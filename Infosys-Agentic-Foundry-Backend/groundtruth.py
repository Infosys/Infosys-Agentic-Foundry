# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import sys
import os
import asyncio
import pandas as pd
import datetime
from typing import Union
from difflib import SequenceMatcher
import uuid
from langchain.prompts import PromptTemplate
from langchain_core.runnables import Runnable
from pathlib import Path
from fuzzywuzzy import fuzz  
import psutil
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from rouge_score import rouge_scorer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer, util

from src.inference.base_agent_inference import AgentInferenceRequest, BaseAgentInference
from telemetry_wrapper import logger as log

# ✅ Load SBERT model
# sbert_model = SentenceTransformer(r'C:\Users\kotni.greeshma\Downloads\models\all-MiniLM-L6-v2')
sbert_model = SentenceTransformer('all-MiniLM-L6-v2')

# ✅ LLM prompt templates
grading_prompt = PromptTemplate(
    input_variables=["query", "expected_response", "actual_response"],
    template="""
You are an expert evaluator for AI-generated responses.

Your task is to assign a score between 0.0 and 1.0 based on how well the actual response answers the user query **and** aligns with the expected response.

Rate based on the following criteria:

1. **Relevance** — Does the actual response directly address the user’s query?
2. **Correctness** — Is the information in the response factually or logically correct?
3. **Completeness** — Does the actual response include all important elements found in the expected response?
4. **Clarity & Language Quality** — Is the response understandable, coherent, and well-phrased?
5. **Semantic Similarity** — Even if the wording is different, does the actual response convey the same meaning as the expected one?

Each point contributes equally to the overall rating. Do not penalize for minor phrasing differences if the meaning is preserved.

---

**User Query**: {query}

**Expected Response**: {expected_response}

**Actual Response**: {actual_response}

---

Provide **only** a single decimal number between 0.0 and 1.0 (e.g., 0.85), with no explanation or extra text.
"""
)


diagnostic_prompt = PromptTemplate(
    input_variables=["scores_dict"],
    template="""
You are an AI evaluation analyst.

You are given average metric scores from an evaluation of an AI agent’s responses compared to expected outputs.

Here are the average scores:
{scores_dict}

Each score represents a different aspect of similarity:
- TF-IDF, Jaccard, BLEU, ROUGE → surface/textual overlap.
- SBERT → semantic similarity.
- LLM score → human-like judgment of correctness.

Based on these scores, provide a diagnostic summary: What do these scores reveal about the agent’s performance? Highlight whether the responses were semantically aligned but textually different, or vice versa.

Be specific and concise. Do not just list the scores again — explain what the pattern means.
"""
)

# ✅ Unified agent call
async def call_agent(query, model_name, agentic_application_id, session_id, agent_type, specialized_agent_inference: BaseAgentInference):
    req = AgentInferenceRequest(
        agentic_application_id=agentic_application_id,
        query=query,
        session_id=session_id,
        model_name=model_name,
        reset_conversation=True
    )
    try:
        response = await specialized_agent_inference.run(req)
        result = response if isinstance(response, dict) else {"response": f"Error: {response}"}
    except Exception as e:
        log.error(f"Error calling agent: {str(e)}")
        result = {"response": f"Exception: {str(e)}"}
    return result.get("response", f"Invalid or error response for query: {query}")



async def evaluate_ground_truth_file(
    model_name: str,
    agent_type: str,
    file_path: Union[str, os.PathLike],
    agentic_application_id: str,
    session_id: str,
    specialized_agent_inference: BaseAgentInference,
    llm=None,
    use_llm_grading: bool = False
) -> tuple[pd.DataFrame, dict, str, str, str, Union[str, None]]:
    if file_path.endswith(".csv"):
        df = pd.read_csv(file_path)
    elif file_path.endswith((".xlsx", ".xls")):
        df = pd.read_excel(file_path)
    else:
        raise ValueError("File must be a CSV or Excel file.")

    if 'queries' not in df.columns or 'expected_outputs' not in df.columns:
        log.error("File must contain 'queries' and 'expected_outputs' columns.")
        raise ValueError("File must contain 'queries' and 'expected_outputs' columns.")

    # Initialize metrics
    actual_outputs, jaccard_scores, sequence_ratios = [], [], []
    bleu_scores, rouge1_scores, rougeL_scores = [], [], []
    expected_texts, actual_texts, sbert_scores = [], [], []
    tfidf_cosine_scores, llm_scores = [], []
    exact_match_scores, fuzzy_match_scores = [], []

    # Setup
    smoothie = SmoothingFunction().method4
    rouge = rouge_scorer.RougeScorer(['rouge1', 'rougeL'], use_stemmer=True)
    grading_chain = (grading_prompt | llm) if use_llm_grading and llm else None

    # Evaluation loop
    for i, row in df.iterrows():
        query = str(row["queries"])
        expected = str(row["expected_outputs"])

        log.info(f"\nQuery {i+1}: {query}")
        actual = await call_agent(query, model_name, agentic_application_id, session_id, agent_type, specialized_agent_inference)
        actual_outputs.append(actual)
        expected_texts.append(expected)
        actual_texts.append(actual)

        # Similarity metrics
        set1, set2 = set(expected.lower().split()), set(actual.lower().split())
        jaccard_scores.append(len(set1 & set2) / len(set1 | set2) if set1 | set2 else 0)
        sequence_ratios.append(SequenceMatcher(None, expected, actual).ratio())
        bleu_scores.append(sentence_bleu([expected.split()], actual.split(), smoothing_function=smoothie))
        rouge_scores = rouge.score(expected, actual)
        rouge1_scores.append(rouge_scores["rouge1"].fmeasure)
        rougeL_scores.append(rouge_scores["rougeL"].fmeasure)

        emb1 = sbert_model.encode(expected, convert_to_tensor=True)
        emb2 = sbert_model.encode(actual, convert_to_tensor=True)
        sbert_scores.append(util.cos_sim(emb1, emb2).item())

        exact_match_scores.append(1.0 if expected.strip() == actual.strip() else 0.0)
        fuzzy_match_scores.append(fuzz.ratio(expected, actual) / 100.0)

        # LLM grading
        if use_llm_grading and llm:
            try:
                result = await grading_chain.ainvoke({
                    "query": query,
                    "expected_response": expected,
                    "actual_response": actual
                })
                score = float(result.content.strip().split()[0])
                llm_scores.append(max(0.0, min(1.0, score)))
            except Exception as e:
                llm_scores.append(0.0)
                log.error(f"Error during LLM grading: {str(e)}")

    # TF-IDF similarity
    vectorizer = TfidfVectorizer().fit(expected_texts + actual_texts)
    expected_vecs = vectorizer.transform(expected_texts)
    actual_vecs = vectorizer.transform(actual_texts)
    tfidf_cosine_scores = [
        cosine_similarity(expected_vecs[i], actual_vecs[i])[0][0] for i in range(len(expected_texts))
    ]

    # Assign metrics to DataFrame
    df["actual_outputs"] = actual_outputs
    df["tfidf_cosine_similarity"] = tfidf_cosine_scores
    df["jaccard_similarity"] = jaccard_scores
    df["sequence_match_ratio"] = sequence_ratios
    df["bleu_score"] = bleu_scores
    df["rouge1_f1"] = rouge1_scores
    df["rougeL_f1"] = rougeL_scores
    df["sbert_similarity"] = sbert_scores
    df["exact_match"] = exact_match_scores
    df["fuzzy_match"] = fuzzy_match_scores
    if grading_chain:
        df["llm_score"] = llm_scores


    # Average scores
    metric_cols = [
        "tfidf_cosine_similarity", "sbert_similarity", "jaccard_similarity",
        "sequence_match_ratio", "bleu_score", "rouge1_f1", "rougeL_f1",
        "exact_match", "fuzzy_match"
    ]
    if grading_chain:
        metric_cols.append("llm_score")
    avg_scores = df[metric_cols].mean().to_dict()

    # Append average row
    avg_row = {
        "queries": "--- AVERAGES ---",
        "expected_outputs": "",
        "actual_outputs": "",
        **{metric: avg_scores[metric] for metric in metric_cols}
    }
    df = pd.concat([df, pd.DataFrame([avg_row])], ignore_index=True)

    # Optional LLM diagnostic summary
    summary = ""
    if llm:
        scores_text = "\n".join(f"{k}: {v:.3f}" for k, v in avg_scores.items())
        summary_chain = diagnostic_prompt | llm
        result = await summary_chain.ainvoke({"scores_dict": scores_text})
        summary = result.content.strip()
    else:
        log.warning("No LLM model provided for diagnostic summary generation.")
        summary = "No LLM diagnostic summary generated. Please provide an LLM model for detailed analysis."

    # Save output to files
    output_dir = Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_uuid = str(uuid.uuid4())
    base_filename = f"evaluation_results_{generated_uuid}"

    excel_path = output_dir / f"{base_filename}.xlsx"
    df.to_excel(excel_path, index=False)

    return avg_scores, summary, str(excel_path)
