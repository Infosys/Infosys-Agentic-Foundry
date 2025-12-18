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
from rapidfuzz import fuzz  
from dotenv import load_dotenv
import psutil
from nltk.translate.bleu_score import sentence_bleu, SmoothingFunction
from rouge_score import rouge_scorer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from src.utils.remote_model_client import RemoteSentenceTransformer as SentenceTransformer
from src.utils.remote_model_client import RemoteSentenceTransformersUtil
util = RemoteSentenceTransformersUtil()
from src.utils.remote_model_client import RemoteSentenceTransformer, ModelServerClient
from typing import Optional, Callable, Awaitable

from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.schemas import AgentInferenceRequest
from telemetry_wrapper import logger as log

# Load environment variables from .env file
load_dotenv()

# Initialize SBERT model 
model_server_url = os.getenv("MODEL_SERVER_URL", "").strip()
sbert_model = None

if not model_server_url or model_server_url.lower() == "none":
    log.info("MODEL_SERVER_URL not configured. SBERT model will be unavailable for ground truth evaluation.")
else:
    try:
        log.info(f"Connecting to model server at {model_server_url}")
        client = ModelServerClient(model_server_url)
        if client.server_available:
            sbert_model = RemoteSentenceTransformer(client=client)
            log.info("Remote SBERT model initialized successfully.")
        else:
            log.warning("Model server is not available. SBERT model will be unavailable for ground truth evaluation.")
    except Exception as e:
        sbert_model = None
        log.error(f"Failed to connect to remote SBERT model: {e}")


# ✅ LLM prompt templates
grading_prompt = PromptTemplate(
    input_variables=["query", "expected_response", "actual_response"],
    template="""
You are an expert evaluator for AI-generated responses.

Your task is to assign a score between 0.0 and 1.0 based on how well the actual response answers the user query **and** aligns with the expected response.

Rate based on the following criteria:

1. **Relevance** — Does the actual response directly address the user's query?
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

You are given average metric scores from an evaluation of an AI agent's responses compared to expected outputs.

Here are the average scores:
{scores_dict}

Each score represents a different aspect of similarity:
- TF-IDF, Jaccard, BLEU, ROUGE → surface/textual overlap.
- SBERT → semantic similarity.
- LLM score → human-like judgment of correctness.

Based on these scores, provide a diagnostic summary: What do these scores reveal about the agent's performance? Highlight whether the responses were semantically aligned but textually different, or vice versa.

Be specific and concise. Do not just list the scores again — explain what the pattern means.
"""
)

# Unified agent call
# async def call_agent(query, model_name, agentic_application_id, session_id, agent_type, inference_service: CentralizedAgentInference):
#     req = AgentInferenceRequest(
#         query=query,
#         agentic_application_id=agentic_application_id,
#         session_id=session_id,
#         model_name=model_name,
#         reset_conversation=True
#     )
#     try:
#         response = await anext(inference_service.run(req))
#         result = response if isinstance(response, dict) else {"response": f"Error: {response}"}
#     except Exception as e:
#         log.error(f"Error calling agent: {str(e)}")
#         result = {"response": f"Exception: {str(e)}"}
#     return result.get("response", f"Invalid or error response for query: {query}")

async def call_agent(query, model_name, agentic_application_id, session_id, agent_type, inference_service: CentralizedAgentInference):
    req = AgentInferenceRequest(
        query=query,
        agentic_application_id=agentic_application_id,
        session_id=session_id,
        model_name=model_name,
        reset_conversation=True
    )
    
    final_result = {}
    
    try:
        # FIX 1: Don't use anext(). Iterate to get the actual data.
        # If the agent streams, we want the chunk that contains the answer.
        async for response in inference_service.run(req):
            if isinstance(response, dict):
                # Log for debugging (remove later if too noisy)
                log.info(f"DEBUG - Agent Chunk: {response}")
                
                # Update our final result with the latest chunk
                final_result = response
                
                # Optional: If you know the agent stops after sending the answer, 
                # and you found a valid key, you could break here.
                if any(k in response for k in ["response", "answer", "output", "content"]):
                    final_result = response
                    # break # Uncomment if you want to stop at the first valid chunk
            else:
                # Handle cases where response might be a raw string
                final_result = {"response": str(response)}

    except Exception as e:
        log.error(f"Error calling agent: {str(e)}")
        return f"Exception: {str(e)}"

    # FIX 2: Check for multiple common keys, not just "response"
    if "response" in final_result:
        return final_result["response"]
    elif "answer" in final_result:
        return final_result["answer"]
    elif "output" in final_result:
        return final_result["output"]
    elif "content" in final_result:
        return final_result["content"]
    else:
        # Debugging: Print what keys actually exist so you can fix the code
        log.error(f"Missing expected key. keys found: {final_result.keys()} | Full Payload: {final_result}")
        return f"Invalid or error response. Raw Output: {str(final_result)}"



async def evaluate_ground_truth_file(
    model_name: str,
    agent_type: str,
    file_path: Union[str, os.PathLike],
    agentic_application_id: str,
    session_id: str,
    inference_service: CentralizedAgentInference,
    llm=None,
    use_llm_grading: bool = False,
    progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
) -> tuple[pd.DataFrame, dict, str, str, str, Union[str, None]]:
    if file_path.endswith(".csv"):
        if progress_callback:
            await progress_callback("Reading CSV file...")
        df = pd.read_csv(file_path)
    elif file_path.endswith((".xlsx", ".xls")):
        if progress_callback:
            await progress_callback("Reading Excel file...")
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
        if progress_callback:
            await progress_callback(f"Evaluating query {i+1}/{len(df)}")

        actual = await call_agent(
            query=query,
            model_name=model_name,
            agentic_application_id=agentic_application_id,
            session_id=session_id,
            agent_type=agent_type,
            inference_service=inference_service
        )

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
        sbert_scores.append(util.cos_sim(emb1, emb2))

        exact_match_scores.append(1.0 if expected.strip() == actual.strip() else 0.0)
        fuzzy_match_scores.append(fuzz.ratio(expected, actual) / 100.0)

        # LLM grading
        if grading_chain:
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

    if progress_callback:
        await progress_callback("Computing TF-IDF similarity...")

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

    avg_row = {
        "queries": "--- AVERAGES ---",
        "expected_outputs": "",
        "actual_outputs": "",
        **{metric: avg_scores[metric] for metric in metric_cols}
    }
    df = pd.concat([df, pd.DataFrame([avg_row])], ignore_index=True)

    # Diagnostic summary
    summary = ""
    if llm:
        scores_text = "\n".join(f"{k}: {v:.3f}" for k, v in avg_scores.items())
        summary_chain = diagnostic_prompt | llm
        result = await summary_chain.ainvoke({"scores_dict": scores_text})
        summary = result.content.strip()
    else:
        log.warning("No LLM model provided for diagnostic summary generation.")
        summary = "No LLM diagnostic summary generated. Please provide an LLM model for detailed analysis."

    if progress_callback:
        await progress_callback("Saving results to Excel...")

    output_dir = Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_uuid = session_id
    base_filename = f"evaluation_results_{generated_uuid}"
    excel_path = output_dir / f"{base_filename}.xlsx"
    df.to_excel(excel_path, index=False)

    return avg_scores, summary, str(excel_path)
