# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import os
import shutil
import ast
import psycopg2
import re
import bcrypt
import uuid
import secrets

from typing import List, Dict, Optional, Union
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, Query, Header
from fastapi.responses import JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from contextlib import closing
from pydantic import BaseModel
from src.tools.tool_docstring_generator import *
from src.agent_templates.react_agent_onboarding import react_system_prompt_gen_func
from inference import *
from replanner_multi_agent_inference import human_in_the_loop_replanner_inference, ReplannerAgentInferenceRequest
from database_creation import initialize_tables
from database_manager import *
from tool_exec import test_Case6_validate_dangerous_tool_usage


# Connection string format:
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")
DATABASE_URL = os.getenv("POSTGRESQL_DATABASE_URL", "")


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_tables()
    assign_general_tag_to_untagged_items()
    yield

app = FastAPI(lifespan=lifespan)


# # Configure CORS
origins = [
    "http://127.0.0.1", # Allow 127.0.0.1
    "http://127.0.0.1:3000", #If your frontend runs on port 3000
    "http://localhost",
    "http://localhost:3000"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)



class GetAgentRequest(BaseModel):
    """
    A class used to represent a Get Agent Request.

    Attributes:
    ----------
    agentic_application_id : str
        The ID of the agentic application.
    agent_table_name : Optional[str], optional
        The name of the agent table (default is "agent_table").
    tool_table_name : Optional[str], optional
        The name of the tool table (default is "tool_table").
    """
    agentic_application_id: str
    agent_table_name: Optional[str] = "agent_table"
    tool_table_name: Optional[str] = "tool_table"


class ToolData(BaseModel):
    """
    A class used to represent tool data.

    Attributes
    ----------
    tool_description : str
        A brief description of the tool.
    code_snippet : str
        A code snippet demonstrating the tool's usage.
    model_name : str
        The name of the model associated with the tool.
    created_by : str
        The name of the person or entity that created the tool.
    """
    tool_description: str
    code_snippet: str
    model_name: str
    tag_ids: Optional[Union[str, List[str]]] = None
    created_by: str


class AgentOnboardingRequest(BaseModel):
    """
    A class used to represent an Agent Onboarding Request.

    Attributes:
    ----------
    agent_name : str
        The name of the agent.
    agent_goal : str
        The goal or purpose of the agent.
    workflow_description : str
        A description of the workflow the agent will follow.
    model_name : str
        The name of the model to be used by the agent.
    tools_id : List[str]
        A list of tool IDs that the agent will use.
    email_id : str
        The email ID associated with the agent.
    """
    agent_name: str
    agent_goal: str
    workflow_description: str
    model_name: str
    tools_id: List[str]
    tag_ids: Optional[Union[str, List[str]]] = None
    email_id: str



class UpdateToolRequest(BaseModel):
    """
    A class used to represent an Update Tool Request.

    Attributes:
    ----------
    model_name : str
        The name of the model to be updated.
    user_email_id : str
        The email ID of the user requesting the update.
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    tool_description : Optional[str], optional
        A description of the tool (default is None).
    code_snippet : Optional[str], optional
        A code snippet related to the tool (default is None).
    """
    model_name: str
    user_email_id: str
    is_admin: bool = False
    tool_description: Optional[str] = None
    code_snippet: Optional[str] = None
    updated_tag_id_list: Optional[Union[str, List[str]]] = None


class DeleteToolRequest(BaseModel):
    """
    A class used to represent a Delete Tool Request.

    Attributes:
    ----------
    user_email_id : str
        The email ID of the user requesting the deletion.
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    """
    user_email_id: str
    is_admin: bool = False


class UpdateAgentRequest(BaseModel):
    """
    A class used to represent an Update Agent Request.

    Attributes:
    ----------
    model_name : str
        The name of the model to be updated.
    user_email_id : str
        The email ID of the user requesting the update.
    agentic_application_id_to_modify : str
        The ID of the agentic application to be modified.
    agentic_application_type : str
        The type of the agentic application.
    agentic_application_name_to_modify : str, optional
        The name of the agentic application to be modified (default is an empty string).
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    agentic_application_description : str, optional
        A description of the agentic application (default is an empty string).
    agentic_application_workflow_description : str, optional
        A description of the workflow of the agentic application (default is an empty string).
    system_prompt : dict
        The system prompt for the agentic application.
    tools_id_to_add : List[str], optional
        A list of tool IDs to be added (default is an empty list).
    tools_id_to_remove : List[str], optional
        A list of tool IDs to be removed (default is an empty list).
    """
    model_name: str
    user_email_id: str
    agentic_application_id_to_modify: str
    agentic_application_type: str
    agentic_application_name_to_modify: str = ""
    is_admin: bool = False
    agentic_application_description: str = ""
    agentic_application_workflow_description: str = ""
    system_prompt: dict
    tools_id_to_add: List[str] = []
    tools_id_to_remove: List[str] = []
    updated_tag_id_list: Optional[Union[str, List[str]]] = None


class UpdateSystemPromptAgent(UpdateAgentRequest):
    new_tool_lists: List[str] = []



class DeleteAgentRequest(BaseModel):
    """
    A class used to represent a Delete Agent Request.

    Attributes:
    ----------
    user_email_id : str
        The email ID of the user requesting the deletion.
    is_admin : bool, optional
        Indicates if the user has admin privileges (default is False).
    """
    user_email_id: str
    is_admin: bool = False


class AgentInferenceRequest(BaseModel):
    """
    Pydantic model representing the input request for agent inference.
    This model captures the necessary details for querying the agent,
    including the application ID, query, session ID, and model-related information.
    """
    agentic_application_id: str  # ID of the agentic application
    query: str  # The query to be processed by the agent
    session_id: str  # Unique session identifier
    model_name: str  # Name of the llm model
    reset_conversation: bool = False# If true need to reset the conversation


class TagData(BaseModel):
    tag_name: str
    created_by: str

class UpdateTagData(BaseModel):
    tag_id: Optional[str] = None
    tag_name: Optional[str] = None
    new_tag_name: str
    created_by: str

class DeleteTagData(BaseModel):
    tag_id: Optional[str] = None
    tag_name: Optional[str] = None
    created_by: str

class AgentIdName(BaseModel):
    agentic_application_id: Optional[str] = None
    agent_name: Optional[str] = None

class ToolIdName(BaseModel):
    tool_id: Optional[str] = None
    tool_name: Optional[str] = None

class TagIdName(BaseModel):
    tag_ids: Optional[Union[str, List[str]]] = None
    tag_names: Optional[Union[str, List[str]]] = None




def extract_fn_name(code_str: str):
    """
        Using the ast module syntax check the function and
        return the function name in the code snippet.
    """

    try:
        parsed_code = ast.parse(code_str)
    except Exception as e:
        err = f"Tool Onboarding Failed: Function parsing error.\n{e}"
        return ""

    try:
        for node in parsed_code.body:
            if isinstance(node, ast.FunctionDef):
                for arg in node.args.args:
                    if arg.annotation is None:
                        raise ValueError("Data Types Not Mentioned for the arguments of the function")

        function_names = [
            node.name
            for node in ast.walk(parsed_code)
            if isinstance(node, ast.FunctionDef)
        ]
        return function_names[0] if function_names else ""
    except (SyntaxError, ValueError, IndexError) as e:
        err = f"There is a syntax mistake in it: {e}"
        return ""


def get_agents_by_ids_studio(agentic_application_ids: List[str]) -> List[dict]:
    agents = []
    for agent_id in agentic_application_ids:
        # Simulated data for agents
        agents.append({"agent_id": agent_id, "name": f"Agent {agent_id}"})
    return agents


def verify_csrf_token(session_id: str, csrf_token: str) -> Optional[JSONResponse]:
    status = is_valid_session_and_token(session_id=session_id, csrf_token=csrf_token)
    if not status["is_valid"]:
        return JSONResponse(status_code=401, content={"error": status["message"]})
    return None


@app.get('/get-models')
async def get_available_models():
    try:
        # Use 'with' for automatic cleanup
        db_params = {
            'dbname': DATABASE,
            'user': POSTGRESQL_USER,
            'password': POSTGRESQL_PASSWORD,
            'host': POSTGRESQL_HOST,  # or the host where your DB is running
            'port': 5432          # default PostgreSQL port
        }
        with psycopg2.connect(**db_params) as connection:
            with closing(connection.cursor()) as cursor:
                cursor.execute("SELECT model_name FROM models;")
                data = cursor.fetchall()
                data = list(map(lambda x: x[0], data))

        # Returning JSON data using FastAPI's built-in JSONResponse
        return JSONResponse(content={"models": data})

    except psycopg2.Error as e:
        # Handle any SQLite errors
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        # Handle other unforeseen errors
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")



@app.post("/add-tool")
async def add_tool(tool_data: ToolData, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Adds a new tool to the tool table after verifying code safety.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    tool_list = dict(tool_data)

    # Extract tool name from code
    tool_list["tool_name"] = extract_fn_name(code_str=tool_list["code_snippet"])
   
    if not tool_list["tool_name"]:
        status={
            "message" : f"Invalid syntax or missing type annotations in the function parameters",
            "is_created":False      
        }
        return status
    
    # Check if the code is safe
    is_safe, feedback = test_Case6_validate_dangerous_tool_usage(tool_list["code_snippet"])
    if not is_safe:

        status={
                "message" : f"Code snippet failed safety validation. Ensure it doesn't contain unsafe code or syntax issues. {feedback}",
                "is_created":False      
            }
        return status
 
 
    # Add default tag if none is provided
    if not tool_list.get("tag_ids"):
        tool_list['tag_ids'] = get_tags_by_id_or_name(tag_name="General").get("tag_id", None)
 
    # Insert tool
    status = insert_into_tool_table(tool_list)
    return status

@app.get("/get-tools/")
async def get_tools_endpoint():
    """
    Retrieves all tools from the tool table.

    Returns:
    -------
    list
        A list of tools. If no tools are found, raises an HTTPException with status code 404.
    """
    tools = await get_tools()
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found")
    return tools


@app.get("/get-tool/{tool_id}")
async def get_tool_by_id(tool_id: str):
    """
    Retrieves a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the tool's details.
        If the tool is not found, raises an HTTPException with status code 404.
    """
    tool = get_tools_by_id(tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    return tool

 
@app.put("/update-tool/{tool_id}")
async def update_tool_endpoint(tool_id: str, request: UpdateToolRequest):
    """
    Updates a tool by its ID after checking the code for safety.
 
    Parameters:
    ----------
    tool_id : str
        The ID of the tool to be updated.
    request : UpdateToolRequest
        The request body containing the update details.
 
    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        Raises HTTPException with status code 400 if the update is not safe or fails.
    """
 
    # Safety Validation of the code snippet
    is_safe, feedback = test_Case6_validate_dangerous_tool_usage(request.code_snippet)
    if not is_safe:
        raise HTTPException(
            status_code=400,
            detail=f"Code validation failed. Unsafe operation detected. Suggestion: {feedback}"
        )
 
    # Proceed with update if code is safe
    response = update_tool_by_id(
        model_name=request.model_name,
        user_email_id=request.user_email_id,
        is_admin=request.is_admin,
        tool_id_to_modify=tool_id,
        tool_description=request.tool_description,
        code_snippet=request.code_snippet,
        updated_tag_id_list=request.updated_tag_id_list
    )
 
    if not response.get("is_update", False):
        raise HTTPException(status_code=400, detail=response.get("status_message", "Update failed."))
 
    return response


@app.delete("/delete-tool/{tool_id}")
async def delete_tool(tool_id: str, request: DeleteToolRequest):
    """
    Deletes a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be deleted.
    request : DeleteToolRequest
        The request body containing the user email ID and admin status.

    Returns:
    -------
    dict
        A dictionary containing the status of the deletion operation.
    """
    status = delete_tools_by_id(user_email_id=request.user_email_id,
                                is_admin=request.is_admin,
                                tool_id=tool_id)
    return status


@app.put("/react-agent/update-system-prompt")
async def update_system_prompt_react_agent(request: UpdateSystemPromptAgent):
    llm = load_model(model_name=request.model_name)
    tools_info=extract_tools_using_tools_id(request.new_tool_lists)
    tool_prompt=generate_tool_prompt(tools_info)
    updated_agent_system_prompt = react_system_prompt_gen_func(agent_name=request.agentic_application_name_to_modify,
                                            agent_goal=request.agentic_application_description,
                                            workflow_description=request.agentic_application_workflow_description,
                                            tool_prompt=tool_prompt,
                                            llm=llm)
    return {"SYSTEM_PROMPT_REACT_AGENT": updated_agent_system_prompt}


@app.put("/planner-executor-critic-agent/update-system-prompt")
async def update_system_prompt_planner_executor_critic_agent(request: UpdateSystemPromptAgent):
    llm = load_model(model_name=request.model_name)
    tools_info=extract_tools_using_tools_id(request.new_tool_lists)
    tool_prompt=generate_tool_prompt(tools_info)
    updated_agent_system_prompts = planner_executor_critic_builder(agent_name=request.agentic_application_name_to_modify,
                                            agent_goal=request.agentic_application_description,
                                            workflow_description=request.agentic_application_workflow_description,
                                            tool_prompt=tool_prompt,
                                            llm=llm)
    return updated_agent_system_prompts["MULTI_AGENT_SYSTEM_PROMPTS"]


@app.post("/react-agent/onboard-agent")
async def onboard_agent(request: AgentOnboardingRequest, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Onboards a new agent.

    Parameters:
    ----------
    request : AgentOnboardingRequest
        The request body containing the agent's details.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with
        status code 500 and the error message.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    try:
        if not request.tag_ids:
            request.tag_ids = get_tags_by_id_or_name(tag_name="General").get("tag_id", None)
        result = react_agent_onboarding(
            agent_name=request.agent_name,
            agent_goal=request.agent_goal,
            workflow_description=request.workflow_description,
            model_name=request.model_name,
            tools_id=request.tools_id,
            user_email_id=request.email_id,
            tag_ids=request.tag_ids
        )
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}"
        ) from e


@app.post("/planner-executor-critic-agent/onboard-agents")
async def onboard_agents(request: AgentOnboardingRequest, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Onboards multiple agents in one go.
    -------
    Param---
    request :  AgentOnboardingRequest
        The request body containing a list of agents' onboarding details.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation for each agent.
        If an error occurs, raises an HTTPException with error details.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    try:
        if not request.tag_ids:
            request.tag_ids = get_tags_by_id_or_name(tag_name="General").get("tag_id", None)
        result = react_multi_agent_onboarding(
            agent_name=request.agent_name,
            agent_goal=request.agent_goal,
            workflow_description=request.workflow_description,
            model_name=request.model_name,
            tools_id=request.tools_id,
            user_email_id=request.email_id,
            tag_ids=request.tag_ids
        )
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}") from e


@app.get("/planner-executor-critic-agent/get-agents/")
@app.get("/react-agent/get-agents/")
@app.get("/get-agents/")
def get_agents_endpoint(
        agentic_application_type: Optional[str] = None,
        agent_table_name: str = "agent_table"):
    """
    Retrieves agents from the specified agent table.

    Parameters:
    ----------
    agentic_application_type : Optional[str], optional
        The type of agentic application to filter agents by (default is None).
    agent_table_name : str, optional
        The name of the agent table to retrieve agents from (default is "agent_table").

    Returns:
    -------
    list
        A list of agents. If no agents are found, raises an HTTPException with status code 404.
    """
    try:
        response = get_agents(agentic_application_type, agent_table_name)

        if not response:
            raise HTTPException(status_code=404, detail="No agents found")

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agents: {str(e)}")

@app.get("/planner-executor-critic-agent/get-agent/{agent_id}")
@app.get("/react-agent/get-agent/{agent_id}")
@app.get("/get-agent/{agent_id}")
def get_agent_by_id_endpoint(agent_id: str):
    """
    Retrieves an agent by its ID.

    Parameters:
    ----------
    id : str
        The ID of the agent to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the agent's details.
        If no agent is found, raises an HTTPException with status code 404.
    """
    response = get_agents_by_id(
        agentic_application_id=agent_id
    )
    if not response:
        raise HTTPException(status_code=404, detail="No agents found")
    return response

@app.get("/planner-executor-critic-agent/agent-details/{agent_id}")
@app.get("/react-agent/agent-details/{agent_id}")
@app.get("/agent-details/{agent_id}")
def get_agent_details(agent_id: str):
    """
    Retrieves detailed information about an agent by its ID.

    Parameters:
    ----------
    id : str
        The ID of the agent to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the agent's detailed information.
        If the agent is not found, raises an HTTPException with status code 404.
    """
    response = get_agents_by_id_studio(
        agentic_application_id=agent_id
    )
    if not response:
        raise HTTPException(status_code=404, detail="Agent not found")
    return response


@app.put("/planner-executor-critic-agent/update-agent")
@app.put("/react-agent/update-agent")
def update_agent(request: UpdateAgentRequest):
    """
    Updates an agent by its ID.

    Parameters:
    ----------
    request : UpdateAgentRequest
        The request body containing the update details.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    response = update_agent_by_id(
        model_name=request.model_name,
        user_email_id=request.user_email_id,
        agentic_application_type=request.agentic_application_type,
        is_admin=request.is_admin,
        agentic_application_id_to_modify=request.agentic_application_id_to_modify,
        agentic_application_name_to_modify=request.agentic_application_name_to_modify,
        agentic_application_description=request.agentic_application_description,
        agentic_application_workflow_description=request.agentic_application_workflow_description,
        system_prompt=request.system_prompt,
        tools_id_to_add=request.tools_id_to_add,
        tools_id_to_remove=request.tools_id_to_remove,
        updated_tag_id_list=request.updated_tag_id_list)
    if not response["is_update"]:
        raise HTTPException(status_code=400, detail=response["status_message"])
    return response



@app.delete("/planner-executor-critic-agent/delete-agent/{agent_id}")
@app.delete("/react-agent/delete-agent/{agent_id}")
@app.delete("/delete-agent/{agent_id}")
def delete_agent(agent_id: str, request: DeleteAgentRequest):
    """
    Deletes an agent by its ID.

    Parameters:
    ----------
    id : str
        The ID of the agent to be deleted.
    request : DeleteAgentRequest
        The request body containing the user email ID and admin status.

    Returns:
    -------
        dict
        A dictionary containing the status of the deletion operation.
        If the deletion is unsuccessful, raises an HTTPException
        with status code 400 and the status message.
    """
    response = delete_agent_by_id(
        user_email_id=request.user_email_id,
        is_admin=request.is_admin,
        agentic_application_id=agent_id
    )
    if not response["is_delete"]:
        raise HTTPException(status_code=400, detail=response["status_message"])
    return response

@app.post("/planner-executor-critic-agent/get-chat-history")
@app.post("/react-agent/get-chat-history")
@app.post("/get-chat-history")
async def get_history(request: PrevSessionRequest, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Retrieves the chat history of a previous session.

    Parameters:
    ----------
    request : PrevSessionRequest
        The request body containing the details of the previous session.

    Returns:
    -------
    dict
        A dictionary containing the previous conversation history.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    return retrive_previous_conversation(request=request)




@app.post("/get-query-response")
async def get_response(
    request: AgentInferenceRequest,
    session_id: str = Header(...),
    csrf_token: str = Header(...)
):
    """
    Gets the response for a query using agent inference.

    Parameters:
    ----------
    request : AgentInferenceRequest
        The request body containing the query details.

    Returns:
    -------
    dict
        A dictionary containing the response generated by the agent.
    """
    # Verify CSRF token
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error

    # If token is valid, process the request
    response = agent_inference(request)
    return response

@app.post("/react-agent/get-feedback-response/{feedback}")
async def get_response(
    feedback: str,
    request: AgentInferenceRequest,
    session_id: str = Header(...),
    csrf_token: str = Header(...)
):
    """
    Gets the response for the feedback using agent inference.

    Parameters:
    ----------
    feedback: str
        The feedback type
    request : AgentInferenceRequest
        The request body containing the feedback details.

    Returns:
    -------
    dict
        A dictionary containing the response generated by the agent.
    """
    # Verify CSRF token
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error

    if feedback == "like":
        update_status = update_latest_query_response_with_tag(
            agentic_application_id=request.agentic_application_id,
            session_id=request.session_id
        )
        if update_status is True:
            return {"message": "Thanks for the like! We're glad you found the response helpful. If you have any more questions or need further assistance, feel free to ask!"}
        elif update_status is False:
            return {"message": "Your like has been removed. If you have any more questions or need further assistance, feel free to ask!"}
        else:
            return {"message": "Sorry, we couldn't update your request at the moment. Please try again later."}
    elif feedback == "regenerate":
        request.query = "[regenerate:][:regenerate]"
    elif feedback == "feedback":
        request.query = f"[feedback:]{request.query}[:feedback]"
    else:
        return {"error": "Invalid Path!"}

    request.reset_conversation = False
    response = agent_inference(request)
    return response


@app.delete("/react-agent/clear-chat-history")
async def clear_chat_history(request: PrevSessionRequest):
    return delete_chat_history_by_session_id(request)

@app.get("/react-agent/get-chat-sessions")
async def get_chat_sessions():
    """
    Retrieves all tools from the tool table.

    Returns:
    -------
    list
        A list of all thread ids. If not found, raises an HTTPException with status code 404.
    """
    sessions=get_all_chat_sessions()
    if not sessions:
        raise HTTPException(status_code=404, detail="No thread id found")
    return sessions


@app.get("/react-agent/create-new-session")
async def create_new_session():
    """
    Create a new session id

    Returns:
    -------
    str
        A string containing new session ID. If not found, raises an HTTPException with status code 404.
    """
    import uuid
    session=str(uuid.uuid4())
    if not session:
        raise HTTPException(status_code=404, detail="Some problem occured while creating a new session")
    return session



@app.post("/planner-executor-critic-agent/get-query-response-hitl-replanner")
async def generate_response_replanner_executor_critic_agent_main(request: ReplannerAgentInferenceRequest, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (ReplannerAgentInferenceRequest): The request object containing the query, session ID, and other parameters.

    Returns:
        JSONResponse: A JSON response containing the agent's response and state.

    Raises:
        HTTPException: If an error occurs during processing.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    return human_in_the_loop_replanner_inference(request)




@app.post("/tags/create-tag")
def create_tag(tag_data: TagData, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Inserts data into the tags table in SQLite.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    result = insert_into_tags_table(dict(tag_data))
    return result

@app.get("/tags/get-available-tags")
def get_available_tags():
    """
    Retrieves tags from the tags table in SQLite.
    """
    return get_tags()

@app.get("/tags/get-tag/{tag_id}")
def read_tag_by_id(tag_id: str):
    """
    Retrieves tags from the SQLite database based on provided parameters.
    """
    result = get_tags_by_id_or_name(tag_id=tag_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tag not found")
    return result

@app.put("/tags/update-tag")
def update_tag(update_data: UpdateTagData):
    """
    Updates the tag name in the tags table if the given tag ID or tag name is present and created by the given user ID.
    """
    result = update_tag_name_by_id_or_name(**dict(update_data))
    return result

@app.delete("/tags/delete-tag")
def delete_tag(delete_data: DeleteTagData):
    """
    Deletes a tag from the tags table if the given tag ID or tag name is present and created by the given user ID.
    """
    result = delete_tag_by_id_or_name(**dict(delete_data))
    return result

@app.post("/tags/get-tags-by-agent")
def read_tags_by_agent(agent_data: AgentIdName, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Retrieves tags associated with a given agent ID or agent name.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    result = get_tags_by_agent(agent_id=agent_data.agentic_application_id, agent_name=agent_data.agent_name)
    if not result:
        raise HTTPException(status_code=404, detail="Tags not found")
    return result

@app.post("/tags/get-tags-by-tool")
def read_tags_by_tool(tool_data: ToolIdName, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Retrieves tags associated with a given tool ID or tool name.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    result = get_tags_by_tool(**(dict(tool_data)))
    if not result:
        raise HTTPException(status_code=404, detail="Tags not found")
    return result

@app.post("/tags/get-agents-by-tag")
def read_agents_by_tag(tag_data: TagIdName, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Retrieves agents associated with a given tag ID or tag name.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    result = get_agents_by_tag(**dict(tag_data))
    if not result:
        raise HTTPException(status_code=404, detail="Agents not found")
    return result

@app.post("/tags/get-tools-by-tag")
def read_tools_by_tag(tag_data: TagIdName, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    """
    Retrieves tools associated with a given tag ID or tag name.
    """
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    result = get_tools_by_tag(**dict(tag_data))
    if not result:
        raise HTTPException(status_code=404, detail="Tools not found")
    return result




# Document uploading

# Base directory for uploads
BASE_DIR = "user_uploads"


# Function to save uploaded files
def save_uploaded_file(uploaded_file: UploadFile, save_path: str):
    all_files = os.listdir(save_path)
    
    if uploaded_file.filename in all_files:
        raise HTTPException(status_code=400, detail="File already exists!")

    if ".." in save_path  or ":" in save_path:
        raise HTTPException(status_code=400, detail="Invalid Path File")

    file_location = os.path.join(save_path, re.sub(r'[^A-Za-z0-9_.-]', '_', uploaded_file.filename))
    if ".." in file_location or ":" in file_location:
        raise HTTPException(status_code=400, detail="Invalid Path File")
    if not file_location.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(status_code=400, detail="Invalid Path File")

    with open(file_location, "wb") as f:
        shutil.copyfileobj(uploaded_file.file, f)
    return file_location

# Function to generate file structure
def generate_file_structure(directory="user_uploads"):
    file_struct = {}
    for root, dirs, files in os.walk(directory):
        path_parts = root.split(os.sep)
        current_level = file_struct
        for part in path_parts:
            if part not in current_level:
                current_level[part] = {}
            current_level = current_level[part]
        if files:
            current_level["__files__"] = files
    return file_struct

@app.post("/files/user-uploads/upload-file/")
async def upload_file(file: UploadFile = File(...), subdirectory: str = "", session_id: str = Header(...),
    csrf_token: str = Header(...)):
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    if subdirectory.startswith("/") or subdirectory.startswith("\\"):
        subdirectory = subdirectory[1:]


    if ".." in subdirectory  or ":" in subdirectory:
        raise HTTPException(status_code=400, detail="Invalid Path File")

    save_path = os.path.join(BASE_DIR, subdirectory) if subdirectory else BASE_DIR
    
    # Before creating the directory, check if the save_path is valid and within the allowed directory
    abs_save_path = os.path.abspath(save_path)
    
    # Ensure that the absolute save path is inside the BASE_DIR and prevent directory traversal
    if not abs_save_path.startswith(os.path.abspath(BASE_DIR)):
        raise HTTPException(status_code=400, detail="Invalid Path File")
    
    if not os.path.exists(save_path):
        os.makedirs(save_path)
    file_location = save_uploaded_file(file, save_path)
    if isinstance(file_location, HTTPException):
        raise file_location

    return {"info": f"File '{file.filename}' saved at '{file_location}'"}


@app.get("/files/user-uploads/get-file-structure/")
async def get_file_structure():
    file_structure = generate_file_structure(BASE_DIR)
    return JSONResponse(content=file_structure)

@app.delete("/files/user-uploads/delete-file/")
async def delete_file(file_path: str):
    full_path = os.path.join(BASE_DIR, file_path)
    if os.path.exists(full_path):
        if os.path.isfile(full_path):
            os.remove(full_path)
            return {"info": f"File '{file_path}' deleted successfully."}
        else:
            raise HTTPException(status_code=400, detail="The specified path is a directory. Only files can be deleted.")
    else:
        raise HTTPException(status_code=404, detail="No such file or directory.")


class login_data(BaseModel):
    email_id : str
    password: str
    role: str

class registration_data(BaseModel):
    email_id : str
    password: str
    role: str
    user_name: str


class old_session_request(BaseModel):
    user_email: str
    agent_id: str 


   
@app.post("/login")
def login(data: login_data):
    conn = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM login_credential WHERE mail_id = %s", (data.email_id,))
    login_data = cursor.fetchone()

    conn.commit()
    conn.close()

    if login_data is None:
        return {"approval": False,
                "message": "User not found"}
    if bcrypt.checkpw(data.password.encode('utf-8'), login_data[2].encode('utf-8')):
        if login_data[3] == "Admin":
            pass
        elif login_data[3] == "Developer" and data.role == "Admin":
            return {"approval": False, "message": "You are not authorized to as Admin"}
        elif login_data[3] == "User" and data.role in ["Admin", "Developer"]:
            return {"approval": False, "message": f"You are not authorized to as {data.role}"}

        user_email_id = login_data[0]

        expire_token(user_id=user_email_id)
        session_id = f"{user_email_id}_{str(uuid.uuid4()).replace('-', '_')}"
        csrf_token = secrets.token_hex(32)

        register_csrf_token(session_id=session_id, csrf_token=csrf_token)

        return {
            "approval": True,
            "session_id": session_id,
            "csrf_token": csrf_token,
            "role": data.role,
            "username": login_data[1],
            "email": user_email_id,
            "message": "Login successful"
        }
    else:
        return {"approval": False, "message": "Incorrect password"}

@app.post("/protected_api")
def protected_api(
    session_id: str = Header(...),
    csrf_token: str = Header(...)
):
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error

    # Your protected logic here
    return {"message": "This is valid"}

@app.post("/registration")
def registration(data: registration_data):
    conn = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM login_credential WHERE mail_id = %s", (data.email_id,))
    login_data = cursor.fetchone()
    if login_data:
        conn.commit()
        conn.close()
        return {"approval": False, "message": "User already exists"}

    try:
        hashed_password = bcrypt.hashpw(data.password.encode('utf-8'), bcrypt.gensalt())
        cursor.execute('''
        INSERT INTO login_credential (mail_id, user_name, password, role)
        VALUES (%s, %s, %s, %s)
        ''', (data.email_id, data.user_name, hashed_password.decode('utf-8'), data.role)
        )

        conn.commit()
        conn.close()

        id = str(uuid.uuid4())
        return {"approval": True, "message": f"{data.user_name} registered successfully"}
    except Exception as e:
        conn.rollback()
        conn.close()
        return {"approval": False, "message": f"Error: {str(e)}"}
    


@app.get("/login_guest")
def login_guest():
    session_id = f"guest_{str(uuid.uuid4()).replace('-', '_')}"
    csrf_token = secrets.token_hex(32)
    register_csrf_token(session_id=session_id, csrf_token=csrf_token)

    return {
        "approval": True,
        "email": "test",
        "session_id": session_id,
        "csrf_token": csrf_token,
        "user_name": "Guest",
        "message": "Guest Login Successful"
    }



@app.post("/old-chats")
def get_old_chats(request: old_session_request, session_id: str = Header(...),
    csrf_token: str = Header(...)):
    error = verify_csrf_token(session_id, csrf_token)
    if error:
        return error
    conn = psycopg2.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    user_email = request.user_email
    agent_id = request.agent_id
    table_name = f'table_{agent_id.replace("-", "_")}'
    c = conn.cursor()
    try:
        c.execute(f"SELECT * FROM {table_name} WHERE session_id LIKE '{user_email}_%';")
    except:
        conn.close()
        return "no old chats found"
    data = c.fetchall()
    conn.close()
    result = {}
    for row in data:
        test_number = row[0]
        timestamp_start = row[1]
        timestamp_end = row[2]
        user_input = row[3]
        agent_response = row[4]

        if test_number not in result:
            result[test_number] = []

        result[test_number].append({
            "timestamp_start": timestamp_start,
            "timestamp_end": timestamp_end,
            "user_input": user_input,
            "agent_response": agent_response
        })

    return JSONResponse(content=result)

@app.get("/new_chat/{email}")
def new_chat(email:str):
    import uuid

    id = str(uuid.uuid4()).replace("-","_")
    session_id = email + "_" + id
    return session_id

@app.get('/download')
def download(filename:str, sub_dir_name:str=None):
    raise HTTPException(status_code=404, detail="This feature is not available yet.")


@app.get("/get-tools-by-pages/{page}")
def get_tools_by_pages(page: int = 1, limit : int = Query(20, ge=1)):
    """
    Retrieves tools from the PostgreSQL database with pagination.

    Parameters:
    ----------
    page : int
        The page number to retrieve (default is 1).
    page_size : int
        The number of items per page (default is 10).
 
    Returns:
    -------
    list
        A list of tools for the specified page.
    """
    tools = get_tools_by_page(page=page, limit=limit)
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found")
    return tools


@app.get("/get-agents-by-pages/{page}")
def get_agents_by_pages(page: int = 1, user_email: str= None, agent_type: str = None, limit: int = 10, is_admin: bool = True):
    """
    Retrieves agents from the PostgreSQL database with pagination.
 
    Parameters:
    ----------
    Pagination : Pagination
        The request body containing pagination details.
 
    Returns:
    -------
    list
        A list of agents for the specified page.
    """
    agents = get_agents_by_page(page=page, limit = limit, user_email_id=user_email, agentic_application_type=agent_type, is_admin=is_admin)
    if not agents:
        raise HTTPException(status_code=404, detail="No agents found")
    return agents
 
@app.get("/get-tools-by-search/{tool_name}")
def get_tools_by_search(tool_name):
    """
    Retrieves tools from the tool table in PostgreSQL.

    Args:
        tool_name (str): The name of the tool to search for.

    Returns:
        list: A list of tools from the tool table, represented as dictionaries.
    """
    try:
        # Connect to the PostgreSQL database
        db_params = {
            'dbname': DATABASE,
            'user': POSTGRESQL_USER,
            'password': POSTGRESQL_PASSWORD,
            'host': POSTGRESQL_HOST,
            'port': 5432
        }
        with psycopg2.connect(**db_params) as connection:
            with closing(connection.cursor()) as cursor:
                # Build and execute the SELECT query
                query = """
                    SELECT * 
                    FROM tool_table 
                    WHERE tool_name ILIKE %s 
                    ORDER BY created_on DESC;
                """
                cursor.execute(query, (f"{tool_name}%",))
                rows = cursor.fetchall()
                columns = [desc[0] for desc in cursor.description]

                # Convert rows into a list of dictionaries
                results_as_dicts = [dict(zip(columns, row)) for row in rows]
                for result in results_as_dicts:
                    result['tags'] = get_tags_by_tool(tool_id=result['tool_id'])
                return results_as_dicts

    except psycopg2.Error as e:
        return []

 
@app.get("/get-agents-by-search/{agent_name}")
def get_agents_by_search(agentic_application_type=None, agent_table_name="agent_table", agent_name : str = None):
    try:
        # Connect to the PostgreSQL database
        db_params = {
            'dbname': DATABASE,
            'user': POSTGRESQL_USER,
            'password': POSTGRESQL_PASSWORD,
            'host': POSTGRESQL_HOST,
            'port': 5432
        }
        with psycopg2.connect(**db_params) as connection:
            with closing(connection.cursor()) as cursor:
                # Build the query based on whether a filter is provided
                if agentic_application_type:
                    if isinstance(agentic_application_type, str):
                        agentic_application_type = [agentic_application_type]

                    placeholders = ', '.join(['%s'] * len(agentic_application_type))
                    query = f"""
                        SELECT *
                        FROM {agent_table_name}
                        WHERE agentic_application_type IN ({placeholders})
                        ORDER BY created_on DESC
                    """
                    parameters = tuple(agentic_application_type)
                else:
                    query = f"SELECT * FROM {agent_table_name} WHERE agentic_application_name ILIKE %s ORDER BY created_on DESC;"
                    parameters = (f"{agent_name}%",)

                # Execute the query
                cursor.execute(query, parameters)
                rows = cursor.fetchall()

                # Fetch column names to convert results into a list of dictionaries
                columns = [desc[0] for desc in cursor.description]
                results_as_dicts = [dict(zip(columns, row)) for row in rows]
                for result in results_as_dicts:
                    result['tags'] = get_tags_by_agent(agent_id=result['agentic_application_id'])
                return results_as_dicts

    except psycopg2.Error as e:
        return []

