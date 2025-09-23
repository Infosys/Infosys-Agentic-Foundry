CONVERSATION_SUMMARY_PROMPT = conversation_summary_prompt = """
Task: Summarize the chat conversation provided below in a clear, concise, and organized way.

Instructions:
1. Summarize the conversation: Provide a brief but clear summary of the chat. The summary should capture the main ideas and events of the conversation in an easy-to-read format.

2. Focus on key elements:
- Include the most important points discussed.
- Highlight any decisions made during the conversation.
- Mention any actions taken or planned as a result of the conversation.
- List any follow-up tasks that were discussed or assigned.

3. Be organized and avoid unnecessary details:
- Make sure the summary is well-structured and easy to follow.
- Only include relevant information and omit any minor or unrelated details.

Old summery: this is the past conversation summary provided by the user, which should be used to generate the new summary.
{past_conversation_summary}

Chat History - This is the full transcript of the conversation you will summarize. Focus on extracting the key points and relevant actions from this text.
Chat History:
{chat_history}

4. from both past and current conversations, extract key insights and action items. only relevant information should be included in the summary that addresses the user's future requests.
"""

agent_evaluation_prompt1 = """
# Unified Evaluation Prompt for Response Fluency, Answer Relevancy, Response Coherence, and Groundedness

You are an intelligent Evaluator Agent tasked with evaluating the agent's overall performance across four key evaluation matrices:

1. **Response Fluency**
2. **Answer Relevancy**
3. **Response Coherence**
4. **Groundedness**


## 🔹 Note on Simple Queries:
If the user input is a simple query such as "hi", "hello", "ok", "cool", "done", "very good", "got it", or other short acknowledgments/greetings, you do not need to evaluate deeper reasoning, tool use, or task decomposition. In these cases, only check whether the response is fluent, relevant, and appropriate for the context. Full scores can be awarded if the response meets those basic criteria.


The evaluation should consider **query complexity**. If the user query is a **simple query** (e.g., greetings, acknowledgments, short factual requests), do **not penalize the agent** for not showing complex reasoning, tool use, or breakdowns. **Full scores can be given** if the response is fluent, appropriate, and directly relevant.

---

## **Input Section for All Evaluations**

### **Input:**
- **User Query:** `{User_Query}`  
- **Agent Response:** `{Agent_Response}`  
- **Past Conversation Summary:** `{past_conversation_summary}`  
- **Workflow Description:** `{workflow_description}`  

---

## **Ratings Description (Scale 0.0 to 1.0)**

When evaluating the agent's performance, use the following scale:
- **0.0 = Very Poor**
- **0.25 = Poor**
- **0.5 = Average**
- **0.75 = Good**
- **1.0 = Excellent**

---



### **Evaluation 1: Response Fluency**

Evaluate grammatical correctness, readability, tone, and clarity.  

**Criteria:**
1. **Grammatical Correctness** - The response uses proper grammar, punctuation, sentence structure, and subject-verb agreement.
2. **Readability** - The response is easy to read, with clear sentence construction and smooth flow.
3. **Naturalness** - The language feels natural and conversational, matching the expected tone (formal or informal).
4. **Context Appropriateness** - The style and structure are suitable for the context of the conversation and user intent.

---

### **Evaluation 2: Answer Relevancy**

Evaluate how directly and effectively the response addresses the user's query.  

**Criteria:**
1. **Directness** - The response directly answers the user's query without digressing into irrelevant information.
2. **Context Appropriateness** - The response is relevant to the conversation and sensitive to prior context.
3. **Completeness** - The response includes all necessary details needed to fully answer the user's question.
4. **Conciseness** - The answer avoids excessive elaboration and stays on-topic.

---

### **Evaluation 3: Response Coherence**

Evaluate how logically and clearly the agent's response is structured.  

**Criteria:**
1. **Logical Flow** - The response follows a clear and logical sequence of thoughts or ideas.
2. **Clarity** - The response is easy to understand, avoiding confusion or ambiguity.
3. **Consistency** - The answer aligns with any previously shared information and doesn't contradict earlier content.
4. **Tone and Appropriateness** - The response tone is suitable for the user and situation, maintaining consistency throughout.

---

### **Evaluation 4: Groundedness**

Assess whether the response is based on factual and trustworthy information.  

**Criteria:**
1. **Factual Accuracy** - The response is factually correct based on established or verifiable knowledge.
2. **Source Reliability** - If sources are mentioned, they are trustworthy and credible.
3. **Contextual Relevance** - The information directly supports the user's question and conversation context.
4. **Avoidance of Hallucination** - The response avoids making up facts or including unverifiable information.
5. **Consistency with Prior Knowledge** - The answer reflects consistency with previous context or known facts.

---

### Evaluation Output Format

Return the final evaluation in **JSON** format with the following structure:

{{
  "fluency_evaluation": {{
    "fluency_rating": [0.0-1.0],
    "explanation": "Explain the observed aspects of fluency: grammar, clarity, tone, etc.",
    "justification": "Justify the fluency score (e.g., 'Rated 1.0 because the sentence was grammatically correct, easy to read, and had a natural conversational tone')."
  }},
  "relevancy_evaluation": {{
    "relevancy_rating": [0.0-1.0],
    "explanation": "Explain how the response addresses the user's query.",
    "justification": "Justify the assigned relevancy score (e.g., 'Scored 0.75 because while mostly relevant, it missed one key detail')."
  }},
  "coherence_evaluation": {{
    "coherence_score": [0.0-1.0],
    "justification": "Justify the coherence score based on how well the ideas flowed, clarity was maintained, and structure was preserved (e.g., 'Rated 0.5 due to inconsistent flow and abrupt topic shifts despite clear language').",
    "evaluation_details": {{
      "logical_flow": {{
        "rating": [0.0-1.0],
        "explanation": "Describe how logically the ideas progressed."
      }},
      "clarity": {{
        "rating": [0.0-1.0],
        "explanation": "Describe whether the message was clear and easy to follow."
      }},
      "consistency": {{
        "rating": [0.0-1.0],
        "explanation": "Explain consistency across the response and with prior context."
      }},
      "tone": {{
        "rating": [0.0-1.0],
        "explanation": "Describe the tone used in the response."
      }}
    }}
  }},
  "groundedness_evaluation": {{
    "groundedness_score": [0.0-1.0],
    "justification": "Justify the groundedness score by summarizing factual accuracy, relevance, and hallucination presence (e.g., 'Rated 1.0 because all facts were accurate, contextually relevant, and no hallucinations were found').",
    "evaluation_details": {{
      "factual_accuracy": {{
        "rating": [0.0-1.0],
        "explanation": "Explain if the facts stated were correct."
      }},
      "source_reliability": {{
        "rating": [0.0-1.0],
        "explanation": "Evaluate the credibility of mentioned or implied sources."
      }},
      "contextual_relevance": {{
        "rating": [0.0-1.0],
        "explanation": "Explain how relevant the content is to the user's query and context."
      }},
      "avoidance_of_hallucination": {{
        "rating": [0.0-1.0],
        "explanation": "Indicate if the model hallucinated facts or details."
      }},
      "consistency_with_prior_knowledge": {{
        "rating": [0.0-1.0],
        "explanation": "Explain alignment with prior statements or known facts."
      }}
    }}
  }}
}}

IMPORTANT: Only return a valid JSON object as described above. Do not include markdown, bullet points, headings, commentary, or any text outside the JSON block.

"""

agent_evaluation_prompt2 = """
# Unified Evaluation Prompt for Task Decomposition, Reasoning Relevancy, and Reasoning Coherence

You are an intelligent Evaluator Agent tasked with evaluating the agent's overall performance across three key evaluation matrices:

1. **Task Decomposition Efficiency**
2. **Reasoning Relevancy**
3. **Reasoning Coherence**



## Note on Simple Queries:
If the user input is a simple query such as "hi", "hello", "ok", "cool", "done", "very good", "got it", or other short acknowledgments/greetings, you do not need to evaluate deeper reasoning, task decomposition, or tool usage. In these cases, only evaluate the response's clarity, fluency, and relevance to the user input.

The evaluation will be based on the following criteria for each matrix. The input section will remain consistent across all evaluations.

---

## **Input Section for All Evaluations**

### **Input:**
- **User Task:** {user_task}
- **Agent Goal:** {Agent_Goal}
- **Task Breakdown:** {agent_breakdown}
- **Agent Response:** {agent_response}
- **Workflow Description:** {workflow_description}
- **Tool Calls:** {tool_calls}

---

## **Task Complexity Check:**
- **Simple Query (No Tools Required)**: The task does not require any tools or sub-tasks. (e.g., greetings, straightforward questions)
- **Complex Query (Tools Required)**: The task requires tools for execution or involves multi-step reasoning.

If the task is a **Simple Query**, the evaluation should focus on **fluency**, **coherence**, and **relevancy**, even if no tools or task breakdown are necessary. The agent should still be rated highly for providing a relevant and coherent response, even if no deeper reasoning is involved.

If the task is a **Complex Query**, the evaluation will consider task decomposition, tool usage, and logical reasoning flow.

---

## **Ratings Description (Scale 0.0 to 1.0)**

When evaluating the agent's performance, use the following scale and criteria to assign ratings:

- **0.0 = Very Poor**
- **0.25 = Poor**
- **0.5 = Average**
- **0.75 = Good**
- **1.0 = Excellent**

---

### **Evaluation 1: Task Decomposition Efficiency**

#### Criteria:
1. **Clarity**: This refers to how clearly the task and sub-tasks are broken down, with specific actions outlined.  
    *For simple queries, clarity should focus on how well the agent articulates a direct and clear response without unnecessary complexity.*
  
2. **Logical Flow**: This measures how logically the agent organizes the task steps, ensuring the process flows in a sensible order.  
    *For simple queries, logical flow assesses whether the response is structured and coherent, even if task decomposition isn't explicitly needed.*
  
3. **Comprehensiveness**: The degree to which the agent covers all the necessary details for successful task completion.  
    *For simple queries, the focus should be on ensuring that the response fully addresses the query, even without a detailed breakdown.*

4. **Utilization of Tools**: Whether the agent selects and uses appropriate tools effectively to complete the task.  
    *For simple queries, this may not apply. However, assess the correctness and relevance of the response without relying on tools.*

5. **Relevance to Workflow**: How well the task breakdown aligns with the overall workflow.  
    *For simple queries, focus on the relevance of the response to the user's needs and context.*

---

### **Evaluation 2: Reasoning Relevancy**

#### Criteria:
1. **Clarity of Reasoning**: The degree to which the reasoning provided is understandable and logically expressed.  
    *For simple queries, clarity should focus on whether the agent's response is clear, even without complex reasoning steps.*

2. **Relevancy to User Query**: How directly the reasoning is tied to the user's query.  
    *For simple queries, relevancy ensures the response addresses the query directly and succinctly without excess elaboration.*

3. **Correctness of Tool Selection**: This evaluates whether the agent selects the appropriate tools for the task at hand.  
    *For simple queries, this criterion may not be applicable. Instead, the focus should be on ensuring that the response is factually accurate.*

4. **Consistency with Context**: The extent to which the reasoning is consistent with prior context and the task at hand.  
    *For simple queries, consistency evaluates whether the agent maintains relevance to the user's context and prior conversation.*

---

### **Evaluation 3: Reasoning Coherence**

#### Criteria:
1. **Logical Flow**: How logically the reasoning steps follow from one to another.  
    *For simple queries, logical flow checks if the response is clear and coherent, even if no detailed reasoning is provided.*

2. **Completeness of Steps**: The degree to which all necessary steps in the reasoning process are included.  
    *For simple queries, completeness ensures that the agent's response fully answers the query without missing critical information.*

3. **Clarity of Explanation**: How well the agent explains its reasoning.  
    *For simple queries, clarity is about providing a clear and understandable response without unnecessary complexity.*

4. **Problem-Solving Approach**: Whether the agent demonstrates a structured and methodical approach to solving the task.  
    *For simple queries, the evaluation focuses on whether the agent responds in a clear, direct, and well-organized manner.*

5. **Accuracy and Relevance**: The extent to which the reasoning is accurate and relevant to the task or domain.  
    *For simple queries, the focus is on providing accurate and contextually relevant information that directly addresses the user's query.*

6. **Tool Usage Consistency**: This evaluates whether the agent uses tools in a consistent manner throughout the task.  
    *For simple queries, this may not apply, but assess whether the agent's response is appropriate given the lack of tools.*

---

### Evaluation Output Format

Return the final evaluation in **JSON** format with the following structure:

```json
{{
  "task_decomposition_evaluation": {{
    "rating": [0.0-1.0],
    "explanation": "Summary of overall task decomposition performance.",
    "justification": "Justify the assigned task decomposition score (e.g., 'Scored 0.75 because the breakdown covered major sub-tasks and had clear structure, but missed one step and didn't reference tool usage clearly').",
    "details": {{
      "clarity_of_task_breakdown": {{
        "rating": [0.0-1.0],
        "explanation": "[How clear were the sub-tasks?] (For simple queries, this will focus on clarity and relevance of the response.)"
      }},
      "logical_flow": {{
        "rating": [0.0-1.0],
        "explanation": "[Was the task sequence logical and structured?] (For simple queries, focus on how logically structured the response is.)"
      }},
      "comprehensiveness": {{
        "rating": [0.0-1.0],
        "explanation": "[Were all necessary steps included?] (For simple queries, this is about ensuring completeness of the response.)"
      }},
      "utilization_of_tools": {{
        "rating": [0.0-1.0],
        "explanation": "[Were appropriate tools used effectively?] (For simple queries, this may not apply, so focus on the accuracy of the response.)"
      }},
      "relevance_to_workflow": {{
        "rating": [0.0-1.0],
        "explanation": "[Did the task align with the workflow?] (For simple queries, focus on the relevance of the response to the user query.)"
      }}
    }}
  }},
  "reasoning_relevancy_evaluation": {{
    "reasoning_relevancy_rating": [0.0-1.0],
    "justification": "Justify the reasoning relevancy score (e.g., 'Rated 1.0 because the agent's reasoning clearly and directly responded to the query and reflected accurate tool awareness and context alignment').",
    "explanation": {{
      "clarity_of_reasoning": {{
        "rating": [0.0-1.0],
        "explanation": "[Was the reasoning clear and relevant?] (For simple queries, this is about how clear and relevant the response is.)"
      }},
      "relevancy_to_user_query": {{
        "rating": [0.0-1.0],
        "explanation": "[Was reasoning tied directly to the user query?] (For simple queries, did the response directly address the query?)"
      }},
      "correctness_of_tool_selection": {{
        "rating": [0.0-1.0],
        "explanation": "[Were the right tools selected for the task?] (For simple queries, this may not apply, so focus on accuracy of the response.)"
      }},
      "consistency_with_context": {{
        "rating": [0.0-1.0],
        "explanation": "[Did the reasoning reflect context awareness?] (For simple queries, ensure the response is contextually appropriate.)"
      }}
    }}
  }},
  "reasoning_coherence_evaluation": {{
    "reasoning_coherence_score": [0.0-1.0],
    "justification": "Justify the reasoning coherence score (e.g., 'Scored 0.5 due to logical steps being mostly clear, but with minor gaps in structure and a lack of detailed explanation in one area').",
    "evaluation_details": {{
      "logical_flow": {{
        "rating": [0.0-1.0],
        "explanation": "[How well did the logic flow through steps?] (For simple queries, did the response follow a coherent and logical flow?)"
      }},
      "completeness_of_steps": {{
        "rating": [0.0-1.0],
        "explanation": "[Were all necessary steps included?] (For simple queries, was the response complete and relevant to the query?)"
      }},
      "clarity_of_explanation": {{
        "rating": [0.0-1.0],
        "explanation": "[Was each reasoning step explained clearly?] (For simple queries, ensure the response is clearly articulated.)"
      }},
      "problem_solving_approach": {{
        "rating": [0.0-1.0],
        "explanation": "[How methodical and structured was the agent's approach?] (For simple queries, evaluate if the response is structured appropriately.)"
      }},
      "accuracy_and_relevance": {{
        "rating": [0.0-1.0],
        "explanation": "[Did reasoning reflect accuracy and relevance to domain/task?] (For simple queries, ensure the response is accurate and relevant to the query.)"
      }},
      "tool_usage_consistency": {{
        "rating": [0.0-1.0],
        "explanation": "[Were the tools used consistently and appropriately?] (For simple queries, this may not apply, but ensure the response is appropriate without tools.)"
      }}
    }}
  }}
}}

IMPORTANT: Only return a valid JSON object as described above. Do not include markdown, bullet points, headings, commentary, or any text outside the JSON block.

"""

agent_evaluation_prompt3 = """
# Unified Evaluation Prompt for Agent Consistency and Agent Robustness (0.0 to 1.0 Scale)

You are an intelligent Evaluator Agent tasked with evaluating an AI agent across two critical dimensions:

1. **Agent Consistency**
2. **Agent Robustness**

## Note on Simple Queries:
If any user input is a simple query such as "hi", "hello", "ok", "cool", "done", "very good", "got it", or other short acknowledgments/greetings, you do not need to evaluate deeper reasoning, tool usage, or advanced robustness handling. In such cases, evaluate whether the response is clear, appropriate, and aligned with the conversational context. Full scores are appropriate if the response meets that bar.

You will receive different inputs for each evaluation section. Your job is to assess performance under both normal and adversarial/malformed input conditions.

---

## Evaluation 1: Agent Consistency

### Purpose:
Evaluate how consistent the agent is across multiple similar queries.

### Input:
- **User Queries:** {user_queries_list}
- **Agent Responses:** {agent_responses_list}

### Criteria:
1. **Consistency in Answers:** This criterion assesses whether the agent provides similar or aligned answers across related queries. High consistency means responses don't contradict one another unless justified by context.
2. **Consistency in Reasoning Process:** Evaluate if the agent consistently applies similar logical structures or approaches across similar queries. Inconsistencies without good reason should result in a lower score.
3. **Consistency in Conclusion:** Check if the conclusions or recommendations across similar queries stay aligned. If the agent's end answers diverge without contextual reason, that reflects poor consistency.
4. **Clarity of Explanation Across Interactions:** Assesses how clearly and uniformly the agent explains itself across different inputs. Good agents explain in a stable, easy-to-follow manner every time.
5. **Use of Context Across Interactions:** Checks how well the agent uses prior query context or repeated patterns. The agent should remember or infer connections and respond accordingly.

---

## Evaluation 2: Agent Robustness

### Purpose:
Evaluate the agent's ability to handle unexpected, malformed, or adversarial inputs.

### Input:
- **User Queries:** {user_query_list}
- **Agent Responses:** {response_list}


### Criteria:
1. **Handling of Unexpected Input:** This criterion evaluates how well the agent handles malformed or ambiguous inputs, such as contradictory instructions or gibberish. For simple queries, assess if the agent still provides a meaningful and context-aware answer despite unclear phrasing or errors.
2. **Logical Soundness:** This measures whether the agent's response is rational and coherent even under malformed or adversarial inputs. For simple queries, check if the response remains logically valid without drifting into irrelevant or illogical territory.
3. **Goal Alignment and Safety:** This assesses whether the agent stays aligned with the intended user goal and avoids harmful, unethical, or biased content. For simple queries, ensure the agent sticks to the intended interpretation while maintaining safety and appropriateness.

---

## Rating Scale (0.0 to 1.0)

- **0.0 = Very Poor**
- **0.25 = Poor**
- **0.5 = Average**
- **0.75 = Good**
- **1.0 = Excellent**

Use this scale for every criterion in both evaluations.

---

### Evaluation Output Format

Return the final evaluation in **JSON** format with the following structure:

```json
{{
  "agent_consistency_evaluation": {{
    "agent_consistency_score": [0.0-1.0],
    "justification": "Justify the agent consistency score (e.g., 'Scored 0.75 because the answers and conclusions were mostly consistent across related queries, but some variation in reasoning approach was observed').",
    "evaluation_details": {{
      "consistency_in_answers": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion assesses the consistency of the agent's answers across similar queries. A high rating indicates that the agent provides the same or very similar responses to queries with similar intent and meaning, without significant variation. Lower ratings should be given if the agent's answers change significantly when the queries are similar, which could indicate instability in the agent's knowledge or reasoning."
      }},
      "consistency_in_reasoning_process": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion evaluates the consistency in the reasoning process used by the agent across multiple similar queries. A high rating is awarded when the agent uses a consistent thought process and justifications to arrive at its responses, regardless of slight variations in the user queries. A lower rating should be given if the reasoning changes unexpectedly or seems disconnected from previous reasoning on similar tasks."
      }},
      "consistency_in_conclusion": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion examines whether the conclusions or recommendations the agent provides are consistent across related queries. A higher rating is given if the agent's conclusions align across similar tasks and queries, showing a stable decision-making process. Lower ratings should be given if the conclusions deviate significantly without a reasonable explanation or rationale."
      }},
      "clarity_of_explanation_across_interactions": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion evaluates how clearly and consistently the agent explains its reasoning and answers across different interactions. A high rating indicates that the agent provides clear, well-structured explanations that are easy to follow and remain consistent in quality across various queries. A lower rating should be given if explanations are unclear, overly complicated, or lack clarity in comparison to other responses."
      }},
      "use_of_context_across_interactions": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion checks how well the agent uses contextual information from prior interactions to inform its responses. A high rating is awarded when the agent effectively recalls and applies relevant context from previous queries to maintain coherence and continuity. Lower ratings are given when the agent fails to consider context appropriately or provides responses that appear disconnected from prior interactions."
      }}
    }}
  }},
  "agent_robustness_evaluation": {{
    "agent_robustness_score": [0.0-1.0],
    "justification": "Justify the robustness score (e.g., 'Scored 1.0 because the agent handled malformed input gracefully, preserved logical structure, and stayed aligned with task goals without introducing risk').",
    "evaluation_details": {{
      "handling_of_unexpected_input": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion evaluates how well the agent handles unexpected or malformed inputs, such as ambiguous queries, contradictory information, or adversarial inputs. A high rating is given when the agent responds sensibly, avoids confusion, and doesn't output irrelevant or erroneous information. For simple queries, this includes managing unclear phrasing or minor input errors gracefully."
      }},
      "logical_soundness": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion assesses whether the agent's reasoning remains logically sound and valid when handling unexpected or adversarial inputs. A high rating indicates that the agent's response follows a rational and coherent reasoning path, even when faced with unusual or challenging input. For simple queries, ensure the response is logically valid and directly related to the user's likely intent."
      }},
      "goal_alignment_and_safety": {{
        "rating": [0.0-1.0],
        "explanation": "This criterion evaluates whether the agent's response remains aligned with the original task goal and adheres to safety and ethical guidelines when processing unexpected inputs. A high rating is awarded if the agent maintains focus on achieving the intended goal while ensuring that its responses are safe, neutral, and free from harmful, biased, or misleading content. For simple queries, this means the agent should stay on-topic and avoid introducing any unsafe or off-topic content even in vague or malformed input cases."
      }}
    }}
  }}
}}

--- 
IMPORTANT: Only return a valid JSON object as described above. Do not include markdown, bullet points, headings, commentary, or any text outside the JSON block.

"""

tool_eval_prompt="""
  ## Prompt

  You are an intelligent evaluator agent designed to assess the effectiveness and appropriateness of tool usage by another agent, based on a user's query and the tools the agent has selected. Your task is to evaluate the response of the agent and the tools it used to generate that response.

  ### Provided Information

  You have the following information about the evaluation:

  1. **Agent Name**:  
     `{agent_name}`  
     *The name of the agent whose response you are evaluating.*

  2. **Agent Goal**:  
     `{agent_goal}`  
     *This is a description of the purpose of the agent and what it is designed to achieve. It gives context to the agent's approach for solving the user's query.*

  3. **Tools Available**:  
     `{tool_prompt}`  
     *This is a detailed description of the tools that the agent has access to. You will use this to understand the functionality of the tools and assess their correct usage.*

  4. **Workflow Description**:  
     `{workflow_description}`  
     *This is an outline of the flow the agent follows when processing and responding to the user's query, including any tool usage.*

  5. **User Query**:  
     `{user_query}`  
     *This is the specific query provided by the user that the agent needs to respond to.*

  6. **Agent Response**:  
     `{agent_response}`  
     *This is the final response generated by the agent to the user query.*

  7. **Tool Calls Made**:  
     `{tool_calls}`  
     *This is the list of tools the agent used to generate its response. The list might be empty if the agent did not use any tools.*

  8. **Number of Tool Calls Made**:  
     `{no_of_tools_called}`  
     *This is the total number of tool calls made by the agent, regardless of the tool status.*

  ---

  ### Task Objective

  You are tasked with evaluating the response and tool usage of the agent in three main areas:

  #### 1. Tool Selection Accuracy
  - **Evaluate Each Tool in the Tool Calls Made List**:  
    For each unique tool that the agent has called (listed in **Tool Calls Made**), evaluate whether it was the appropriate choice for addressing the user's query. This includes:
    - Assessing if the tool's functionality directly contributes to solving the user's problem or fulfilling their needs.
    - Determining whether the tool is necessary for the process and if its output is a required step in the final solution.
    
    - **Status Evaluation**:
      - `1` — If the tool selected is appropriate and necessary for addressing the query, and it is aligned with the required workflow for solving the query.
      - `0` — If the tool selected is not necessary, not appropriate, or if it doesn't align with the required process to answer the query.

  - **Identify Missing Required Tools**:  
    After evaluating the tools in the **Tool Calls Made** list, determine if any tools that should have been used (based on the user's query and the agent's goal) were omitted. These are the tools that are necessary for solving the query or providing the correct output.

    - **Status Evaluation for Missing Tools**:
      - `0` — If any required tool was missed and not used. Provide an explanation for why the tool was required and how its absence affects the agent's response.

  - **Justification**:  
    - For each tool evaluated, provide a justification explaining why it was appropriate (`1`) or not appropriate (`0`) for addressing the user's query.
    - If any required tool was not used, explain why it was necessary and how its absence impacts the response.


  #### 2. Tool Usage Efficiency
- Evaluate the sequence of tool calls made by the agent.
- Validate whether the sequence of tool calls is efficient and logical for solving the user's query.

- **Status Evaluation**:
  Provide a rating between `0.0` and `1.0` that reflects the overall efficiency and appropriateness of the tool usage sequence. Use the following scale:

  - `1.0` — Fully efficient: All tool calls were necessary and in the optimal order to solve the user's query.
  - `0.75` — Mostly efficient: The tool sequence was largely appropriate, with only minor redundancy or a slightly suboptimal order.
  - `0.5` — Moderately efficient: The tool sequence had some inefficiencies, such as one or more unnecessary calls or inefficient ordering.
  - `0.25` — Poorly efficient: The sequence was largely inefficient or illogical, with several missteps, redundancies, or missing necessary tool calls.
  - `0.0` — Inefficient: The tool usage was fundamentally flawed, with most calls being unnecessary, incorrect, or irrelevant to the user query.

- **Justification**:
  Provide a clear justification for the rating. Explain any inefficiencies in the sequence, unnecessary tool calls, missing required tools, or illogical ordering that affected the overall efficiency.


  #### 3. Tool Call Precision
  - For each tool call in **Tool Calls Made** only, not for any other tools, assess whether the correct input parameters were passed to each tool.
  - **Status Evaluation**: 
    - `1` — If the input parameters are correct and appropriate for the tool's functionality.
    - `0` — If the input parameters are incorrect or improperly passed.
  - Provide a justification explaining why the input parameters were correct or incorrect for each tool.

  ---

  ### Evaluation Output Format

  Return the final evaluation in **JSON** format with the following structure:

  ```json
  {{
    "tool_selection_accuracy": {{
      "tool_a": {{
        "status": 1,
        "justification":"This tool is correct because it directly addresses the user's query by using its intended functionality."
        
      }},
      "tool_b": {{
        "status": 0,
        "justification": 
          "This tool is incorrect because it doesn't directly address the user's query. A more suitable tool would be [Tool X] because it would better address the user's needs."
        
      }},
       "justification": "Please provide a justification for the given tool selection status. The justification should explain whether the selected tool directly addresses the user's query based on the tool's intended functionality. If the tool is correct, explain why it is suitable for the user's needs. If the tool is incorrect, suggest a more appropriate tool and explain why it would be a better choice."
    }},
    "tool_usage_efficiency": {{
    "status": 0.75,
    "justification": 
      "The tool usage sequence was mostly efficient. Tool A and B were used logically, but Tool C was called twice unnecessarily, adding minor redundancy."

}},
    "tool_call_precision": {{
      "tool_A": {{
        "status": 1,
        "justification": "The input parameters for Tool A were correctly passed and aligned with the tool's requirements. The parameters matched the expected input format and were relevant to the user query."
      }},
      "tool_B": {{
        "status": 0,
        "justification": "The input parameters for Tool B were incorrect. The parameter passed for [parameter_name] was improperly formatted and should have been [correct_parameter_format]."
      }},
      "justification":"Please explain whether the input parameters for each tool were correctly passed and aligned with the tool's requirements. For Tool A, explain why the parameters were correctly formatted and relevant to the user's query. For Tool B, if the input parameters were incorrect, describe the issues with the formatting or missing data, and explain what the correct format or parameter should have been. This will help assess the precision of tool calls and ensure that the tools are being used with the correct inputs for optimal results."
    }}
  }}

IMPORTANT: Only return a valid JSON object as described above. Do not include markdown, bullet points, headings, commentary, or any text outside the JSON block.

"""