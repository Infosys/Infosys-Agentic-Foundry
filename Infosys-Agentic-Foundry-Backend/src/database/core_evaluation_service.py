# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import ast
import json

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.prompts.prompts import (
    agent_evaluation_prompt1,
    agent_evaluation_prompt2,
    tool_eval_prompt
)

from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.database.services import EvaluationService
from src.models.model_service import ModelService
from telemetry_wrapper import logger as log



class CoreEvaluationService:
    """
    Service layer for managing evaluation metrics.
    Orchestrates repository calls for evaluation data, agent metrics, and tool metrics.
    Handles data preparation and serialization for database insertion.
    """

    def __init__(
            self,
            evaluation_service: EvaluationService,
            centralized_agent_inference: CentralizedAgentInference,
            model_service: ModelService
        ):
            self.evaluation_service = evaluation_service
            self.agent_inference = centralized_agent_inference
            self.model_service = model_service


    async def _evaluate_agent_performance(
        self,
        llm,
        User_Query: str,
        Agent_Response: str,
        Agent_Goal: str,
        Steps,
        Workflow_Description: str,
        weights = None
    ):
        """
        Performs the core agent performance evaluation using LLM calls.
        """
        
        agent_breakdown_prompt = ChatPromptTemplate.from_template("""
You are a **highly efficient summarization agent**. Your task is to **analyze and extract task breakdown steps** performed by the agent from the given data.
Consider **tool calls, actions, and responses** to structure the breakdown clearly and logically.

#### **Instructions:**
- **Identify key steps** taken by the agent.
- **Group related actions** under appropriate categories.
- **Highlight error handling and escalation** if applicable.
- Format the response in **numbered steps** with **bold subcategories** if necessary.
- Ensure the steps **flow logically**, showing dependencies where applicable.

---#### **Now, process the following data and extract the steps, Give me the summary for it:**
{Steps}
""")
        agent_breakdown_chain = agent_breakdown_prompt | llm | StrOutputParser()
        agent_breakdown = await agent_breakdown_chain.ainvoke({"Steps": Steps})

        past_conversation_summary = await llm.ainvoke(f"""
You are an **LLM conversation summarization agent**. Your task is to **extract only the past conversation summary** from the following conversation steps. Do not include ongoing conversation details. Provide a concise yet informative summary of the past conversation.

#### **Instructions:**  
- Focus only on summarizing the **past conversation** section.
- Extract and summarize the **key points** and **responses** from the past conversation section provided below.
- Ensure to avoid ongoing conversation details and focus purely on **completed exchanges**.

Past Conversation Summary:
{Steps}

""")
        past_conversation_summary = past_conversation_summary.content if hasattr(past_conversation_summary, "content") else str(past_conversation_summary)

        # Extract tool calls and their statuses from raw Steps
        tool_calls_extracted = []
        for step_msg in Steps:
            if step_msg.get('type') == 'ai' and step_msg.get('tool_calls'):
                tool_calls_extracted.extend(step_msg['tool_calls'])
        statuses_extracted = [step_msg for step_msg in Steps if step_msg.get('type') == 'tool']

        for tool_call in tool_calls_extracted:
            match = next((item for item in statuses_extracted if item.get('tool_call_id') == tool_call.get('id')), None)
            tool_call['status'] = match['status'] if match else 'unknown'

        # Step 6: Define and run agent evaluation chains (using InferenceUtils for parsing)
        agent_chain_1_template = ChatPromptTemplate.from_template(agent_evaluation_prompt1)
        agent_chain_2_template = ChatPromptTemplate.from_template(agent_evaluation_prompt2)

        agent_chain_1 = agent_chain_1_template | llm | StrOutputParser()
        agent_chain_2 = agent_chain_2_template | llm | StrOutputParser()

        result_1_raw = await agent_chain_1.ainvoke({
            "User_Query": User_Query,
            "Agent_Response": Agent_Response,
            "workflow_description": Workflow_Description,
            "past_conversation_summary": past_conversation_summary
        })
        result_2_raw = await agent_chain_2.ainvoke({
            "user_task": User_Query,
            "Agent_Goal": Agent_Goal,
            "agent_breakdown": agent_breakdown,
            "agent_response": Agent_Response,
            "workflow_description": Workflow_Description,
            "tool_calls": tool_calls_extracted
        })

        # For simplicity, assuming direct json.loads after stripping markdown.
        def parse_json_safe(raw_json_str: str):
            clean_str = raw_json_str.replace("```json", "").replace("```", "").strip()
            try:
                return json.loads(clean_str)
            except Exception as e:
                log.error(f"Failed to parse JSON from evaluation result: {e}\nRaw: {raw_json_str}")
                return {"error": f"JSON parsing failed: {e}"}

        res_1 = parse_json_safe(result_1_raw)
        res_2 = parse_json_safe(result_2_raw)

        # Step 7: Score Calculation with weights
        def calculate_weighted_score_and_justifications():
            scores = {
                'Fluency': res_1.get('fluency_evaluation', {}).get('fluency_rating', 0.0),
                'Relevancy': res_1.get('relevancy_evaluation', {}).get('relevancy_rating', 0.0),
                'Coherence': res_1.get('coherence_evaluation', {}).get('coherence_score', 0.0),
                'Groundness': res_1.get('groundedness_evaluation', {}).get('groundedness_score', 0.0),
                'Task Decomposition': res_2.get('task_decomposition_evaluation', {}).get('rating', 0.0),
                'Reasoning Relevancy': res_2.get('reasoning_relevancy_evaluation', {}).get('reasoning_relevancy_rating', 0.0),
                'Reasoning Coherence': res_2.get('reasoning_coherence_evaluation', {}).get('reasoning_coherence_score', 0.0),
            }

            justifications = {
                'Fluency': res_1.get('fluency_evaluation', {}).get('justification', ''),
                'Relevancy': res_1.get('relevancy_evaluation', {}).get('justification', ''),
                'Coherence': res_1.get('coherence_evaluation', {}).get('justification', ''),
                'Groundness': res_1.get('groundedness_evaluation', {}).get('justification', ''),
                'Task Decomposition': res_2.get('task_decomposition_evaluation', {}).get('justification', ''),
                'Reasoning Relevancy': res_2.get('reasoning_relevancy_evaluation', {}).get('justification', ''),
                'Reasoning Coherence': res_2.get('reasoning_coherence_evaluation', {}).get('justification', ''),
            }

            default_weights = {k: 1 for k in scores}
            applied_weights = weights if weights else default_weights

            total_weight = sum(applied_weights.get(k, 0) for k in scores)
            weighted_sum = sum(scores[k] * applied_weights.get(k, 0) for k in scores)

            efficiency_score = weighted_sum / total_weight if total_weight else 0

            category = "Bad"
            if efficiency_score >= 0.75:
                category = "Good"
            elif efficiency_score >= 0.5:
                category = "Average"
            elif efficiency_score >= 0.2:
                category = "Below Average"

            scores['Agent Utilization Efficiency'] = efficiency_score
            scores['Efficiency Category'] = category
            return scores, justifications

        scores, justifications = calculate_weighted_score_and_justifications()
        log.info("Agent evaluation completed successfully.")
        return scores, justifications

    async def _tool_utilization_efficiency(
        self,
        llm,
        agent_name: str,
        agent_goal: str,
        workflow_description: str,
        tool_prompt: str,
        steps,
        user_query: str,
        agent_response: str
    ):
        """
        Performs the tool utilization efficiency evaluation using LLM calls.
        """
        tool_calls_extracted = []
        for step_msg in steps:
            if step_msg.get('type') == 'ai' and step_msg.get('tool_calls'):
                tool_calls_extracted.extend(step_msg['tool_calls'])

        if not tool_calls_extracted:
            log.info("No tool calls detected for tool evaluation.")
            return None

        statuses_extracted = [step_msg for step_msg in steps if step_msg.get('type') == 'tool']

        for tool_call in tool_calls_extracted:
            match = next((item for item in statuses_extracted if item.get('tool_call_id') == tool_call.get('id')), None)
            tool_call['status'] = match['status'] if match else 'unknown'

        prompt_template = ChatPromptTemplate.from_template(tool_eval_prompt)
        tool_eval_chain = prompt_template | llm | StrOutputParser()

        tool_call_success_rate = 0
        tools_success = sum(1 for tc in tool_calls_extracted if tc.get("status", "").lower() == 'success')
        tools_failed = sum(1 for tc in tool_calls_extracted if tc.get("status", "").lower() == 'error')
        total_calls = tools_success + tools_failed
        if total_calls > 0:
            tool_call_success_rate = tools_success / total_calls

        try:
            evaluation_result_raw = await tool_eval_chain.ainvoke({
                "agent_name": agent_name,
                "agent_goal": agent_goal,
                "workflow_description": workflow_description,
                "tool_prompt": tool_prompt,
                "no_of_tools_called": len(tool_calls_extracted),
                "tool_calls": tool_calls_extracted,
                "user_query": user_query,
                "agent_response": agent_response,
            })

            # Parse the result (using InferenceUtils for robustness if needed)
            evaluation_result = evaluation_result_raw.replace('```json', '').replace('```', '')

            res = json.loads(evaluation_result)

            def safe_float(value):
                try:
                    return float(value)
                except (ValueError, TypeError):
                    return 0.0 # Default to 0 if conversion fails

            tsa_values = [
                safe_float(i.get('status'))
                for i in res.get('tool_selection_accuracy', {}).values()
                if isinstance(i, dict) and 'status' in i
            ]
            tsa = sum(tsa_values) / len(tsa_values) if tsa_values else 0.0

            tue = safe_float(res.get('tool_usage_efficiency', {}).get('status', 0.0))

            tcp_values = [
                safe_float(i.get('status'))
                for i in res.get('tool_call_precision', {}).values()
                if isinstance(i, dict) and 'status' in i
            ]
            tcp = sum(tcp_values) / len(tcp_values) if tcp_values else 0.0

            # Calculate tool utilization efficiency (using default weights of 1)
            w_tsa = w_tue = w_tcp = w_tcsr = 1
            tool_utilization_efficiency = (w_tsa * tsa + w_tue * tue + w_tcp * tcp + w_tcsr * tool_call_success_rate) / 4.0

            category = "Bad"
            if tool_utilization_efficiency >= 0.75:
                category = "Good"
            elif tool_utilization_efficiency >= 0.5:
                category = "Average"
            elif tool_utilization_efficiency >= 0.2:
                category = "Below Average"
            
            log.info(f"Tool Evaluation completed successfully for agent {agent_name}.")
            return {
                'tool_selection_accuracy': tsa,
                'tool_usage_efficiency': tue,
                'tool_call_precision': tcp,
                'tool_call_success_rate': tool_call_success_rate,
                'tool_utilization_efficiency': tool_utilization_efficiency,
                'tool_utilization_efficiency_category': category,
                'tool_selection_accuracy_justification': res.get('tool_selection_accuracy', {}).get('justification', ""),
                'tool_usage_efficiency_justification': res.get('tool_usage_efficiency', {}).get('justification', ""),
                'tool_call_precision_justification': res.get('tool_call_precision', {}).get('justification', "")
            }

        except Exception as e:
            log.error(f"Error during tool evaluation for agent {agent_name}: {e}", exc_info=True)
            return {"error": f"Failed to process tool evaluation: {e}"}


    async def is_meaningful_interaction(self, query, response, llm) -> bool:
        prompt = f"""
    You are a conversation filter agent. Your task is to check if a given user query and the corresponding agent response represent a meaningful and substantive interaction that should be evaluated.
    
    Return only `true` or `false` in lowercase — no explanation.
    
    ### Examples of non-meaningful interactions:
    - "hi", "hello", "thank you", "okay", "how can I help you?", "goodbye", "thanks", etc.
    - Any generic greetings or polite closures.
    - If the response is empty or meaningless.
    
    ### Evaluate this interaction:
    
    User Query: "{query}"
    Agent Response: "{response}"
    
    Is this interaction meaningful for evaluation?
    """.strip()
    
        try:
            result = await llm.ainvoke(prompt)  # assuming you're using async LLM
            result_text = result.content.strip().lower()
            return result_text == "true"
        except Exception as e:
            log.warning(f"⚠️ LLM failed to classify interaction: {e}")
            return True  # fallback to processing to avoid data loss


    async def process_unprocessed_evaluations(self, model1: str, model2: str):
        """
        Processes all unprocessed evaluation records.
        """
        log.info(f"Starting to process unprocessed evaluations with models {model1} and {model2}.")
        while True:
            data = await self.evaluation_service.fetch_next_unprocessed_evaluation()
            if not data:
                log.info("No more unprocessed evaluations found.")
                break

            evaluation_id = data["id"]
            await self.evaluation_service.update_evaluation_status(evaluation_id, "processing")
            log.info(f"Processing evaluation_id: {evaluation_id}")
            
            # Determine which LLM to use for evaluation based on the agent's model
            eval_llm_model_name = model2 if data['model_used'] == model1 else model1
            eval_llm = await self.model_service.get_llm_model(model_name=eval_llm_model_name)
            
            try:
                # ✅ Check if interaction is meaningful
                is_valid = await self.is_meaningful_interaction(data["query"], data["response"], eval_llm)
                if not is_valid:
                    log.info(f"⚠️ Skipping trivial interaction for evaluation_id {evaluation_id}")
                    await self.evaluation_service.update_evaluation_status(evaluation_id, "skipped")
                    continue

                # === Agent Evaluation ===
                scores, justifications = await self._evaluate_agent_performance(
                    llm=eval_llm,
                    User_Query=data["query"],
                    Agent_Response=data["response"],
                    Agent_Goal=data["agent_goal"],
                    Steps=data["steps"],
                    Workflow_Description=data["workflow_description"],
                )

                if scores and justifications:
                    await self.evaluation_service.insert_agent_metrics(
                        {
                            "evaluation_id": evaluation_id,
                            "user_query": data["query"],
                            "response": data["response"],
                            "model_used": data["model_used"],
                            "task_decomposition_efficiency": scores.get('Task Decomposition', 0.0),
                            "task_decomposition_justification": justifications.get('Task Decomposition', ''),
                            "reasoning_relevancy": scores.get('Reasoning Relevancy', 0.0),
                            "reasoning_relevancy_justification": justifications.get('Reasoning Relevancy', ''),
                            "reasoning_coherence": scores.get('Reasoning Coherence', 0.0),
                            "reasoning_coherence_justification": justifications.get('Reasoning Coherence', ''),
                            "answer_relevance": scores.get('Relevancy', 0.0),
                            "answer_relevance_justification": justifications.get('Relevancy', ''),
                            "groundedness": scores.get('Groundness', 0.0),
                            "groundedness_justification": justifications.get('Groundness', ''),
                            "response_fluency": scores.get('Fluency', 0.0),
                            "response_fluency_justification": justifications.get('Fluency', ''),
                            "response_coherence": scores.get('Coherence', 0.0),
                            "response_coherence_justification": justifications.get('Coherence', ''),
                            "efficiency_category": scores.get('Efficiency Category', 'Unknown'),
                            "model_used_for_evaluation": eval_llm_model_name
                        }
                    )
                else:
                    log.warning(f"Agent evaluation failed or returned empty for evaluation_id {evaluation_id}. Skipping agent metrics insert.")

                # === Tool Evaluation ===
                tool_result = await self._tool_utilization_efficiency(
                    llm=eval_llm,
                    agent_name=data["agent_name"],
                    agent_goal=data["agent_goal"],
                    workflow_description=data["workflow_description"],
                    tool_prompt=data["tool_prompt"],
                    steps=data["steps"],
                    user_query=data["query"],
                    agent_response=data["response"]
                )

                if tool_result is not None and "error" not in tool_result:
                    await self.evaluation_service.insert_tool_metrics(
                        {
                            "evaluation_id": evaluation_id,
                            "user_query": data["query"],
                            "agent_response": data["response"],
                            "model_used": data["model_used"],
                            "tool_selection_accuracy": tool_result["tool_selection_accuracy"],
                            "tool_usage_efficiency": tool_result["tool_usage_efficiency"],
                            "tool_call_precision": tool_result["tool_call_precision"],
                            "tool_call_success_rate": tool_result["tool_call_success_rate"],
                            "tool_utilization_efficiency": tool_result["tool_utilization_efficiency"],
                            "tool_utilization_efficiency_category": tool_result["tool_utilization_efficiency_category"],
                            "tool_selection_accuracy_justification": tool_result.get("tool_selection_accuracy_justification", ""),
                            "tool_usage_efficiency_justification": tool_result.get("tool_usage_efficiency_justification", ""),
                            "tool_call_precision_justification": tool_result.get("tool_call_precision_justification", ""),
                            "model_used_for_evaluation": eval_llm_model_name
                        }
                    )
                else:
                    log.warning(f"Tool evaluation failed or returned empty for evaluation_id {evaluation_id}. Skipping tool metrics insert.")

                # Update processing status
                await self.evaluation_service.update_evaluation_status(evaluation_id, "processed")
                log.info(f"Successfully processed evaluation_id: {evaluation_id}.")
                
            except Exception as e:
                log.error(f"Error during evaluation of ID {evaluation_id}: {e}", exc_info=True)
                await self.evaluation_service.update_evaluation_status(evaluation_id, "error")
                
        log.info("All evaluations processed. Please check the database and dashboard for results.")
        return "All evaluations processed. Please check the database and dashboard for results."


    