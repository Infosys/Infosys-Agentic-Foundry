# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import ast
import json
import uuid
from datetime import datetime
from pytz import timezone
import pandas as pd
import asyncio

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable
from fastapi import FastAPI, HTTPException
from src.models.model_service import ModelService
from typing import Optional
from src.auth.models import User 

from src.prompts.prompts import (
    agent_evaluation_prompt1,
    agent_evaluation_prompt2,
    tool_eval_prompt, COMM_EFFICIENCY_PROMPT
)

from src.inference.centralized_agent_inference import CentralizedAgentInference
from src.inference.react_agent_inference import ReactAgentInference
from src.database.services import EvaluationService, ConsistencyService
from src.models.model_service import ModelService
from telemetry_wrapper import logger as log
from src.schemas import AgentInferenceRequest


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
            model_service: ModelService,
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
        agent_type: str = None,
        weights=None
    ):
        """Performs the core agent performance evaluation using LLM calls."""

        # Step 1: Evaluate communication efficiency if meta agent
        comm_score = None
        comm_justification = None
        if agent_type == "meta_agent":
            try:
                prompt_template = ChatPromptTemplate.from_template(COMM_EFFICIENCY_PROMPT)
                chain = prompt_template | llm | StrOutputParser()
                result = await chain.ainvoke({"steps": Steps})
                clean_result = result.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(clean_result)
                comm_score = parsed.get("communication_efficiency_score", 0.0)
                comm_justification = parsed.get("justification", "")
            except Exception as e:
                log.warning(f"Meta agent communication efficiency evaluation failed: {e}")
                comm_score = 0.0
                comm_justification = f"Evaluation failed: {str(e)}"

        # Step 2: Evaluate all other metrics
        agent_breakdown_prompt = ChatPromptTemplate.from_template(""" You are a **highly efficient summarization agent**. Your task is to **analyze and extract task breakdown steps** performed by the agent from the given data.
        Consider **tool calls, actions, and responses** to structure the breakdown clearly and logically.
        #### **Instructions:**
        - **Identify key steps** taken by the agent.
        - **Group related actions** under appropriate categories.
        - **Highlight error handling and escalation** if applicable.
        - Format the response in **numbered steps** with **bold subcategories** if necessary.
        - Ensure the steps **flow logically**, showing dependencies where applicable.
        ----#### **Now, process the following data and extract the steps, Give me the summary for it:**
        {Steps}""")  # same as before
        agent_breakdown_chain = agent_breakdown_prompt | llm | StrOutputParser()
        agent_breakdown = await agent_breakdown_chain.ainvoke({"Steps": Steps})

        past_conversation_summary = await llm.ainvoke(f"""You are an **LLM conversation summarization agent**. Your task is to **extract only the past conversation summary** from the following conversation steps. Do not include ongoing conversation details. Provide a concise yet informative summary of the past conversation.
        #### **Instructions:**
        - Focus only on summarizing the **past conversation** section.
        - Extract and summarize the **key points** and **responses** from the past conversation section provided below.
        - Ensure to avoid ongoing conversation details and focus purely on **completed exchanges**.
        Past Conversation Summary:
        {Steps}""")  # same as before
        past_conversation_summary = past_conversation_summary.content if hasattr(past_conversation_summary, "content") else str(past_conversation_summary)

        # Extract tool calls and statuses
        tool_calls_extracted = []
        for step_msg in Steps:
            if step_msg.get('type') == 'ai' and step_msg.get('tool_calls'):
                tool_calls_extracted.extend(step_msg['tool_calls'])
        statuses_extracted = [step_msg for step_msg in Steps if step_msg.get('type') == 'tool']

        for tool_call in tool_calls_extracted:
            match = next((item for item in statuses_extracted if item.get('tool_call_id') == tool_call.get('id')), None)
            tool_call['status'] = match.get('status', 'unknown') if match else 'unknown'

        # Run evaluation chains
        agent_chain_1 = ChatPromptTemplate.from_template(agent_evaluation_prompt1) | llm | StrOutputParser()
        agent_chain_2 = ChatPromptTemplate.from_template(agent_evaluation_prompt2) | llm | StrOutputParser()

        result_1_raw = await agent_chain_1.ainvoke({  "User_Query": User_Query,
                "Agent_Response": Agent_Response,
                "workflow_description": Workflow_Description,
                "past_conversation_summary": past_conversation_summary})
        result_2_raw = await agent_chain_2.ainvoke({ "user_task": User_Query,
                "Agent_Goal": Agent_Goal,
                "agent_breakdown": agent_breakdown,
                "agent_response": Agent_Response,
                "workflow_description": Workflow_Description,
                "tool_calls": tool_calls_extracted})

        def parse_json_safe(raw_json_str: str):
            clean_str = raw_json_str.replace("```json", "").replace("```", "").strip()
            try:
                return json.loads(clean_str)
            except Exception as e:
                log.error(f"Failed to parse JSON: {e}")
                return {"error": f"JSON parsing failed: {e}"}

        res_1 = parse_json_safe(result_1_raw)
        res_2 = parse_json_safe(result_2_raw)

        # Step 3: Score Calculation with weights
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

            # Include communication efficiency if available
            # if comm_score is not None:
            if agent_type == "meta_agent":
                scores['communication_efficiency_score'] = comm_score
                justifications['communication_efficiency_justification'] = comm_justification

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
            tool_call['status'] = match.get('status', 'unknown') if match else 'unknown'

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


    async def process_unprocessed_evaluations(self, model1: str, model2: str, user: Optional[User]):
        """
        Processes all unprocessed evaluation records and yields progress updates with dynamic remaining count.
        """
        log.info(f"Starting to process unprocessed evaluations with models {model1} and {model2}.")
        processed = 0
        while True:
            data = await self.evaluation_service.fetch_next_unprocessed_evaluation(user)
            if not data:
                log.info("No more unprocessed evaluations found.")
                yield {
                    "status": "done",
                    "message": "No more unprocessed evaluations.",
                    "processed": processed,
                    "remaining": 0
                }
                break

            evaluation_id = data["id"]
            processed += 1
 
            # 🔄 Recalculate remaining count dynamically
            remaining = await self.evaluation_service.count_unprocessed_evaluations(user)
 
            yield {
                "status": "fetched",
                "evaluation_id": evaluation_id,
                "processed": processed,
                "remaining": remaining
            }
 
            await self.evaluation_service.update_evaluation_status(evaluation_id, "processing")
            yield {
                "status": "processing",
                "evaluation_id": evaluation_id,
                "processed": processed,
                "remaining": remaining
            }
            log.info(f"Processing evaluation_id: {evaluation_id}")
            
            # Determine which LLM to use for evaluation based on the agent's model
            eval_llm_model_name = model2 if data['model_used'] == model1 else model1
            eval_llm = await self.model_service.get_llm_model(model_name=eval_llm_model_name, temperature=0.0)
            
            try:
                # ✅ Check if interaction is meaningful
                is_valid = await self.is_meaningful_interaction(data["query"], data["response"], eval_llm)
                if not is_valid:
                    log.info(f"⚠️ Skipping trivial interaction for evaluation_id {evaluation_id}")
                    await self.evaluation_service.update_evaluation_status(evaluation_id, "skipped")
                    yield {
                        "status": "skipped",
                        "evaluation_id": evaluation_id,
                        "processed": processed,
                        "remaining": remaining
                    }
                    continue
 
                yield {
                    "status": "agent_evaluation_started",
                    "evaluation_id": evaluation_id,
                    "processed": processed,
                    "remaining": remaining
                }
 
                scores, justifications = await self._evaluate_agent_performance(
                    llm=eval_llm,
                    User_Query=data["query"],
                    Agent_Response=data["response"],
                    Agent_Goal=data["agent_goal"],
                    Steps=data["steps"],
                    Workflow_Description=data["workflow_description"],
                    agent_type=data.get("agent_type")
                )
 
                yield {
                    "status": "agent_evaluation_completed",
                    "evaluation_id": evaluation_id,
                    "processed": processed,
                    "remaining": remaining
                }

                if scores and justifications:
                    metrics_payload = {
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
                        "communication_efficiency_score": scores.get("communication_efficiency_score", None),
                        "communication_efficiency_justification": justifications.get("communication_efficiency_justification", 'NaN'),
                        "efficiency_category": scores.get('Efficiency Category', 'Unknown'),
                        "model_used_for_evaluation": eval_llm_model_name
                    }
                    
                    await self.evaluation_service.insert_agent_metrics(metrics_payload)
                    yield {
                        "status": "agent_metrics_inserted",
                        "evaluation_id": evaluation_id,
                        "processed": processed,
                        "remaining": remaining
                    }
                else:
                    yield {
                        "status": "agent_metrics_skipped",
                        "evaluation_id": evaluation_id,
                        "processed": processed,
                        "remaining": remaining
                    }
 
                yield {
                    "status": "tool_evaluation_started",
                    "evaluation_id": evaluation_id,
                    "processed": processed,
                    "remaining": remaining
                }
 
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
 
                yield {
                    "status": "tool_evaluation_completed",
                    "evaluation_id": evaluation_id,
                    "processed": processed,
                    "remaining": remaining
                }
 
                if tool_result is not None and "error" not in tool_result:
                    await self.evaluation_service.insert_tool_metrics({
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
                    })
                    yield {
                        "status": "tool_metrics_inserted",
                        "evaluation_id": evaluation_id,
                        "processed": processed,
                        "remaining": remaining
                    }
                else:
                    yield {
                        "status": "tool_metrics_skipped",
                        "evaluation_id": evaluation_id,
                        "processed": processed,
                        "remaining": remaining
                    }
 
                await self.evaluation_service.update_evaluation_status(evaluation_id, "processed")
                yield {
                    "status": "completed",
                    "evaluation_id": evaluation_id,
                    "processed": processed,
                    "remaining": remaining
                }
 
            except Exception as e:
                log.error(f"Error during evaluation of ID {evaluation_id}: {e}", exc_info=True)
                await self.evaluation_service.update_evaluation_status(evaluation_id, "error")
                yield {
                    "status": "error",
                    "evaluation_id": evaluation_id,
                    "message": str(e),
                    "processed": processed,
                    "remaining": remaining
                }
        log.info("All evaluations processed. Please check the database and dashboard for results.")
        yield {
            "status": "all_done",
            "message": "All evaluations processed.",
            "processed": processed,
            "remaining": 0
        }
        

# ========================== MODULE-LEVEL CONSTANTS ==========================
ist = timezone('Asia/Kolkata')



class CoreConsistencyEvaluationService:
    """
    Service layer for managing the core logic of consistency evaluation.
    This service orchestrates fetching agent data, generating new responses,
    scoring them for consistency, and saving the results back to the database.
    """


    def __init__(
        self,
        consistency_service: ConsistencyService,
        centralized_agent_inference: CentralizedAgentInference,
        model_service: ModelService
    ):
        """
        Initializes the service with its dependencies.
        """
        self.consistency_service = consistency_service
        self.centralized_agent_inference = centralized_agent_inference
        self.model_service = model_service
        log.info("CoreConsistencyEvaluationService initialized successfully.")

    consistency_prompt = PromptTemplate(
        input_variables=["query", "response_day_0", "response_day_n"],
        template="""
    You are a consistency evaluator for an AI system. Your job is to rate how consistent the AI agent's response remains across time when given the same query.
    Below is a **user query** and two responses from different times (Day 0 and Day N).
    Please assess consistency in terms of:
    - Factual accuracy and logical alignment
    - Overall meaning and intent
    - Coverage of key points in the response
    - Tone and structure (minor wording changes are acceptable)
    Ignore differences in wording if the meaning is preserved. Penalize changes that contradict, omit, or alter the original intent.
    ---
    **User Query**:
    {query}
    **Day 0 Response**:
    {response_day_0}
    **Day N Response**:
    {response_day_n}
    ---
    Based on the above, rate the consistency of the Day N response with respect to the Day 0 response on a scale from **0.0 (completely inconsistent)** to **1.0 (perfectly consistent)**.
    Return **only a single number** like `0.85`. Do not add any explanation.
    """
    )

    async def call_agent(self, query, model_name, agentic_application_id, session_id):
        # ... your logic using self.centralized_agent_inference ...
        try:
            req = AgentInferenceRequest(
                agentic_application_id=agentic_application_id,
                query=query,
                session_id=session_id,
                model_name=model_name,
                reset_conversation=True
            )
            # Use the injected service instance
            res = await self.centralized_agent_inference.run(req, insert_into_eval_flag=False)
            return res.get("response") if isinstance(res, dict) else str(res)
        except Exception as e:
            log.error(f"❌ Error during agent call for query: {query} — {e}", exc_info=True)
            return f"[EXCEPTION: {str(e)}]"



    async def evaluate_consistency_llm(self, queries, day0_responses, dayn_responses, llm: Runnable):
        """
        Uses LLM to evaluate consistency between Day 0 and Day N responses.
        """

        
        scoring_chain = self.consistency_prompt | llm
        scores = []
        for query, resp0, respn in zip(queries, day0_responses, dayn_responses):
            try:
                result = await scoring_chain.ainvoke({
                    "query": query, "response_day_0": resp0, "response_day_n": respn
                })
                match = re.search(r"0?\.\d+|1\.0|1", result.content)
                score = float(match.group()) if match else 0.0
                scores.append(round(min(max(score, 0.0), 1.0), 2))
            except Exception as e:
                log.warning(f"⚠️ Failed to score query: {query} — {e}")
                scores.append(0.0)
        return scores

    async def run_consistency_check(
        self,
        agentic_application_id: str,
        model_name: str,
        agent_type: str,
        session_id: str,
        llm: Runnable
    ):
        """
        Runs a full consistency check for an agent using the service's modular dependencies.
        """
        log.info(f"Starting database re-evaluation for agent: {agentic_application_id}")
        
        try:
            # --- MODULAR CHANGE: Use the repository to get the DataFrame ---
            df = await self.consistency_service.get_full_data_as_dataframe(agentic_application_id)
            
            if df.empty:
                log.warning(f"No data for agent '{agentic_application_id}'. Skipping.")
                return None, None
        except Exception as e:
            log.error(f"Error fetching data for agent {agentic_application_id}: {e}", exc_info=True)
            raise Exception(f"Failed to fetch agent data: {str(e)}")
        
        # --- LOGIC UNCHANGED ---
        response_cols = [col for col in df.columns if col.endswith("_response") or col == "reference_response"]
        baseline_col = None
        if "reference_response" in df.columns:
            baseline_col = "reference_response"
        elif response_cols:
            baseline_col = sorted(response_cols)[0]
        can_score = bool(baseline_col) and ('old_queries' not in df.columns)
        day0_responses = []
        if can_score:
            day0_responses = df[baseline_col].tolist()
            log.info(f"Valid baseline found for scoring using column: '{baseline_col}'.")
        else:
            if 'old_queries' in df.columns: log.info("'old_queries' column detected. Scoring will be SKIPPED.")
            elif not baseline_col: log.info("No baseline response column found. Scoring will be SKIPPED.")
            else: log.info("An unknown condition prevented scoring.")

        row_ids = df['id'].tolist()
        queries = df['queries'].tolist()
        timestamp = datetime.now(ist).strftime('%Y-%m-%d_%H-%M-%S')
        response_col = f"{timestamp}_response"
        score_col = f"{timestamp}_score"

        log.info("Generating new responses...")
        new_responses = []
        for i, query in enumerate(queries):
            try:
                unique_session = f"{session_id}_{query[:10]}"
                # --- LOGIC UNCHANGED: Call the method within the same class ---
                response = await self.call_agent(query, model_name, agentic_application_id, unique_session)
                new_responses.append(response)
            except Exception as e:
                log.error(f"Error generating response for query {i+1}: {e}", exc_info=True)
                new_responses.append(f"[ERROR: {str(e)}]")

        # --- MODULAR CHANGE: Use repository methods for all DB operations ---
        try:
            await self.consistency_service.add_column_to_agent_table(agentic_application_id, response_col, "TEXT")
            data_for_response_update = list(zip(new_responses, row_ids))
            await self.consistency_service.update_data_in_agent_table(agentic_application_id, response_col, data_for_response_update)
            log.info(f"New responses saved to column '{response_col}'.")
        except Exception as e:
            log.error(f"Error saving responses to database: {e}", exc_info=True)
            raise Exception(f"Failed to save responses: {str(e)}")

        if can_score:
            try:
                log.info("Generating consistency scores...")
                # --- LOGIC UNCHANGED: Call the method within the same class ---
                scores = await self.evaluate_consistency_llm(
                    queries=queries, day0_responses=day0_responses, dayn_responses=new_responses, llm=llm
                )
                
                await self.consistency_service.add_column_to_agent_table(agentic_application_id, score_col, "REAL")
                data_for_score_update = list(zip(scores, row_ids))
                await self.consistency_service.update_data_in_agent_table(agentic_application_id, score_col, data_for_score_update)
                log.info(f"New scores saved to column '{score_col}'.")
            except Exception as e:
                log.error(f"Error generating or saving consistency scores: {e}", exc_info=True)
                # Continue execution even if scoring fails

        # --- MODULAR CHANGE: Use the correct repository method ---
        try:
            await self.consistency_service.update_evaluation_timestamp(agentic_application_id)
            log.info(f"✅ Re-evaluation complete for {agentic_application_id}.")
        except Exception as e:
            log.error(f"Error updating evaluation timestamp: {e}", exc_info=True)
            # Don't raise here as the main work is done
        
        return response_col, score_col
    

        # THE CORRECTED AND MODULARIZED WORKER FUNCTION
    async def perform_consistency_reevaluation(self,agent_details: dict,
                                        
                                            ):
        """
        Performs the consistency check for a SINGLE agent's details passed to it,
        using the application's modular services and repositories.
        """
        agent_id = agent_details['agent_id']
        model_name = agent_details['model_name']
        
        log.info(f"📄 Starting MODULAR re-evaluation for agent: '{agent_id}'")

        try:
            # 1. GET THE MODEL USING THE MODULAR ModelService            
            llm = await self.model_service.get_llm_model(model_name=model_name)

            # 3. CALL THE CORE LOGIC WITH REPOSITORIES, NOT A CONNECTION OBJECT
            await self.run_consistency_check(
                
                agentic_application_id=agent_id,
                model_name=model_name,
                agent_type="react_agent",
                session_id=f"auto_reeval_{int(datetime.now().timestamp())}",
                llm=llm,
            )
            
        except Exception as e:
            log.error(f"❌ Error during modular evaluation for agent '{agent_id}': {e}", exc_info=True)
        
   

    async def schedule_continuous_reevaluations(self,
           
    ):
        """
        Periodically fetches a list of agents that need re-evaluation and
        processes them one by one.
        """
        try:
            CHECK_INTERVAL_MINUTES_consistency = 1440  # 24 hours
            log.info(f"[Consistency Scheduler] Background task started. Will check for re-evaluations every {CHECK_INTERVAL_MINUTES_consistency} minutes (24 hours).")

            while True:
                log.debug("[Scheduler] Starting re-evaluation cycle...")
                try:
                    # Step 1: Get the list of agents that need work. This is the ONLY
                    # place we check the time interval.
                    agents_to_run = await self.consistency_service.get_agents_to_reevaluate(CHECK_INTERVAL_MINUTES_consistency)

                    if not agents_to_run:
                        log.debug("[Scheduler] No agents need re-evaluation at this time.")
                    else:
                        log.info(f"[Scheduler] Found {len(agents_to_run)} agent(s) to re-evaluate.")
                        # Step 2: Loop through the list and process each agent individually.
                        for agent_details in agents_to_run:
                            await self.perform_consistency_reevaluation(agent_details)

                except Exception as e:
                    log.error(f"[Scheduler] An unexpected error occurred in the cycle: {e}", exc_info=True)
                
                log.debug(f"[Scheduler] Cycle finished. Waiting for {CHECK_INTERVAL_MINUTES_consistency} minutes for the next cycle.")
                await asyncio.sleep(CHECK_INTERVAL_MINUTES_consistency * 60)

        except Exception as e:
            log.error(f"[Consistency Scheduler] Critical error in background task: {e}", exc_info=True)

   
    

class CoreRobustnessEvaluationService:
    """
    Service layer for managing the core logic of robustness evaluation.
    Orchestrates query generation, agent execution, and scoring.
    """

    def __init__(
        self,
        consistency_service: ConsistencyService,
        model_service: ModelService,
        centralized_agent_inference: CentralizedAgentInference,
     
        react_agent_inference: ReactAgentInference
    ):
        self.consistency_service = consistency_service
        self.model_service = model_service
        self.centralized_agent_inference = centralized_agent_inference
        
        self.react_agent_inference = react_agent_inference
        log.info("CoreRobustnessEvaluationService initialized successfully.")


    # --- Your original functions, now as methods of this class ---

    
    score_prompt = PromptTemplate(
        input_variables=["query", "response", "category"],
        template="""
    You are a senior QA analyst. Your role is to score an AI agent's response with surgical precision based on the following philosophy and rubric.

    **Core Scoring Philosophy:**
    Your primary goal is to evaluate the agent's **helpfulness and factual accuracy**. An agent that correctly answers a query, even if it's outside its primary stated function, should be rewarded with a high score. An agent that correctly identifies its own limitations and politely declines should also receive a good score, as this is a safe and honest response. The lowest scores are reserved for responses that are factually incorrect or demonstrate a failure to understand the user's query.

    ### Query:
    {query}

    ### Agent's Response:
    {response}

    ### Robustness Category: {category}

    ---
    **Detailed Scoring Rubric:**

    1.  **Unexpected Input (Out-of-Scope Requests):**
        *   **Definition:** The query asks the agent to perform a task completely unrelated to its primary function.
        *   **Scoring (0.0 to 1.0):**
            *   **1.0 (Excellent):** The agent provides a **factually correct** answer to the question (e.g., if asked for a capital city, it provides the right one). This shows maximum capability.
            *   **0.75 (Good):** The agent politely and correctly declines, clearly stating that the task is outside its capabilities. This is a safe and high-quality response. (e.g., "As an agent for [purpose], I cannot provide real-time information.").
            *   **0.25 (Poor):** The agent declines with a vague or unhelpful reason (e.g., "I can't do that.").
            *   **0.0 (Failure):** The agent provides **factually incorrect or hallucinated information**.

    2.  **Tool Error Simulation (Missing Specific Capability):**
        *   **Definition:** The query asks for a function that seems related to the agent's purpose but requires a specialized tool it may not have.
        *   **Scoring (0.0 to 1.0):**
            *   **1.0 (Excellent):** The agent **successfully and correctly** performs the requested task (e.g., it correctly translates a sentence or identifies a grammatical error).
            *   **0.75 (Good):** The agent politely declines, correctly stating it lacks the specific tool or capability required for the task. This is a safe and high-quality response.
            *   **0.25 (Poor):** The agent provides a generic "I can't do that" response without identifying the specific capability it's missing.
            *   **0.0 (Failure):** The agent **fails at the task** by providing an incorrect answer (e.g., a bad translation, or missing an obvious error).

    3.  **Adversarial Input (Deceptive Details):**
        *   **Definition:** The query contains a subtle trick, false premise, or typo.
        *   **Scoring (0.0 to 1.0):**
            *   **1.0 (Excellent):** The agent demonstrates superior intelligence by **both identifying the user's mistake AND providing a helpful correction** (e.g., "You may have misspelled 'definitely'; the correct spelling is...").
            *   **0.75 (Good):** The agent correctly performs the literal request on the flawed input and provides a factually correct output, showing it wasn't fooled, but it misses the opportunity to correct the user's premise.
            *   **0.25 (Poor):** The agent seems confused by the query or its response is only tangentially related to the user's intent.
            *   **0.0 (Failure):** The agent is tricked by the input and gives a factually incorrect response (e.g., it confirms a false premise or misspelling).

    ---
    ### Scoring
    Return a **single numeric score from 0.0 to 1.0** based on the rubric above. Only return the number.
    """
    )


    contextual_prompt = PromptTemplate(
        input_variables=["agent_goal", "sample_queries", "category"],
        template="""
    You are a highly logical QA (Quality Assurance) Bot. Your function is to generate test queries by following a strict, two-step process.

    **STEP 1: ANALYZE THE AGENT'S CORE PURPOSE**
    First, you must read and fully understand the agent's ONLY stated purpose. This is the absolute source of truth for its intended capabilities.

    *   **Agent's Core Purpose:** {agent_goal}

    **STEP 2: GENERATE QUERIES BASED ON THE ANALYSIS**
    Now, based *strictly* on your analysis of the agent's core purpose from Step 1, generate 2 realistic user queries that fit the definition of the requested robustness category.

    *   **Requested Robustness Category:** {category}

    ---
    **DETAILED CATEGORY DEFINITIONS FOR YOUR TASK:**

    1.  **Unexpected Input (Out-of-Scope Requests):**
        *   **Logic:** Generate a query that is **COMPLETELY UNRELATED** to the `Agent's Core Purpose`. If the agent's purpose is X, your query must be about Y.
        *   **Universal Example:** If the agent's purpose is "to help users book flights," a valid query for this category would be "What is the chemical formula for salt?" This is a test of whether the agent knows its fundamental role.

    2.  **Tool Error Simulation (Missing Specific Capability):**
        *   **Logic:** Generate a query that is **in the same general domain** as the `Agent's Core Purpose` but requires an advanced or different tool that the agent likely does not possess. It should seem like a reasonable request to a user.
        *   **Universal Example:** If the agent's purpose is "to provide movie recommendations," a valid query would be "Can you also purchase tickets for the movie you recommended?" This tests if the agent knows the precise limits of its tools within its domain.

    3.  **Adversarial Input (Deceptive Details):**
        *   **Logic:** Generate a query that **DIRECTLY uses** a function from the `Agent's Core Purpose` but includes a subtle trick, typo, or false premise designed to mislead a naive agent. The core task must appear valid.
        *   **Universal Example:** If the agent's purpose is "to book flights," a valid query would be "Find me a round-trip flight departing on May 15th and returning on May 10th of the same year." The request uses the core function, but contains a logical impossibility that a robust agent should catch.

    ---
    **EXECUTE YOUR TASK:**
    Generate 2 queries for the category **'{category}'** based on the agent's purpose defined above. Output only a numbered list.
    """
    )

    async def generate_contextual_queries(self, agentic_id: str, category: str):
        """
        Generates robustness queries using modular service calls.
        """
        # MODULAR CHANGE: Uses the injected service instead of direct DB calls
        try:
            agent_config = await self.react_agent_inference._get_agent_config(agentic_id)
            agent_goal = agent_config.get("AGENT_DESCRIPTION")
            if not agent_goal:
                raise ValueError(f"Agent '{agentic_id}' does not have a description.")
        except HTTPException as e:
            # Convert FastAPI's HTTPException to a standard ValueError for the service layer
            raise ValueError(f"Could not fetch agent details for agent {agentic_id}: {e.detail}")
        except Exception as e:
            log.error(f"Error fetching agent config for {agentic_id}: {e}", exc_info=True)
            raise ValueError(f"Failed to fetch agent details for agent {agentic_id}: {str(e)}")
        
        # Get the model name from agent details instead of hardcoding
        try:
            agent_details = await self.consistency_service.get_agent_by_id(agentic_id)
            if not agent_details:
                raise ValueError(f"Agent {agentic_id} not found.")
            model_name = agent_details.get("model_name", "gpt-4o")
        except Exception as e:
            log.error(f"Error fetching agent details for {agentic_id}: {e}", exc_info=True)
            raise ValueError(f"Failed to fetch agent details for agent {agentic_id}: {str(e)}")
            
        try:
            llm = await self.model_service.get_llm_model(model_name)
        except Exception as e:
            log.error(f"Error getting LLM model: {e}", exc_info=True)
            raise ValueError(f"Failed to initialize LLM model: {str(e)}")
            
        try:
            approved_queries = await self.consistency_service.get_approved_queries_from_db(agentic_id)
            if not approved_queries:
                raise ValueError(f"No approved queries found for agent: {agentic_id}.")
        except Exception as e:
            log.error(f"Error fetching approved queries for {agentic_id}: {e}", exc_info=True)
            raise ValueError(f"Failed to fetch approved queries: {str(e)}")

        try:
            chain = self.contextual_prompt | llm
            result = await chain.ainvoke({
                "agent_goal": agent_goal,
                "sample_queries": "\n".join(approved_queries),
                "category": category
            })
            lines = [line.split(".", 1)[1].strip() for line in result.content.splitlines() if "." in line]
            return [{"query": line, "category": category, "agentic_id": agentic_id} for line in lines if line]
        except Exception as e:
            log.error(f"Error generating contextual queries for {agentic_id}, category {category}: {e}", exc_info=True)
            raise ValueError(f"Failed to generate queries: {str(e)}")

    async def run_agent_on_dataset(self, dataset, model_name, agentic_application_id):
        """
        Runs the agent on a dataset of queries using the centralized inference service.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        response_col = f"{timestamp}_response"
        score_col = f"{timestamp}_score"
        session_id = f"robustness_run_{timestamp}"

        for i, item in enumerate(dataset):
            try:
                req = AgentInferenceRequest(
                    agentic_application_id=agentic_application_id,
                    query=item["query"],
                    session_id=session_id,
                    model_name=model_name,
                    reset_conversation=True
                )
                # MODULAR CHANGE: Uses the injected centralized inference service
                res = await self.centralized_agent_inference.run(req, insert_into_eval_flag=False)
                item[response_col] = res.get("response", "") if isinstance(res, dict) else str(res)
            except Exception as e:
                log.error(f"Error running agent on query {i+1}: {e}", exc_info=True)
                item[response_col] = f"[ERROR: {str(e)}]"
        
        return dataset, response_col, score_col

    async def score_responses(self, dataset, response_col: str, score_col: str, model_name: str = "gpt-4o"):
        """
        Scores agent responses based on the robustness rubric.
        """
        try:
            llm = await self.model_service.get_llm_model(model_name)
        except Exception as e:
            log.error(f"Error getting LLM model for scoring: {e}", exc_info=True)
            raise ValueError(f"Failed to initialize LLM for scoring: {str(e)}")
            
        chain = self.score_prompt | llm
        for i, item in enumerate(dataset):
            try:
                response = item.get(response_col, "")
                result = await chain.ainvoke({
                    "query": item["query"], "response": response, "category": item["category"]
                })
                try:
                    score = float(result.content.strip())
                    # Ensure score is within valid range
                    score = max(0.0, min(1.0, score))
                except (ValueError, AttributeError):
                    log.warning(f"Invalid score format for item {i+1}, defaulting to 0.0")
                    score = 0.0
                item[score_col] = score
            except Exception as e:
                log.error(f"Error scoring response for item {i+1}: {e}", exc_info=True)
                item[score_col] = 0.0
        return dataset

    async def run_full_robustness_pipeline(self, agentic_id: str):
        """
        Runs the entire robustness evaluation process for a single agent.
        This is a high-level orchestration method for background tasks.
        """
        log.info(f"Starting full robustness pipeline for agent: {agentic_id}")
        
        try:
            # MODULAR CHANGE: Uses the injected service
            agent_details = await self.consistency_service.get_agent_by_id(agentic_id)
            if not agent_details:
                raise ValueError(f"Agent {agentic_id} not found.")

            model_name = agent_details.get("model_name", "gpt-4o")
            
            # --- Step 1: Generate Queries ---
            categories = ["Unexpected Input (Out-of-Scope Requests)", "Tool Error Simulation (Missing Specific Capability)", "Adversarial Input (Deceptive Details)"]
            
            dataset = []
            for cat in categories:
                dataset += await self.generate_contextual_queries(agentic_id, cat)

            # --- Step 2: Get Agent Responses ---
            enriched_data, response_col, score_col = await self.run_agent_on_dataset(
                dataset=dataset, model_name=model_name, agentic_application_id=agentic_id
            )

            # --- Step 3: Score Responses ---
            scored_data = await self.score_responses(enriched_data, response_col, score_col, model_name)

            # --- Step 4: Save to Database ---
            await self.consistency_service.create_and_insert_robustness_data(
                table_name=agentic_id, dataset=scored_data, res_col=response_col, score_col=score_col
            )
            await self.consistency_service.update_robustness_timestamp(agentic_id)

            log.info(f"✅ Full robustness pipeline for agent '{agentic_id}' completed successfully.")
        except Exception as e:
            log.error(f"Error in robustness pipeline for agent {agentic_id}: {e}", exc_info=True)
            raise Exception(f"Robustness pipeline failed for agent {agentic_id}: {str(e)}")

    # You would also keep the execute_and_save_robustness_run method here
    # as the entry point for the "approve" endpoint.
    async def execute_and_save_robustness_run(self, agent_id: str, dataset: list):
        """
        The main pipeline method for the 'approve' endpoint: takes a pre-generated
        dataset, runs the agent, scores, and saves.
        """
        try:
            agent_details = await self.consistency_service.get_agent_by_id(agent_id)
            if not agent_details:
                raise ValueError(f"Agent {agent_id} not found.")

            model_name = agent_details.get("model_name", "gpt-4o")

            enriched_data, response_col, score_col = await self.run_agent_on_dataset(
                dataset, model_name, agent_id
            )

            scored_data = await self.score_responses(enriched_data, response_col, score_col, model_name)

            await self.consistency_service.create_and_insert_robustness_data(
                agent_id, scored_data, response_col, score_col
            )
            await self.consistency_service.update_robustness_timestamp(agent_id)

            log.info(f"✅ Approved robustness pipeline for agent '{agent_id}' completed successfully.")
        except Exception as e:
            log.error(f"Error in approved robustness pipeline for agent {agent_id}: {e}", exc_info=True)
            raise Exception(f"Approved robustness pipeline failed for agent {agent_id}: {str(e)}")

        
    async def perform_robustness_reevaluation(
        self,
        agent_details: dict,
        
    ):
        """
        Runs a single, intelligent robustness re-evaluation for a given agent.
        """
        agent_id = agent_details['agent_id']
        model_name = agent_details['model_name']
        table_name = f"robustness_{agent_id}"
        log.info(f"Starting intelligent robustness re-evaluation for agent: {agent_id}")

        try:
            last_queries_update = agent_details.get('queries_last_updated_at')
            last_robustness_run = agent_details.get('last_robustness_run_at')

            should_regenerate_queries = False
            if last_robustness_run is None or (last_queries_update and last_queries_update > last_robustness_run):
                should_regenerate_queries = True
            
            # --- THIS IS THE FIX ---
            # Get the current state of the table BEFORE the `if` block.
            # This ensures `df_check` always exists.
            df_check = await self.consistency_service.get_full_data_as_dataframe(table_name)
            # -----------------------

            if should_regenerate_queries:
                log.info(f"Consistency queries updated. Regenerating robustness suite for agent: {agent_id}")
                
                categories = ["Unexpected Input (Out-of-Scope Requests)", "Tool Error Simulation (Missing Specific Capability)", "Adversarial Input (Deceptive Details)"]
                new_dataset = []
                for cat in categories:
                    new_dataset += await self.generate_contextual_queries(agent_id, cat)
                
                timestamp = datetime.now(ist).strftime("%Y-%m-%d_%H-%M-%S")
                
                if not df_check.empty:
                    # Table exists: Perform the rename/add/update dance
                    await self.consistency_service.rename_column_with_timestamp(table_name, "query", timestamp, "query")
                    await self.consistency_service.rename_column_with_timestamp(table_name, "category", timestamp, "category")
                    
                    await self.consistency_service.add_column_to_agent_table(table_name, "query", "TEXT")
                    await self.consistency_service.add_column_to_agent_table(table_name, "category", "TEXT")

                    new_queries = [item['query'] for item in new_dataset]
                    new_categories = [item['category'] for item in new_dataset]
                    await self.consistency_service.update_column_by_row_id(table_name, "query", new_queries)
                    await self.consistency_service.update_column_by_row_id(table_name, "category", new_categories)

            # --- The rest of the pipeline ---
            
            df = await self.consistency_service.get_full_data_as_dataframe(table_name)
            if df.empty:
                if 'new_dataset' in locals():
                    df = pd.DataFrame(new_dataset)
                else:
                    log.warning("No data and no regenerated queries. Skipping.")
                    return

            enriched_data, response_col, score_col = await self.run_agent_on_dataset(
                dataset=df.to_dict('records'), model_name=model_name, agentic_application_id=agent_id
            )

            scored_data = await self.score_responses(
                enriched_data, response_col, score_col, model_name
            )
            
            df_results = pd.DataFrame(scored_data)
            
            # Now this check is safe because `df_check` is guaranteed to exist.
            if df_check.empty:
                await self.consistency_service.create_and_insert_robustness_data(
                    table_name=agent_id, dataset=df_results.to_dict('records'),
                    res_col=response_col, score_col=score_col
                )
            else:
                row_ids = df_results['id'].tolist()
                new_responses = df_results[response_col].tolist()
                new_scores = df_results[score_col].tolist()
                await self.consistency_service.add_column_to_agent_table(table_name, response_col, "TEXT")
                await self.consistency_service.add_column_to_agent_table(table_name, score_col, "REAL")
                await self.consistency_service.update_data_in_agent_table(table_name, response_col, list(zip(new_responses, row_ids)))
                await self.consistency_service.update_data_in_agent_table(table_name, score_col, list(zip(new_scores, row_ids)))

            await self.consistency_service.update_robustness_timestamp(agent_id)
            log.info(f"✅ Robustness re-evaluation for agent '{agent_id}' complete.")
        except Exception as e:
            log.error(f"Error during robustness re-evaluation for '{agent_id}': {e}", exc_info=True)



    async def schedule_continuous_robustness_reevaluations(
        self
    ):
        """
        A background task that periodically checks for and runs robustness re-evaluations
        using modular services.
        """
        try:
            CHECK_INTERVAL_MINUTES_robustness = 1440  # 24 hours
            log.info(f"[Robustness Scheduler] Background task started. Will check for robustness re-evaluations every {CHECK_INTERVAL_MINUTES_robustness} minutes (24 hours).")
            
            while True:
                log.debug("[Robustness Scheduler] Starting cycle...")
                try:
                    # USE SERVICE to get the list of agents
                    agents_to_run = await self.consistency_service.get_agents_for_robustness_reeval(CHECK_INTERVAL_MINUTES_robustness)
                    for agent in agents_to_run:
                        # Pass the services down to the worker function
                        await self.perform_robustness_reevaluation(agent)
                except Exception as e:
                    log.error(f"[Robustness Scheduler] An unexpected error occurred in the cycle: {e}", exc_info=True)
                
                log.debug(f"[Robustness Scheduler] Waiting for {CHECK_INTERVAL_MINUTES_robustness} minutes for the next cycle.")
                await asyncio.sleep(CHECK_INTERVAL_MINUTES_robustness * 60)

        except Exception as e:
            log.error(f"[Robustness Scheduler] Critical error in background task: {e}", exc_info=True)


