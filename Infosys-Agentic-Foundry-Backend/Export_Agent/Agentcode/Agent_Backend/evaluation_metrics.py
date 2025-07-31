# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import ast
import json
from typing import Callable

from langchain_core.prompts import ChatPromptTemplate, PromptTemplate
from langchain_core.output_parsers import StrOutputParser

from src.prompts.prompts import (
    agent_evaluation_prompt1,
    agent_evaluation_prompt2,
    agent_evaluation_prompt3,
    tool_eval_prompt)

from src.inference.base_agent_inference import AgentInferenceRequest, BaseAgentInference
from src.models.model import load_model
from database_manager import fetch_next_unprocessed_evaluation, insert_evaluation_metrics, insert_tool_evaluation_metrics, update_processing_status_id
from telemetry_wrapper import logger as log


async def evaluate_agent_performance(
    llm,
    User_Query,
    Agent_Response,
    Agent_Goal,
    Steps,
    Workflow_Description,
    model_used,
    agent_id,
    session_id,
    specialized_agent_inference: BaseAgentInference,
    weights=None  # Optional: pass custom weights as a dict
):
    # Step 1: Fetch evaluation context
    base_query = User_Query
    agentic_application_id = agent_id
    session_id = 'test_session_id'
    model_name = model_used
    # Step 2: Generate similar queries
    variation_prompt = PromptTemplate(
        input_variables=["base_query", "n"],
        template="""
        You are a helpful assistant. Generate {n} different user queries that are semantically similar to the following query, with slightly varied wording. Ensure the meaning remains the same.
        Query: "{base_query}"
        Respond with a valid Python list of {n} strings.
            """
    )

    query_chain = variation_prompt | llm
    variation_response = query_chain.invoke({"base_query": base_query, "n": 3})
    raw_response = variation_response.content if hasattr(variation_response, "content") else str(variation_response)
    match = re.search(r"```(?:python)?\s*(.*?)\s*```", raw_response, re.DOTALL)
    clean_response = match.group(1) if match else raw_response
    try:
        query_list = ast.literal_eval(clean_response)
    except Exception:
        query_list = []
    # Step 3: Run queries through the agent
    responses = []
    for query in query_list:
        req = AgentInferenceRequest(
            agentic_application_id=agentic_application_id,
            query=query,
            session_id=session_id,
            model_name=model_name,
            reset_conversation=True
        )
        try:
            response = await specialized_agent_inference.run(req, insert_into_eval_flag=False)
            result = response if isinstance(response, dict) else {"response": f"Error: {response}"}
        except Exception as e:
            result = {"response": f"Exception: {str(e)}"}
        responses.append({
            "query": query,
            "response": result
        })

    final_responses = []
    for r in responses:
        resp = r["response"]
        if isinstance(resp, dict) and "response" in resp:
            final_responses.append(resp["response"])
        else:
            final_responses.append(f"Invalid or error response for query: {r['query']}")
    #Query and response for robustness evaluation
    robustness_variation_prompt = PromptTemplate(
    input_variables=["base_query", "n"],
    template="""
    You are an intelligent assistant. Generate {n} user queries that are based on the following base query, but introduce unexpected variations, malformed phrasing, contradictions, or subtle ambiguities. 
    These should resemble natural human questions or instructions, not clearly artificial or self-referential ones. 
    Avoid obvious meta-prompts or non-human phrasing. 
    Each query should sound like something a human might plausibly ask, even if it’s unclear, tricky, or oddly worded.

    Base Query: "{base_query}"

    Respond ONLY with a valid Python list of {n} strings. No explanations, no formatting, just the list.
    """
    )

    # Step 3: Generate robustness queries (unexpected, malformed, or adversarial)
    query_chain_robustness = robustness_variation_prompt | llm
    variation_response_robustness = query_chain_robustness.invoke({"base_query": base_query, "n": 3})
   
    raw_response_robustness = variation_response_robustness.content if hasattr(variation_response_robustness, "content") else str(variation_response_robustness)
    

    def fallback_extract_numbered_queries(text: str):
        """
        Extracts quoted strings from a numbered list like:
        1. "some query"
        2. "another query"
        """
        return re.findall(r'\d+\.\s*"(.*?)"', text)
    # Extract list of robustness queries
    match_robustness = re.search(r"```(?:python)?\s*(.*?)\s*```", raw_response_robustness, re.DOTALL)
    clean_response_robustness = match_robustness.group(1) if match_robustness else raw_response_robustness

    # Strip out variable assignment if it exists
    if "=" in clean_response_robustness:
        clean_response_robustness = clean_response_robustness.split("=", 1)[1].strip()

    try:
        query_list_robust = ast.literal_eval(clean_response_robustness)
    except Exception:
        query_list_robust = fallback_extract_numbered_queries(clean_response_robustness)
    # Step 4: Run robustness queries through the agent
    responses_robustness = []
    for query in query_list_robust:
        req = AgentInferenceRequest(
            agentic_application_id=agentic_application_id,
            query=query,
            session_id=session_id,
            model_name=model_name,
            reset_conversation=True
        )
        try:
            response = await specialized_agent_inference.run(req, insert_into_eval_flag=False)
            result = response if isinstance(response, dict) else {"response": f"Error: {response}"}
        except Exception as e:
            result = {"response": f"Exception: {str(e)}"}
        
        responses_robustness.append({
            "query": query,
            "response": result
        })

    # Step 5: Finalize the responses for robustness
    final_responses_robustness = []
    for r in responses_robustness:
        resp = r["response"]
        if isinstance(resp, dict) and "response" in resp:
            final_responses_robustness.append(resp["response"])
        else:
            final_responses_robustness.append(f"Invalid or error response for query: {r['query']}")

    # Step 5: LLM-based agent analysis
    agent_breakdown = llm.invoke(f"""
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
    """).content
  
    past_conversation_summary = llm.invoke(f"""
    You are an **LLM conversation summarization agent**. Your task is to **extract only the past conversation summary** from the following conversation steps. Do not include ongoing conversation details. Provide a concise yet informative summary of the past conversation.

    #### **Instructions:**  
    - Focus only on summarizing the **past conversation** section.
    - Extract and summarize the **key points** and **responses** from the past conversation section provided below.
    - Ensure to avoid ongoing conversation details and focus purely on **completed exchanges**.
    
    Past Conversation Summary:
    {Steps}

    """).content

    tool_calls=[]
    for i in Steps:
      if i['type']=='ai':
          if i['tool_calls']:
              for j in i['tool_calls']:
                  tool_calls.append(j)
    statuses=[]
    for i in Steps:
        if i['type']=='tool':
            statuses.append(i)

    for tool in tool_calls:
      # Find the matching status using tool_call_id
      match = next((item for item in statuses if item['tool_call_id'] == tool['id']), None)
      if match:
          tool['status'] = match['status']
      else:
          tool['status'] = 'unknown'
    # Step 6: Define and run agent evaluation chains
    agent_chain_1 = ChatPromptTemplate.from_template(agent_evaluation_prompt1) | llm | StrOutputParser()
    agent_chain_2 = ChatPromptTemplate.from_template(agent_evaluation_prompt2) | llm | StrOutputParser()
    agent_chain_3 = ChatPromptTemplate.from_template(agent_evaluation_prompt3) | llm | StrOutputParser()

    result_1 = agent_chain_1.invoke({
        "User_Query": User_Query,
        "Agent_Response": Agent_Response,
        "workflow_description": Workflow_Description,
        "past_conversation_summary": past_conversation_summary
    })
    result_2 = agent_chain_2.invoke({
        "user_task": User_Query,
        "Agent_Goal": Agent_Goal,
        "agent_breakdown": agent_breakdown,
        "agent_response": Agent_Response,
        "workflow_description": Workflow_Description,
        "tool_calls": tool_calls
    })
    result_3 = agent_chain_3.invoke({
        "user_query_list":query_list_robust,
        "response_list":responses_robustness,
        "user_queries_list": query_list,
        "agent_responses_list": final_responses
    })
    def parse_json(raw):
        return json.loads(raw.replace("```json", "").replace("```", ""))
    res_1 = parse_json(result_1)
    res_2 = parse_json(result_2)
    res_3 = parse_json(result_3)
    # Step 7: Score Calculation with weights
    def calculate_weighted_score():
        # Extract scores
        scores = {
            'Fluency': res_1['fluency_evaluation']['fluency_rating'],
            'Relevancy': res_1['relevancy_evaluation']['relevancy_rating'],
            'Coherence': res_1['coherence_evaluation']['coherence_score'],
            'Groundness': res_1['groundedness_evaluation']['groundedness_score'],
            'Task Decomposition': res_2['task_decomposition_evaluation']['rating'],
            'Reasoning Relevancy': res_2['reasoning_relevancy_evaluation']['reasoning_relevancy_rating'],
            'Reasoning Coherence': res_2['reasoning_coherence_evaluation']['reasoning_coherence_score'],
            'Agent Consistency': res_3['agent_consistency_evaluation']['agent_consistency_score'],
            'Agent Robustness': res_3['agent_robustness_evaluation']['agent_robustness_score'],
        }

        justifications = {
        'Fluency': res_1['fluency_evaluation']['justification'],
        'Relevancy': res_1['relevancy_evaluation']['justification'],
        'Coherence': res_1['coherence_evaluation']['justification'],
        'Groundness': res_1['groundedness_evaluation']['justification'],
        'Task Decomposition': res_2['task_decomposition_evaluation']['justification'],
        'Reasoning Relevancy': res_2['reasoning_relevancy_evaluation']['justification'],
        'Reasoning Coherence': res_2['reasoning_coherence_evaluation']['justification'],
        'Agent Consistency': res_3['agent_consistency_evaluation']['justification'],
        'Agent Robustness': res_3['agent_robustness_evaluation']['justification'],
        }

    
        # Default weights
        default_weights = {
            'Fluency': 1,
            'Relevancy': 1,
            'Coherence': 1,
            'Groundness': 1,
            'Task Decomposition': 1,
            'Reasoning Relevancy': 1,
            'Reasoning Coherence': 1,
            'Agent Consistency': 1,
            'Agent Robustness': 1,
        }

        # Use passed weights or defaults
        applied_weights = weights if weights else default_weights

        total_weight = sum(applied_weights[k] for k in scores)
        weighted_sum = sum(scores[k] * applied_weights[k] for k in scores)

        efficiency_score = weighted_sum / total_weight if total_weight else 0

        # Categorize score
        if efficiency_score < 0.2:
            category = "Bad"
        elif efficiency_score < 0.5:
            category = "Below Average"
        elif efficiency_score < 0.75:
            category = "Average"
        else:
            category = "Good"

        scores['Agent Utilization Efficiency'] = efficiency_score
        scores['Efficiency Category'] = category
        return scores,justifications ,  query_list, query_list_robust
    log.info("Agent evaluation completed successfully.")
    return calculate_weighted_score()


async def tool_utilization_efficiency(llm, agent_name, agent_goal, workflow_description, tool_prompt, steps, user_query, agent_response):
    tool_calls = []

    # Collect tool calls from workflow steps
    for step in steps:
        if step['type'] == 'ai' and step.get('tool_calls'):
            tool_calls.extend(step['tool_calls'])

    #  Return None if no tool calls were found
    if not tool_calls:
        return None

    statuses = [step for step in steps if step['type'] == 'tool']

    # Match tool calls with statuses
    for tool in tool_calls:
        match = next((item for item in statuses if item['tool_call_id'] == tool['id']), None)
        tool['status'] = match['status'] if match else 'unknown'

    # Set up the LLM chain
    prompt = ChatPromptTemplate.from_template(tool_eval_prompt)
    tool_eval_chain = prompt | llm | StrOutputParser()

    # Calculate tool call success rate
    tool_call_success_rate = 0
    tools_success = sum(1 for tool_call in tool_calls if tool_call.get("status", "").lower() == 'success')
    tools_failed = sum(1 for tool_call in tool_calls if tool_call.get("status", "").lower() == 'error')
    total_calls = tools_success + tools_failed
    if total_calls > 0:
        tool_call_success_rate = tools_success / total_calls

    try:
        # Invoke the LLM for evaluation
        evaluation_result = tool_eval_chain.invoke({
            "agent_name": agent_name,
            "agent_goal": agent_goal,
            "workflow_description": workflow_description,
            "tool_prompt": tool_prompt,
            "no_of_tools_called": len(tool_calls),
            "tool_calls": tool_calls,
            "user_query": user_query,
            "agent_response": agent_response,
        })

        # Clean up the result and parse it
        evaluation_result = evaluation_result.replace('```json', '').replace('```', '')
        res = json.loads(evaluation_result)

        def safe_int(value):
            try:
                if isinstance(value, (str, bytes)) and str(value).isdigit():
                    return int(value)
                elif isinstance(value, (int, float)):
                    return int(value)
                return None
            except (ValueError, TypeError):
                return None

        tsa_values = [
            safe_int(i['status']) if isinstance(i, dict) and 'status' in i else safe_int(i)
            for i in res.get('tool_selection_accuracy', {}).values()
            if safe_int(i['status'] if isinstance(i, dict) else i) is not None
        ]
        tsa = sum(tsa_values) / len(tsa_values) if tsa_values else 0

        tue = res.get('tool_usage_efficiency', {}).get('status', 0)

        tcp_values = [
            safe_int(i['status']) if isinstance(i, dict) and 'status' in i else safe_int(i)
            for i in res.get('tool_call_precision', {}).values()
            if safe_int(i['status'] if isinstance(i, dict) else i) is not None
        ]
        tcp = sum(tcp_values) / len(tcp_values) if tcp_values else 0

        # Calculate tool utilization efficiency
        w_tsa = w_tue = w_tcp = w_tcsr = 1
        tool_utilization_efficiency = (w_tsa * tsa + w_tue * tue + w_tcp * tcp + w_tcsr * tool_call_success_rate) / 4

        # Categorize tool utilization efficiency
        if tool_utilization_efficiency < 0.2:
            category = 'Bad'
        elif tool_utilization_efficiency < 0.5:
            category = 'Below Average'
        elif tool_utilization_efficiency < 0.75:
            category = 'Average'
        else:
            category = 'Good'
        log.info(f"Tool Evaluation completed successfully")
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
        log.error(f"Error during tool evaluation: {e}")
        return {"error": f"Failed to process tool evaluation: {e}"}


async def process_unprocessed_evaluations(model1, model2, get_specialized_inference_service: Callable[[str], BaseAgentInference]):
    # llm = load_model(model_name=model1)
    
    while True:
        # Fetch the next unprocessed evaluation data
        data = await fetch_next_unprocessed_evaluation()
        if not data:
            log.info("No more unprocessed evaluations found.")
            break

        evaluation_id = data["id"]
        log.info(f"Processing evaluation_id: {evaluation_id}")
        model = model2 if data['model_used'] == model1 else model1
        llm = load_model(model_name=model)
        agent_type = data["agent_type"]
        try:
            specialized_agent_inference: BaseAgentInference = get_specialized_inference_service(agent_type)
            # === Agent Evaluation ===
            # Call evaluate_agent_performance and unpack both scores and justifications
            scores, justifications, consistency_queries, robustness_queries = await evaluate_agent_performance(
                llm,
                data["query"],
                data["response"],
                data["agent_goal"],
                data["steps"],
                data["workflow_description"],
                data["model_used"],
                data['agent_id'],
                data['session_id'],
                specialized_agent_inference=specialized_agent_inference
            )

            # Ensure agent_result contains justification and score fields
            if scores and justifications:
                await insert_evaluation_metrics(
                    evaluation_id,
                    data["query"],
                    data["response"],
                    data["model_used"],
                    scores,  # Insert scores here
                    justifications,  # Insert justifications here
                    consistency_queries,
                    robustness_queries,
                    model
                )
            else:
                log.warning(f" Agent evaluation failed or returned empty for evaluation_id {evaluation_id}")

            # === Tool Evaluation ===
            tool_result =await tool_utilization_efficiency(
                llm,
                data["agent_name"],
                data["agent_goal"],
                data["workflow_description"],
                data["tool_prompt"],
                data["steps"],
                data["query"],
                data["response"]
            )

            # If tool_result is not None, extract justifications and insert them into the database
            if tool_result is not None:
                # Prepare the result_dict to pass into the insert function
                result_dict = {
                    "tool_selection_accuracy": tool_result["tool_selection_accuracy"],
                    "tool_usage_efficiency": tool_result["tool_usage_efficiency"],
                    "tool_call_precision": tool_result["tool_call_precision"],
                    "tool_call_success_rate": tool_result["tool_call_success_rate"],
                    "tool_utilization_efficiency": tool_result["tool_utilization_efficiency"],
                    "tool_utilization_efficiency_category": tool_result["tool_utilization_efficiency_category"]
                }

                # Pass the result_dict instead of individual metric values
                await insert_tool_evaluation_metrics(
                    evaluation_id,
                    data["query"],
                    data["response"],
                    data["model_used"],
                    result_dict,  # Pass the result_dict here
                    tool_result.get("tool_selection_accuracy_justification", ""),
                    tool_result.get("tool_usage_efficiency_justification", ""),
                    tool_result.get("tool_call_precision_justification", ""),
                    model
                )
            else:
                log.warning(f" No tool usage detected for evaluation_id {evaluation_id}. Skipping tool metrics insert.")

            # Update processing status
            await update_processing_status_id(evaluation_id, "success")
            log.info(f" Successfully processed evaluation_id: {evaluation_id}")
            
        except Exception as e:
            log.error(f" Error during evaluation of ID {evaluation_id}: {e}")
            await update_processing_status_id(evaluation_id, "error")
            
    log.info("All evaluations processed, Please check the database and dashboard for results.")
    return "All evaluations processed, Please check the database and dashboard for results."