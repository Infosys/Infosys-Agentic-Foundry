# Prompt Optimizer Overview

The Prompt Optimizer is an automated system that improves the instructions, or system prompt, used by your AI agent. It does this by generating, testing, and evolving multiple prompt versions to find the most accurate, reliable, and efficient configuration for your use case. The optimizer uses a data-driven approach and continuous testing to reduce hallucinations, malfunctions, and inefficiency in agent responses.

## User Input and Configuration

To start the optimization process, users configure several key settings:

- **LLM Provider**: Choose from available language model providers.
- **Agent Type**: Select either a Foundry Agent (by providing an Agent ID) or a Logical Agent (by entering an initial prompt).
- **Population Size**: Set how many prompt candidates are generated and tested per cycle.
- **Number of Cycles**: Specify how many optimization rounds to run.
- **Score Threshold**: Define the minimum average score required for a prompt to be considered successful.
- **Dataset**: Provide agent queries and expected responses for evaluation.

These settings guide the optimizer in generating, evaluating, and refining prompts to achieve the best performance.


!!! info "Purpose and Motivation"

    Poorly optimized prompts can cause hallucinations, malfunctions, and inefficiency in agent responses. Hallucinations occur when the AI makes up facts or actions. Malfunctions happen when the AI misuses tools, follows broken reasoning, or produces inconsistent output. Inefficiency results in responses that are too verbose, unclear, or slow. The Prompt Optimizer addresses these issues through data-driven refinement and continuous testing.

## Pareto Sampling

Pareto sampling is a method used to select the most robust prompt candidates for the next cycle. A prompt is considered dominant if it performs well across all metrics without being outperformed by another prompt. This ensures that the selected prompts are balanced and reliable, avoiding the risk of over-optimization in a single area.

## Lesson Manager

The lesson manager plays a critical role in refining prompts that do not meet the desired performance threshold. It extracts insights from failed or low-performing prompts and applies these lessons to generate new candidates. By removing duplicate lessons and focusing on actionable improvements, the lesson manager ensures that each cycle produces stronger and more effective prompts.

## Working Process

The working process employs an LLM as a judge approach to evaluate and optimize prompts through multiple optimization cycles. Each prompt candidate is tested on the provided dataset, generating four key performance metrics for every response: 

- **Accuracy** – factual correctness.
- **Tool Usage** – choosing and using tools/API calls correctly.
- **Clarity** – clear and logical output.
- **Brevity** – concise and to the point.

**Process Example:**

Consider an optimization scenario where the population size is set to five prompt candidates, the user defines a performance threshold, and configures the system to run multiple optimization cycles. Here's how the process unfolds:

**Initial Generation and Evaluation:**

The optimizer begins by creating five distinct prompt candidates, each with different approaches to instruction formatting, tone, and structure. All five candidates are then tested against the provided dataset. For each prompt's response to every query in the dataset, the LLM judge evaluates four metrics: `accuracy`, `tool usage`, `clarity`, and `brevity`. This comprehensive evaluation produces four performance scores per prompt, generating a total of twenty individual metric scores across all candidates in the cycle.

**Threshold Analysis and Lesson Generation:**

The system calculates the average performance score for each prompt candidate. Any prompt whose average score falls below the user-defined threshold is flagged for improvement. For these underperforming prompts, the optimizer analyzes their specific weaknesses and generates targeted lessons. These lessons capture insights about what went wrong and provide guidance for creating better prompts in future iterations.

**Pareto-Based Selection:**

The optimizer then applies Pareto-based sampling to identify the most balanced and robust prompt candidates. Rather than simply selecting the highest-scoring prompts, this method identifies prompts that perform consistently well across all four metrics without significant weaknesses in any area. Typically, two to three dominant candidates emerge from this selection process and advance to the next optimization cycle.

**Advanced Improvement Techniques:**

When the system identifies failures or consistently low-performing examples, it activates two specialized improvement mechanisms:

The **reflection agent** conducts a deep analysis of all available performance data, including individual metric scores, average scores across all candidates, and complete execution trace data. By examining these patterns, it identifies specific issues such as unclear instructions, improper tool usage guidance, or verbose language. Based on these insights, the reflection agent generates new prompt candidates specifically designed to address the identified weaknesses.

The **lesson manager** serves as a complementary improvement mechanism. It systematically extracts and processes lessons from previous optimization cycles, removes duplicate insights, and refines the accumulated knowledge. When the reflection agent doesn't generate sufficient new candidates, the lesson manager leverages this refined knowledge base to create additional high-quality prompt alternatives.

**Convergence and Completion:**

The optimization process continues through multiple cycles until convergence is achieved. Convergence occurs when all prompt candidates consistently meet or exceed the performance threshold across all metrics. At this point, no additional reflection or lesson generation is necessary, and the system selects the optimal prompt as the final output.

In convergence cases where all prompts exceed the threshold, no reflection or lesson manager steps are triggered, and no additional lessons are generated. The process concludes with the selection of the optimal prompt.

The optimizer provides a comprehensive final output, including the optimized prompt, a detailed evaluation report, and a comparison between the initial and final prompts, highlighting all improvements made during the optimization process.

## Optimization Benefits and Deliverables

**Hallucination and Malfunction Prevention**

The optimizer ensures correct tool use, clear and logical reasoning, and robust error handling. Prompts are optimized to handle edge cases and invalid inputs gracefully. Balanced multi-metric optimization ensures that a prompt must perform well in all key areas, not just one.

**Output Components**

You receive a final optimized prompt tailored to your workflows and tested on real scenarios. An audit trail is provided in Excel or JSON format, logging all candidates, scores, and prompt evolution. A before and after diff shows exactly what changed in the instructions. The process reduces hallucinations and failures, and metrics can be customized for your priorities, such as safety, detail level, or tone.

**Business Impact**

The Prompt Optimizer delivers higher accuracy, consistent performance across tasks and edge cases, and time savings through automation. It provides transparency with full visibility into what changed, why, and how it improves performance. The process is scalable and can be re-run whenever tasks, tools, or requirements change.

**Final Deliverables**

The deliverables include:

- optimized_prompt.txt – the final prompt ready for deployment
- prompt_diff_report.json – before and after changes
- optimization_log.xlsx – detailed scoring and evolution history
