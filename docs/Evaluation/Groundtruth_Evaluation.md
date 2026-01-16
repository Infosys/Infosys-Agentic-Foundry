# GroundTruth Evaluation

## Overview
GroundTruth evaluation is used to measure the performance of an AI agent by comparing its generated responses against expected outputs.

GroundTruth evaluation is a method to assess AI agent performance by comparing its generated responses against a set of known correct outputs, called ground truth. This comparison allows for deterministic measurement of the AI system’s quality and alignment with expected outcomes. Ground truth data represents factual and intended responses that serve as a benchmark for evaluating models in tasks like question-answering.

The evaluation typically involves multiple similarity and accuracy metrics to capture semantic alignment, lexical overlap, and exact match quality. Semantic metrics assess whether the AI captures the meaning of the expected response, while lexical metrics measure the textual similarity. This approach helps quantify aspects such as correctness, conciseness, and faithfulness to the ground truth, and it can also be used to detect hallucinations or errors.

By applying GroundTruth evaluation, developers and data scientists can create reproducible and interpretable benchmarks, compare different AI model architectures or configurations, monitor performance drift over time, and make informed decisions about deployment and improvements. This practice is critical for ensuring trustworthy and high-quality AI systems in real-world applications.

---

To perform the evaluation, users must provide the following information:

- **Agent Name**: A unique identifier for the AI agent being evaluated.
- **Model Name**: The specific model version or configuration used by the agent.
- **Agent Type**: The category or type of the agent (e.g., react, multi).
- **Input File Upload**: A `.csv` or `.xlsx` file containing two required columns:
    - `queries`: The input prompts or questions sent to the AI agent.
    - `expected_outputs`: The correct or intended responses for each query.

---

## Execution and Analysis

The system executes evaluation and generates:

  - Average similarity scores across multiple metrics.
  - Diagnostic summary highlighting semantic and textual alignment.
  - Optional LLM grading for human-like quality score alongside similarity metrics.

- After evaluation, user can Download to get an Excel report with detailed scores per query.

---

## Sample Diagnostic Summary

!!! Info "Example Diagnostic Summary"
    The AI responses show strong semantic alignment with expected outputs (e.g., high SBERT similarity: 0.893, LLM score: 0.875), indicating correct conceptual understanding. However, lexical metrics like TF-IDF cosine similarity (0.680), Jaccard similarity (0.600), and BLEU score (0.500) are lower, reflecting variations in wording. Moderate sequence match (0.688) and ROUGE scores support partial textual overlap. Very low exact match (0.125) shows rare verbatim matches. Overall, the AI captures the essence well with diverse phrasing.

---

## Results and Download

Post-evaluation displays:

- Diagnostic summary average.
- Scores for all similarity metrics.
- Downloadable Excel report provides comprehensive, granular insights into the AI agent's performance across various similarity and quality metrics.

