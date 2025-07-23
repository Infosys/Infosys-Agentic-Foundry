# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import re
import os
import ast
import shutil
import asyncpg
import asyncio
import bcrypt
import uuid
import secrets
import warnings
from dotenv import load_dotenv

from typing import List, Dict, Optional, Union
from fastapi import FastAPI, UploadFile, File, HTTPException, Request, WebSocket, WebSocketDisconnect, Query, BackgroundTasks
from pathlib import Path
from fastapi_ws_router import WSRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.encoders import jsonable_encoder
from contextlib import asynccontextmanager
from contextlib import closing
from pydantic import BaseModel
from phoenix.otel import register
from phoenix.trace import using_project
from inference_planner_meta import meta_agent_with_planner_inference
from src.agent_templates.meta_agent_with_planner_onboarding import onboard_meta_agent_with_planner
from tool_validation import graph
from src.models.model import load_model
from src.agent_templates.react_agent_onboarding import react_system_prompt_gen_func
from inference import PrevSessionRequest, retrive_previous_conversation, agent_inference
from replanner_multi_agent_inference import human_in_the_loop_replanner_inference, ReplannerAgentInferenceRequest
from src.utils.secrets_handler import current_user_email
from replanner_planner_executor import human_in_the_loop_replanner_inference_pe, ReplannerAgentInferenceRequest
from typing import Literal
from inference_meta import meta_agent_inference
#from ainference import (aagent_inference)
from database_creation import initialize_tables
from database_manager import (check_and_create_databases,
    meta_agent_onboarding, meta_agent_with_planner_onboarding, update_agent_by_id_meta, delete_agent_by_id, get_agents_by_id, get_tools_by_id,
    assign_general_tag_to_untagged_items, get_tags_by_id_or_name, insert_into_tool_table, get_tools,
    update_tool_by_id, extract_tools_using_tools_id, generate_tool_prompt,delete_tools_by_id,
    planner_executor_critic_builder, worker_agents_config_prompt, meta_agent_system_prompt_gen_func,
    react_agent_onboarding, react_multi_agent_onboarding, get_agents, get_agents_by_id_studio, update_agent_by_id,
    update_latest_query_response_with_tag, insert_into_tags_table, get_tags, update_tag_name_by_id_or_name,
    delete_tag_by_id_or_name, get_tags_by_agent, get_tags_by_tool, get_agents_by_tag, get_tools_by_tag,
    delete_chat_history_by_session_id, get_all_chat_sessions, insert_into_feedback_table,
    get_approvals, get_approval_agents, update_feedback_response, get_response_data, get_tools_by_page, get_agents_by_page,
    react_multi_pe_agent_onboarding,react_critic_agent_onboarding,
    get_agents_details_for_chat, get_evaluation_data_by_agent_names, get_agent_metrics_by_agent_names,
    get_tool_metrics_by_agent_names, get_tool_tags_from_mapping_as_dict, get_agent_tags_from_mapping_as_dict,restore_recycle_agent_by_id,
    restore_recycle_tool_by_id,delete_recycle_agent_by_id,delete_recycle_tool_by_id, get_tool_data
)

from evaluation_metrics import process_unprocessed_evaluations
from telemetry_wrapper import logger as log, update_session_context
import asyncio
import sys
import tempfile
import json
from datetime import datetime

from src.utils.secrets_handler import (
    setup_secrets_manager, 
    get_user_secrets, 
    set_user_secret, 
    delete_user_secret, 
    list_user_secrets, 
    get_user_secrets_dict,
    current_user_email
)

load_dotenv()
task_tracker: dict[str, asyncio.Task] = {}
DB_URI=os.getenv("POSTGRESQL_DATABASE_URL", "")
POSTGRESQL_HOST = os.getenv("POSTGRESQL_HOST", "")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER", "")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD", "")
DATABASE = os.getenv("DATABASE", "")

DB_URI = os.getenv("POSTGRESQL_DATABASE_URL", "")
# Set Phoenix collector endpoint
os.environ["PHOENIX_COLLECTOR_ENDPOINT"] = os.getenv("PHOENIX_COLLECTOR_ENDPOINT")
os.environ["PHOENIX_GRPC_PORT"] = os.getenv("PHOENIX_GRPC_PORT",'50051')
os.environ["PHOENIX_SQL_DATABASE_URL"] = os.getenv("PHOENIX_SQL_DATABASE_URL")

# os.environ["LANGSMITH_TRACING"]="true"
os.environ["LANGCHAIN_TRACING_V2"] = "true"
os.environ["LANGSMITH_ENDPOINT"]="https://api.smith.langchain.com"
os.environ["LANGSMITH_API_KEY"]="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"
os.environ["LANGSMITH_PROJECT"]="meta agent"
os.environ["LANGCHAIN_CALLBACKS_BACKGROUND"] = "true"

if sys.platform.startswith("win"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())



@asynccontextmanager
async def lifespan(app: FastAPI):
    await check_and_create_databases()
    await initialize_tables()
    await assign_general_tag_to_untagged_items()
    yield

app = FastAPI(lifespan=lifespan)
router = WSRouter()


# Configure CORS
origins = [
    "",  # Add your frontend IP address
    "",  # Add you frontend Ip with port number being
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
    prev_response: Dict = None# Previous response from the agent
    feedback: str = "" # Feedback from the user
    reset_conversation: bool = False# If true need to reset the conversation
    interrupt_flag:bool=False

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

class ApprovalRequest(BaseModel):
    response_id: str
    query: str
    old_final_response: str
    old_steps: str
    old_response: str
    feedback: str
    new_final_response: str
    new_steps: str
    approved: bool


# Secrets Management Models
class SecretCreateRequest(BaseModel):
    user_email: str
    secret_name: str
    secret_value: str

class SecretUpdateRequest(BaseModel):
    user_email: str
    secret_name: str
    secret_value: str

class SecretDeleteRequest(BaseModel):
    user_email: str
    secret_name: str

class SecretGetRequest(BaseModel):
    user_email: str
    secret_name: Optional[str] = None
    secret_names: Optional[List[str]] = None

class SecretListRequest(BaseModel):
    user_email: str

def extract_fn_name(code_str: str):
    """
        Using the ast module syntax check the function and
        return the function name in the code snippet.
    """

    try:
        parsed_code = ast.parse(code_str)
    except Exception as e:
        log.error(f"Tool Onboarding Failed: Function parsing error.\n{e}")
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
        log.error(f"Tool Onboarding Failed: Syntax error in function definition.\n{e}")
        err = f"There is a syntax mistake in it: {e}"
        return ""


def get_agents_by_ids_studio(agentic_application_ids: List[str]) -> List[dict]:
    agents = []
    for agent_id in agentic_application_ids:
        # Simulated data for agents
        agents.append({"agent_id": agent_id, "name": f"Agent {agent_id}"})
    log.debug(f"Agents retrieved successfully: {agents}")
    return agents



@app.post('/evaluate')
async def evaluate(evaluating_model1,evaluating_model2):
    register(
            project_name='add-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('evaluation-metrics'):
        return await process_unprocessed_evaluations(model1=evaluating_model1,model2=evaluating_model2)


 
def parse_agent_names(agent_input: Optional[List[str]]) -> Optional[List[str]]:
    if not agent_input:
        return None
 
    if len(agent_input) == 1:
        raw = agent_input[0]
        try:
            # Try parsing stringified list format: "['Agent1','Agent2']"
            parsed = ast.literal_eval(raw)
            if isinstance(parsed, list):
                return [str(x).strip() for x in parsed]
        except Exception:
            if ',' in raw:
                return [x.strip() for x in raw.split(',')]
 
    return agent_input


@app.get("/evaluations")
async def get_evaluation_data(
    agent_names: Optional[List[str]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100)
):
    parsed_names = parse_agent_names(agent_names)
    data = await get_evaluation_data_by_agent_names(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No evaluation data found")
    return data  # Just return the data, no pagination metadata


@app.get("/agent-metrics")
async def get_agent_metrics(
    agent_names: Optional[List[str]] = Query(default=None),
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, ge=1, le=100)
):
    parsed_names = parse_agent_names(agent_names)
    data = await get_agent_metrics_by_agent_names(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No agent metrics found")   
    return data


@app.get("/tool-metrics")
async def get_tool_metrics(
    agent_names: Optional[List[str]] = Query(default=None),
    page: int = Query(default=1, ge=1, description="Page number (starts from 1)"),
    limit: int = Query(default=10, ge=1, le=100, description="Number of records per page (max 100)")
):
    parsed_names = parse_agent_names(agent_names)
    data = await get_tool_metrics_by_agent_names(parsed_names, page, limit)
    if not data:
        raise HTTPException(status_code=404, detail="No tool metrics found")  
    return data


@app.get('/get-models')
async def get_available_models():
    try:
        # Use 'with' for automatic cleanup
        connection = await asyncpg.connect(DB_URI)
        rows = await connection.fetch("SELECT model_name FROM models;")
        data = [row["model_name"] for row in rows]  # asyncpg returns a list of Record objects
        log.debug(f"Models retrieved successfully: {data}")
        return JSONResponse(content={"models": data})

    except asyncpg.PostgresError as e:
        log.error(f"Database error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    except Exception as e:
        # Handle other unforeseen errors
        log.error(f"Unexpected error while fetching models: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An error occurred: {str(e)}")


@app.get('/get-version')
def get_version():
    with open(os.path.join(os.path.dirname(__file__), 'VERSION')) as f:
        return f.read().strip()


@app.post("/add-tool")
async def add_tool(tool_data: ToolData):
    """
    Adds a new tool to the tool table.

    Parameters:
    ----------
    tool_data : ToolData
        The data of the tool to be added.

    Returns:
    -------
    dict
        A dictionary containing the status of the operation.
        If the tool name is successfully extracted and inserted
        into the tool table, the status will indicate success.
        Otherwise, it will provide an error message.

    The status dictionary contains:
    - message : str
        A message indicating the result of the operation.
    - tool_id : str
        The ID of the tool (empty if not created).
    - is_created : bool
        Indicates whether the tool was successfully created.
    """
    update_session_context(model_used=tool_data.model_name,
                            tags=tool_data.tag_ids,)
    register(
            project_name='add-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('add-tool'):
        tool_list = dict(tool_data)
        tool_list["tool_name"] = extract_fn_name(code_str=tool_list["code_snippet"])
        if tool_list["tool_name"]:
            update_session_context(tool_name=tool_list["tool_name"])
            if not tool_list.get("tag_ids", None):
                tag_data = await get_tags_by_id_or_name(tag_name="General")
                tool_list['tag_ids'] = tag_data.get("tag_id", None)
    #         initial_state = {
    #             "code": tool_list["code_snippet"],
    #             "validation_case1": None,
    #             "feedback_case1": None,
    #             "validation_case3": None,
    #             "feedback_case3": None,
    #             "validation_case4": None,
    #             "feedback_case4": None,
    #             "validation_case5": None,
    #             "feedback_case5": None,
    #             "validation_case6": None,
    #             "feedback_case6": None,
    #             "validation_case7": None,
    #             "feedback_case7": None
    #         }

    #         workflow_result = await graph.ainvoke(input=initial_state)
    #         validation_cases = [
    #             "validation_case1", "validation_case3",
    #             "validation_case4", "validation_case5","validation_case6", "validation_case7"
    #         ]

    #         failed_feedback = {}
    #         for case in validation_cases:
    #             if not workflow_result.get(case):
    #                 feedback_key = case.replace("validation_", "feedback_")
    #                 failed_feedback[case] = workflow_result.get(feedback_key)
    #         if not failed_feedback or force_add:
            status = await insert_into_tool_table(tool_list)
    #         else:
    #             verify=list(failed_feedback.values())
    #             status = {
    #                 "message": ("Verification failed: "+str(verify)),
    #                 "tool_id": "",
    #                 "is_created": False
    #             }
        else:
            status = {
                "message": (
                    "The code is having invalid syntax or "
                    "you forgot adding data types to the parameters"
                ),
                "tool_id": "",
                "is_created": False
            }
        log.debug(f"Tool creation status: {status}")

    update_session_context(model_used='Unassigned', 
                            tags='Unassigned',
                            tool_id='Unassigned',
                            tool_name='Unassigned',)
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
    update_session_context(tool_id=tool_id)
    tool = await get_tools_by_id(tool_id=tool_id)
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
    update_session_context(tool_id='Unassigned')
    return tool


@app.put("/update-tool/{tool_id}")
async def update_tool_endpoint(tool_id: str, request: UpdateToolRequest):
    """
    Updates a tool by its ID.

    Parameters:
    ----------
    id : str
        The ID of the tool to be updated.
    request : UpdateToolRequest
        The request body containing the update details.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    update_session_context(tool_id=tool_id,tags=request.updated_tag_id_list,model_used=request.model_name,
                            action_type='update',action_on='tool',previous_value=get_tools_by_id(tool_id=tool_id))
        
    register(
            project_name='update-tool',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('update-tool'):
        response = await update_tool_by_id(
            model_name=request.model_name,
            user_email_id=request.user_email_id,
            is_admin=request.is_admin,
            tool_id_to_modify=tool_id,
            tool_description=request.tool_description,
            code_snippet=request.code_snippet,
            updated_tag_id_list=request.updated_tag_id_list
        )
    if not response["is_update"]:
        raise HTTPException(status_code=400, detail=response["status_message"])
    update_session_context(new_value=get_tools_by_id(tool_id=tool_id))
    log.debug(f"Tool update status: {response}")
    update_session_context(tool_id='Unassigned',tags='Unassigned',model_used='Unassigned',action_type='Unassigned',
                        action_on='Unassigned',previous_value='Unassigned',new_value='Unassigned')
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
    update_session_context(tool_id=tool_id,action_on='tool', action_type='delete',previous_value=get_tools_by_id(tool_id=tool_id))
    status = await delete_tools_by_id(user_email_id=request.user_email_id,
                                is_admin=request.is_admin,
                                tool_id=tool_id)
    update_session_context(tool_id='Unassigned',action_on='Unassigned', action_type='Unassigned',previous_value='Unassigned')
    return status


@app.post("/react-agent/onboard-agent")
async def onboard_react_agent(request: AgentOnboardingRequest):
    """
    Onboards a new React agent.

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
    update_session_context(model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="react",
                           tools_binded=request.tools_id)
    try:
        register(
            project_name='onboard-react-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-react-agent'):
            if not request.tag_ids:
                tag_data = await get_tags_by_id_or_name(tag_name="General")
                request.tag_ids = tag_data.get("tag_id", None)
            update_session_context(tags=request.tag_ids)
                # can't use get directly with await function call.
            result = await react_agent_onboarding(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_email_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}"
        ) from e

@app.post("/react-critic-agent/onboard-agent")
async def onboard_react_agent(request: AgentOnboardingRequest):
    """
    Onboards a new React agent.

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
    update_session_context(model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="react",
                           tools_binded=request.tools_id)
    try:
        register(
            project_name='onboard-react-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-react-agent'):
            if not request.tag_ids:
                tag_data = await get_tags_by_id_or_name(tag_name="General")
                request.tag_ids = tag_data.get("tag_id", None)
            update_session_context(tags=request.tag_ids)
                # can't use get directly with await function call.
            result = await react_critic_agent_onboarding(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_email_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}"
        ) from e

@app.post("/planner-executor-critic-agent/onboard-agents")
async def onboard_pec_agent(request: AgentOnboardingRequest):
    """
    Onboards multiple agents in one go.
eters:
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
    update_session_context(model_used=request.model_name,
                            agent_name=request.agent_name,
                            agent_type="planner-executor-critic",
                            tools_binded=request.tools_id)
    try:
        register(
            project_name='onboard-pec-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-pec-agent'):
            if not request.tag_ids:
                tag_data=await get_tags_by_id_or_name(tag_name="General")
                request.tag_ids = tag_data.get("tag_id", None)
            update_session_context(tags=request.tag_ids)
            result = await react_multi_agent_onboarding(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_email_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}") from e


@app.post("/planner-executor-agent/onboard-agents")
async def onboard_pe_agent(request: AgentOnboardingRequest):
    """
    Onboards multiple agents in one go.
eters:
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
    update_session_context(model_used=request.model_name,
                            agent_name=request.agent_name,
                            agent_type="planner-executor",
                            tools_binded=request.tools_id)
    try:
        register(
            project_name='onboard-pe-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-pe-agent'):
            if not request.tag_ids:
                tag_data=await get_tags_by_id_or_name(tag_name="General")
                request.tag_ids = tag_data.get("tag_id", None)
            update_session_context(tags=request.tag_ids)
            result = await react_multi_pe_agent_onboarding(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                tools_id=request.tools_id,
                user_email_id=request.email_id,
                tag_ids=request.tag_ids
            )
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            tools_binded='Unassigned',
                            tags='Unassigned')
        return {"status": "success", "result": result}
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error during agent onboarding: {str(e)}") from e
        

# Define the API endpoint for onboarding a meta-agent
@app.post("/meta-agent/onboard-agents")
async def onboard_meta_agent(request: AgentOnboardingRequest):
    """
    Onboards a meta-agent.

    Parameters:
    -------
    request : MetaAgentOnboardingRequest
        The request body containing details for onboarding the meta-agent.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with error details.
    """
    update_session_context(model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="meta-agent",
                           agents_binded=request.tools_id)
    try:
        register(
            project_name='onboard-meta-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-meta-agent'):
        # Call the onboarding function
            if not request.tag_ids:
                tag_data= await get_tags_by_id_or_name(tag_name="General")
                request.tag_ids = tag_data.get("tag_id", None)
            update_session_context(tags=request.tag_ids)
            result = await meta_agent_onboarding(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                agentic_app_ids=request.tools_id,
                user_email_id=request.email_id,
                tag_ids=request.tag_ids
            )
            
        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            agents_binded='Unassigned',
                            tags='Unassigned')
        # Return success response
        return {"status": "success", "result": result}

    except Exception as e:
        # Handle any errors and provide an informative response
        raise HTTPException(
            status_code=500,
            detail=f"Error during meta-agent onboarding: {str(e)}"
        ) from e


# Define the API endpoint for onboarding a planner-meta-agent
@app.post("/planner-meta-agent/onboard-agents")
async def onboard_planner_meta_agent(request: AgentOnboardingRequest):
    """
    Onboards a planner-meta-agent.

    Parameters:
    -------
    request : MetaAgentOnboardingRequest
        The request body containing details for onboarding the meta-agent.

    Returns:
    -------
    dict
        A dictionary containing the status of the onboarding operation.
        If an error occurs, raises an HTTPException with error details.
    """
    update_session_context(model_used=request.model_name,
                           agent_name=request.agent_name,
                           agent_type="planner-meta-agent",
                           agents_binded=request.tools_id)
    try:
        register(
            project_name='onboard-planner-meta-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
        with using_project('onboard-planner-meta-agent'):
        # Call the onboarding function
            if not request.tag_ids:
                tag_data= await get_tags_by_id_or_name(tag_name="General")
                request.tag_ids = tag_data.get("tag_id", None)
            update_session_context(tags=request.tag_ids)

            result = await meta_agent_with_planner_onboarding(
                agent_name=request.agent_name,
                agent_goal=request.agent_goal,
                workflow_description=request.workflow_description,
                model_name=request.model_name,
                agentic_app_ids=request.tools_id,
                user_email_id=request.email_id,
                tag_ids=request.tag_ids
            )

        update_session_context(model_used='Unassigned',
                            agent_name='Unassigned',
                            agent_id='Unassigned',
                            agent_type='Unassigned',
                            agents_binded='Unassigned',
                            tags='Unassigned')
        # Return success response
        return {"status": "success", "result": result}

    except Exception as e:
        # Handle any errors and provide an informative response
        raise HTTPException(
            status_code=500,
            detail=f"Error during planner-meta-agent onboarding: {str(e)}"
        ) from e



@app.get("/get-agents/")
async def get_agents_endpoint(agentic_application_type:  Optional[Union[str, List[str]]] = None):
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
        response = await get_agents(agentic_application_type)

        if not response:
            raise HTTPException(status_code=404, detail="No agents found")

        return response

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving agents: {str(e)}")


@app.get("/get-agent/{agent_id}")
async def get_agent_by_id_endpoint(agent_id: str):
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
    update_session_context(agent_id=agent_id)
    response = await get_agents_by_id(
        agentic_application_id=agent_id
    )
  
    if not response:
        raise HTTPException(status_code=404, detail="No agents found")
    update_session_context(agent_id='Unassigned')
    return response


@app.get("/agent-details/{agent_id}")
async def get_agent_details(agent_id: str):
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
    update_session_context(agent_id=agent_id)
  
    response = await get_agents_by_id_studio(
        agentic_application_id=agent_id
    )
    if not response:
        raise HTTPException(status_code=404, detail="Agent not found")
    update_session_context(agent_id='Unassigned')
    return response

@app.put("/react-critic-agent/update-agent")
@app.put("/planner-executor-critic-agent/update-agent")
@app.put("/planner-executor-agent/update-agent")
@app.put("/react-agent/update-agent")
async def update_agent(request: UpdateAgentRequest):
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
    update_session_context(model_used=request.model_name,
                           agent_id=request.agentic_application_id_to_modify,
                           agent_name=request.agentic_application_name_to_modify,
                           agent_type=request.agentic_application_type,
                           tools_binded=request.tools_id_to_remove,
                           tags=request.updated_tag_id_list,
                           action_type='update',
                           action_on='agent',
                           previous_value=get_agents_by_id(agentic_application_id=request.agentic_application_id_to_modify))
    register(
            project_name='update-react-pec-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('update-react-pec-agent'):
        response = await update_agent_by_id(
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
        update_session_context(new_value=get_agents_by_id(agentic_application_id=request.agentic_application_id_to_modify))
    log.debug(f"Agent update status: {response}")
    update_session_context(model_used='Unassigned', agent_id='Unassigned', agent_name='Unassigned',
                        agent_type='Unassigned', tools_binded='Unassigned', tags='Unassigned', 
                        action_on='Unassigned',action_type='Unassigned',previous_value='Unassigned',new_value='Unassigned')
    return response


@app.put("/planner-meta-agent/update-agent")
@app.put("/meta-agent/update-agent")
async def update_agent_meta(request: UpdateAgentRequest):
    """
    Updates a meta-agent by its ID.

    Parameters:
    ----------
    request : UpdateAgentRequest
        The request body containing the update details for a meta-agent.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    update_session_context(model_used=request.model_name,
                           agent_id=request.agentic_application_id_to_modify,
                           agent_name=request.agentic_application_name_to_modify,
                           agent_type=request.agentic_application_type,
                           agents_binded=request.tools_id_to_remove,
                           tags=request.updated_tag_id_list,
                           action_type='update',
                           action_on='agent',
                           previous_value=get_agents_by_id(agentic_application_id=request.agentic_application_id_to_modify))
    register(
            project_name='update-meta-agent',
            auto_instrument=True,
            set_global_tracer_provider=False,
            batch=True
        )
    with using_project('update-meta-agent'):
        # Call the update function with parameters coming from the request
        response = await update_agent_by_id_meta(
            model_name=request.model_name,
            user_email_id=request.user_email_id,
            agentic_application_type=request.agentic_application_type,
            is_admin=request.is_admin,
            agentic_application_id_to_modify=request.agentic_application_id_to_modify,
            agentic_application_name_to_modify=request.agentic_application_name_to_modify,
            agentic_application_description=request.agentic_application_description,
            agentic_application_workflow_description=request.agentic_application_workflow_description,
            system_prompt=request.system_prompt,
            worker_agents_id_to_add=request.tools_id_to_add,
            worker_agents_id_to_remove=request.tools_id_to_remove,
            updated_tag_id_list=request.updated_tag_id_list
        )

        # Check if the update was successful
        if not response["is_update"]:
            # If the update was unsuccessful, raise an HTTPException with status code 400
            raise HTTPException(status_code=400, detail=response["status_message"])
        update_session_context(new_value=get_agents_by_id(agentic_application_id=request.agentic_application_id_to_modify))
    log.debug(f"Meta-agent update status: {response}")
    update_session_context(model_used='Unassigned',
                           agent_id='Unassigned',
                           agent_name='Unassigned',
                           agent_type='Unassigned',
                           agents_binded='Unassigned',
                           tags='Unassigned',
                           action_on='Unassigned',
                           action_type='Unassigned',
                           previous_value='Unassigned',
                           new_value='Unassigned')
    # If update is successful, return the response with the updated data
    return response




@app.delete("/react-agent/delete-agent/{agent_id}")
@app.delete("/delete-agent/{agent_id}")
async def delete_agent(agent_id: str, request: DeleteAgentRequest):
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
    update_session_context(agent_id=agent_id,
                           action_on='agent',
                           action_type='delete',
                           previous_value=get_agents_by_id(agentic_application_id=agent_id))
    response = await delete_agent_by_id(
        user_email_id=request.user_email_id,
        is_admin=request.is_admin,
        agentic_application_id=agent_id
    )
    if not response["is_delete"]:
        raise HTTPException(status_code=400, detail=response["status_message"])
    update_session_context(agent_id='Unassigned',action_on='Unassigned', action_type='Unassigned',previous_value='Unassigned')
    return response

@app.post("/meta-agent/get-chat-history")
@app.post("/react-agent/get-chat-history")
@app.post("/get-chat-history")
async def get_history(request: PrevSessionRequest):
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
    update_session_context(session_id=request.session_id,agent_id=request.agent_id)
    return await retrive_previous_conversation(request=request)


@app.post("/get-query-response")
async def get_react_and_pec_and_pe_rc_agent_response(request: AgentInferenceRequest):
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
    session_id = request.session_id
    log.info(f"[{session_id}] Received new request.")
    current_user_email.set(request.session_id.split("_")[0])
    # Cancel existing task for the session if it exists
    existing_task = task_tracker.get(session_id)
    if existing_task and not existing_task.done():
        log.info(f"[{session_id}] Cancelling existing task...")
        existing_task.cancel()
        try:
            await existing_task
        except asyncio.CancelledError:
            log.warning(f"[{session_id}] Previous task cancelled.")

    # Update context to "processing"
    update_session_context(
        agent_id=request.agentic_application_id,
        session_id=session_id,
        model_used=request.model_name,
        user_query=request.query,
        response="Processing..."
    )

    log.info(f"[{session_id}] Starting agent inference...")

    # Define and create the inference task
    async def do_inference():
        try:
            result = await agent_inference(request)
            log.info(f"[{session_id}] Inference completed.")
            return result
        except asyncio.CancelledError:
            log.warning(f"[{session_id}] Task was cancelled during execution.")
            raise

    new_task = asyncio.create_task(do_inference())
    task_tracker[session_id] = new_task

    try:
        response = await new_task
    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail="Request was cancelled")

    # Clear the context
    update_session_context(
        agent_id="Unassigned",
        session_id="Unassigned",
        model_used="Unassigned",
        user_query="Unassigned",
        response="Unassigned"
    )

    # Optionally: clean up finished task
    if session_id in task_tracker and task_tracker[session_id].done():
        del task_tracker[session_id]
        log.info(f"[{session_id}] Task cleaned up from tracker.")

    return response

@app.post("/react-agent/get-feedback-response/{feedback}")
async def get_react_feedback_response(feedback: str, request: AgentInferenceRequest):
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
    try:
        current_user_email.set(request.session_id.split("_")[0])
        query = request.query
        if feedback == "like":
            update_status = await update_latest_query_response_with_tag(agentic_application_id=request.agentic_application_id, session_id=request.session_id)
            if update_status is True:
                return {"message": "Thanks for the like! We're glad you found the response helpful. If you have any more questions or need further assistance, feel free to ask!"}
            elif update_status is False:
                return {"message": "Your like has been removed. If you have any more questions or need further assistance, feel free to ask!"}
            else:
                return {"message": "Sorry, we couldn't update your request at the moment. Please try again later."}
        elif feedback == "regenerate":
            request.query = "[regenerate:][:regenerate]"
        elif feedback == "feedback":
            request.query = f"[feedback:]{request.feedback}[:feedback]"
        else:
            return {"error": "Invalid Path!"}
        
        user_feedback = request.feedback
        request.feedback=None

        request.reset_conversation = False

        response = await agent_inference(request)
        try:
            final_response = response["response"]
            steps = response["executor_messages"][-1]["agent_steps"]
            old_response = request.prev_response["response"]
            old_steps = request.prev_response["executor_messages"][-1]["agent_steps"]
            
            await insert_into_feedback_table(
                agent_id=request.agentic_application_id.replace("-","_"),
                query=query,
                old_final_response= old_response,
                old_steps=old_steps,
                new_final_response=final_response,
                feedback=user_feedback, 
                new_steps=steps)
        except Exception as e:
            response["error"] = f"An error occurred while processing the response: {str(e)}"
        
        update_session_context(agent_id='Unassigned',session_id='Unassigned',
                           model_used='Unassigned',user_query='Unassigned',response='Unassigned')
        return response
    except Exception as e:
        return {"error": f"An error occurred while processing the request: {str(e)}"}


@app.get("/get-approvals-list")
async def get_approvals_list():
    """
    Retrieves the list of approvals.

    Returns:
    -------
    list
        A list of approvals. If no approvals are found, raises an HTTPException with status code 404.
    """
    approvals = await get_approval_agents()
    if not approvals:
        raise HTTPException(status_code=404, detail="No approvals found")
    return approvals

@app.get("/get-responses-data/{response_id}")
async def get_responses_data_endpoint(response_id):
    """
    Retrieves the list of approvals.

    Returns:
    -------
    list
        A list of approvals. If no approvals are found, raises an HTTPException with status code 404.
    """
    approvals = await get_response_data(response_id=response_id)
    if not approvals:
        raise HTTPException(status_code=404, detail="No Response found")
    return approvals

@app.get("/get-approvals-by-id/{agent_id}")
async def get_approval_by_id(agent_id: str):
    """
    Retrieves an approval by its ID.

    Parameters:
    ----------
    approval_id : str
        The ID of the approval to be retrieved.

    Returns:
    -------
    dict
        A dictionary containing the approval details.
        If no approval is found, raises an HTTPException with status code 404.
    """
    approval = await get_approvals(agent_id=agent_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval

@app.post("/update-approval-response")
async def update_approval_response(request: ApprovalRequest):
    """
    Updates the approval response.

    Parameters:
    ----------
    request : ApprovalRequest
        The request body containing the approval details.

    Returns:
    -------
    dict
        A dictionary containing the status of the update operation.
        If the update is unsuccessful, raises an HTTPException with
        status code 400 and the status message.
    """
    response = await update_feedback_response(
        response_id=request.response_id,
        data_dictionary={
        "query": request.query,
        "old_final_response": request.old_final_response,
        "old_steps": request.old_steps,
        "old_response": request.old_response,
        "feedback": request.feedback,
        "new_final_response": request.new_final_response,
        "new_steps": request.new_steps,
        "approved": request.approved
        }
    )
    if not response["is_update"]:
        raise HTTPException(status_code=400, detail=response["status_message"])
    return response

@app.post("/meta-agent/get-query-response")
async def get_meta_agent_response(request: AgentInferenceRequest):
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
    update_session_context(agent_id=request.agentic_application_id,
                            session_id=request.session_id,
                            model_used=request.model_name,
                            user_query=request.query,
                            response='Processing...')
    
    current_user_email.set(request.session_id.split("_")[0])
    response = await meta_agent_inference(request)
    update_session_context(agent_id='Unassigned',session_id='Unassigned',
                           model_used='Unassigned',user_query='Unassigned',response='Unassigned')
    return response

@app.post("/planner-meta-agent/get-query-response")
async def get_planner_meta_agent_response(request: AgentInferenceRequest):
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
    update_session_context(agent_id=request.agentic_application_id,
                            session_id=request.session_id,
                            model_used=request.model_name,
                            user_query=request.query,
                            response='Processing...')
    current_user_email.set(request.session_id.split("_")[0])
    response = await meta_agent_with_planner_inference(request)
    update_session_context(agent_id='Unassigned',session_id='Unassigned',
                           model_used='Unassigned',user_query='Unassigned',response='Unassigned')
    return response


@app.delete("/react-agent/clear-chat-history")
@app.delete("/clear-chat-history")
async def clear_chat_history(request: PrevSessionRequest):
    return await delete_chat_history_by_session_id(agentic_application_id=request.agent_id, session_id=request.session_id)

@app.get("/react-agent/get-chat-sessions")
async def get_chat_sessions():
    """
    Retrieves all tools from the tool table.

    Returns:
    -------
    list
        A list of all thread ids. If not found, raises an HTTPException with status code 404.
    """
    sessions= await get_all_chat_sessions()
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
    update_session_context(session_id=session)
    return session



@app.post("/planner-executor-agent/get-query-response-hitl-replanner")
async def generate_response_replanner_executor_critic_agent_main(request: ReplannerAgentInferenceRequest):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (ReplannerAgentInferenceRequest): The request object containing the query, session ID, and other parameters.

    Returns:
        JSONResponse: A JSON response containing the agent's response and state.

    Raises:
        HTTPException: If an error occurs during processing.
    """
    query = request.query
    response = {}
    try:
        current_user_email.set(request.session_id.split("_")[0])
        response =  await human_in_the_loop_replanner_inference_pe(request)
        final_response = "\n".join(i for i in response["plan"])
        steps = ""
        old_response = "\n".join(i for i in request.prev_response["plan"])
        old_steps = ""
        await insert_into_feedback_table(
        agent_id=request.agentic_application_id.replace("-","_"),
        query=query,
        old_final_response= old_response,
        old_steps=old_steps,
        new_final_response=final_response,
        feedback=request.feedback, 
        new_steps=steps)
    except Exception as e:
        response["error"] = f"An error occurred while processing the response: {str(e)}"
        # print(request.prev_response)
    
    
    return response


@app.post("/planner-executor-critic-agent/get-query-response-hitl-replanner")
async def generate_response_replanner_executor_critic_agent_main(request: ReplannerAgentInferenceRequest):
    """
    Handles the inference request for the Planner-Executor-Critic-replanner agent.

    Args:
        request (ReplannerAgentInferenceRequest): The request object containing the query, session ID, and other parameters.

    Returns:
        JSONResponse: A JSON response containing the agent's response and state.

    Raises:
        HTTPException: If an error occurs during processing.
    """
    query = request.query
    response = {}
    try:
        current_user_email.set(request.session_id.split("_")[0])
        response =  await human_in_the_loop_replanner_inference(request)
        final_response = "\n".join(i for i in response["plan"])
        steps = ""
        old_response = "\n".join(i for i in request.prev_response["plan"])
        old_steps = ""
        await insert_into_feedback_table(
        agent_id=request.agentic_application_id.replace("-","_"),
        query=query,
        old_final_response= old_response,
        old_steps=old_steps,
        new_final_response=final_response,
        feedback=request.feedback, 
        new_steps=steps)
    except Exception as e:
        response["error"] = f"An error occurred while processing the response: {str(e)}"
    
    
    return response





@app.post("/tags/create-tag")
async def create_tag(tag_data: TagData):
    """
    Inserts data into the tags table.
    """
    result = await insert_into_tags_table(dict(tag_data))
    return result

@app.get("/tags/get-available-tags")
async def get_available_tags():
    """
    Retrieves tags from the tags table.
    """
    return await get_tags()

@app.get("/tags/get-tag/{tag_id}")
async def read_tag_by_id(tag_id: str):
    """
    Retrieves tags from the database based on provided parameters.
    """
    result = await get_tags_by_id_or_name(tag_id=tag_id)
    if not result:
        raise HTTPException(status_code=404, detail="Tag not found")
    return result

@app.put("/tags/update-tag")
async def update_tag(update_data: UpdateTagData):
    """
    Updates the tag name in the tags table if the given tag ID or tag name is present and created by the given user ID.
    """
    result = await update_tag_name_by_id_or_name(**dict(update_data))
    return result

@app.delete("/tags/delete-tag")
async def delete_tag(delete_data: DeleteTagData):
    """
    Deletes a tag from the tags table if the given tag ID or tag name is present and created by the given user ID.
    """
    result = await delete_tag_by_id_or_name(**dict(delete_data))
    return result

@app.post("/tags/get-tags-by-agent")
async def read_tags_by_agent(agent_data: AgentIdName):
    """
    Retrieves tags associated with a given agent ID or agent name.
    """
    result = await get_tags_by_agent(agent_id=agent_data.agentic_application_id, agent_name=agent_data.agent_name)
    if not result:
        raise HTTPException(status_code=404, detail="Tags not found")
    return result

@app.post("/tags/get-tags-by-tool")
async def read_tags_by_tool(tool_data: ToolIdName):
    """
    Retrieves tags associated with a given tool ID or tool name.
    """
    result = await get_tags_by_tool(**(dict(tool_data)))
    if not result:
        raise HTTPException(status_code=404, detail="Tags not found")
    return result

@app.post("/tags/get-agents-by-tag")
async def read_agents_by_tag(tag_data: TagIdName):
    """
    Retrieves agents associated with a given tag ID or tag name.
    """
    result = await get_agents_by_tag(**dict(tag_data))
    if not result:
        raise HTTPException(status_code=404, detail="Agents not found")
    return result

@app.post("/tags/get-tools-by-tag")
async def read_tools_by_tag(tag_data: TagIdName):
    """
    Retrieves tools associated with a given tag ID or tag name.
    """
    result = await get_tools_by_tag(**dict(tag_data))
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

    file_location = os.path.join(save_path, uploaded_file.filename)

    with open(file_location, "wb") as f:
        shutil.copyfileobj(uploaded_file.file, f)
    log.info(f"Saved uploaded file to: {file_location}")
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
    log.info("File structure generated successfully")  
    return file_struct

@app.post("/files/user-uploads/upload-file/")
async def upload_file(file: UploadFile = File(...), subdirectory: str = ""):
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
    file_location = save_uploaded_file(file, abs_save_path)
    if isinstance(file_location, HTTPException):
        raise file_location
    log.info(f"File '{file.filename}' uploaded successfully to '{file_location}'")
    return {"info": f"File '{file.filename}' saved at '{file_location}'"}

@app.get("/files/user-uploads/get-file-structure/")
async def get_file_structure():
    file_structure = generate_file_structure(BASE_DIR)
    log.info("File structure retrieved successfully")
    return JSONResponse(content=file_structure)

@app.delete("/files/user-uploads/delete-file/")
async def delete_file(file_path: str):
    full_path = os.path.join(BASE_DIR, file_path)
    if os.path.exists(full_path):
        if os.path.isfile(full_path):
            os.remove(full_path)
            log.info(f"File '{file_path}' deleted successfully.")
            return {"info": f"File '{file_path}' deleted successfully."}
        else:
            log.info(f"Attempted to delete a directory: '{file_path}'")
            raise HTTPException(status_code=400, detail="The specified path is a directory. Only files can be deleted.")
    else:
        log.info(f"File '{file_path}' not found.")
        raise HTTPException(status_code=404, detail="No such file or directory.")




DOCS_ROOT = Path(r"C:\Agentic_foundary_documentation\docs")

def list_markdown_files(directory: Path) -> List[str]:
    """
    Recursively lists all Markdown (.md) files in the given directory and its subdirectories.
    """
    print(f"Looking in directory: {directory.resolve()}")

    if not directory.exists() or not directory.is_dir():
        raise HTTPException(status_code=404, detail=f"Directory not found at {directory.resolve()}")

    files = [str(file.relative_to(DOCS_ROOT)) for file in directory.rglob("*.md")]
    return files

@app.get("/list_markdown_files/")
def list_all_files():
    """
    Lists all Markdown files in the docs folder (including subfolders).
    """
    try:
        files = list_markdown_files(DOCS_ROOT)
        return {"files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.get("/list_markdown_files/{dir_name}")
def list_files_in_directory(dir_name: str):
    """
    Lists all Markdown files in a specific subdirectory under the docs folder.
    """
    target_dir = DOCS_ROOT / dir_name
    print(f"Target directory: {target_dir.resolve()}") 
    if not target_dir.exists() or not target_dir.is_dir():
        raise HTTPException(status_code=404, detail=f"Subdirectory '{dir_name}' not found")

    try:
        files = list_markdown_files(target_dir)
        return {"directory": dir_name, "files": files}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")




class login_data(BaseModel):
    email_id : str
    password: str
    role: str

class registration_data(BaseModel):
    email_id : str
    password: str
    role: str
    user_name: str


@app.post("/login")
async def login(data: login_data):
    update_session_context(user_id=data.email_id)
    log.info(f"Login attempt for user: {data.email_id} with role: {data.role}")
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='login',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Fetch user by email using parameterized query
        login_data = await conn.fetchrow(
            "SELECT mail_id, user_name, password, role FROM login_credential WHERE mail_id = $1",
            data.email_id
        )


        if login_data is None:
            log.info(f"Login failed for user: {data.email_id} - User not found")
            return {"approval": False, "message": "User not found"}

        if bcrypt.checkpw(data.password.encode('utf-8'), login_data['password'].encode('utf-8')):
            user_role = login_data['role']
            if user_role == "Admin":
                pass
            elif user_role == "Developer" and data.role == "Admin":
                log.info(f"Login failed for user: {data.email_id} - Unauthorized access attempt as Admin")
                return {"approval": False, "message": "You are not authorized as Admin"}
            elif user_role == "User" and data.role in ("Developer", "Admin"):
                log.info(f"Login failed for user: {data.email_id} - Unauthorized access attempt as {data.role}")
                return {"approval": False, "message": f"You are not authorized as {data.role}"}

            session_id = login_data['mail_id'] + "_" + str(uuid.uuid4()).replace("-", "_")
            update_session_context(session_id=session_id)
            log.info(f"Login successful for user: {data.email_id} with session ID: {session_id} and role: {data.role}")

            csrf_token = secrets.token_hex(32)

            return {
                "approval": True,
                "session_id": session_id,
                "csrf_token": csrf_token,
                "role": data.role,
                "username": login_data['user_name'],
                "email": login_data['mail_id'],
                "message": "Login successful"
            }
        else:
            log.info(f"Login failed for user: {data.email_id} - Incorrect password")
            return {"approval": False, "message": "Incorrect password"}

    finally:
        await conn.close()

@app.post("/registration")
async def registration(data: registration_data):
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='login',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    log.info(f"Registration attempt for user: {data.email_id} with role: {data.role}")

    try:
        # Check if user already exists
        existing_user = await conn.fetchrow(
            "SELECT * FROM login_credential WHERE mail_id = $1",
            data.email_id
        )

        if existing_user:
            log.info(f"Registration failed for user: {data.email_id} - User already exists")
            return {"approval": False, "message": "User already exists"}

        # Hash the password
        hashed_password = bcrypt.hashpw(data.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # Insert new user
        await conn.execute(
            '''
            INSERT INTO login_credential (mail_id, user_name, password, role)
            VALUES ($1, $2, $3, $4)
            ''',
            data.email_id, data.user_name, hashed_password, data.role
        )

        user_id = str(uuid.uuid4())
        log.info(f"Registration successful for user: {data.user_name} with email: {data.email_id} and role: {data.role}")
        return {"approval": True, "message": f"{data.user_name} registered successfully"}

    except Exception as e:
        log.error(f"Registration failed for user: {data.user_name} with email: {data.email_id} - Error occurred during registration")
        return {"approval": False, "message": "Registration failed due to an error"}

    finally:
        await conn.close()

@app.post("/update-password-role")
# Assuming you are using asyncpg for database interaction
async def update_user_password(email_id, new_password=None,role=None):
    """
    Updates the password for a user in the login_credential table.

    Args:
        conn: An active database connection object (e.g., from asyncpg.connect).
        email_id (str): The email ID of the user whose password needs to be updated.
        new_password (str): The new password for the user.
    Returns:
        dict: A dictionary indicating approval and a message.
    """
    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database='login',
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )
    try:
        # Check if the user exists
        existing_user = await conn.fetchrow(
            "SELECT * FROM login_credential WHERE mail_id = $1",
            email_id
        )

        if not existing_user:
            # log.info(f"Password update failed for user: {email_id} - User not found")
            return {"approval": False, "message": "User not found"}

        # Hash the new password
        if new_password is not None and role is None:
            hashed_new_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            # Update the password in the database
            await conn.execute(
                """
                UPDATE login_credential
                SET password = $1
                WHERE mail_id = $2
                """,
                hashed_new_password,
                email_id
            )

            # log.info(f"Password updated successfully for user: {email_id}")
            return {"approval": True, "message": "Password updated successfully"}
        elif role is not None and new_password is None:
            # Update the role in the database
            await conn.execute(
                """
                UPDATE login_credential
                SET role = $1
                WHERE mail_id = $2
                """,
                role,
                email_id
            )

            # log.info(f"Role updated successfully for user: {email_id}")
            return {"approval": True, "message": "Role updated successfully"}
        elif role is not None and new_password is not None:
            # Hash the new password
            hashed_new_password = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

            # Update both password and role in the database
            await conn.execute(
                """
                UPDATE login_credential
                SET password = $1, role = $2
                WHERE mail_id = $3
                """,
                hashed_new_password,
                role,
                email_id
            )

            # log.info(f"Password and role updated successfully for user: {email_id}")
            return {"approval": True, "message": "Password and Role updated successfully"}

    except Exception as e:
        # log.error(f"Error updating password for user {email_id}: {e}")
        return {"approval": False, "message": f"An error occurred: {e}"}


@app.get("/login_guest")
async def login_guest():
    update_session_context(user_id="Guest", session_id="test_101")
    log.info("Guest login successful")
    return {"approval": True, "email": "test", "session_id":"test_101", "user_name":"Guest", "message": "Guest Login Successful"}


class old_session_request(BaseModel):
    user_email: str
    agent_id: str

@app.post("/old-chats")
async def get_old_chats(request: old_session_request):
    user_email = request.user_email
    agent_id = request.agent_id
    table_name = f'table_{agent_id.replace("-", "_")}'

    conn = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Use parameterized query, but table name cannot be parameterized,
        # so make sure table_name is safe before usage.
        query = f"SELECT * FROM {table_name} WHERE session_id LIKE $1;"
        rows = await conn.fetch(query, f"{user_email}_%")
    except asyncpg.PostgresError:
        log.error(f"Error retrieving old chats for user: {user_email} and agent ID: {agent_id}")
        await conn.close()
        return JSONResponse(content={"detail": "no old chats found"}, status_code=404)
    finally:
        await conn.close()

    result = {}
    for row in rows:
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
    log.info(f"Retrieved old chats for user: {user_email} and agent ID: {agent_id}")
    return JSONResponse(content=jsonable_encoder(result))

@app.get("/new_chat/{email}")
async def new_chat(email:str):
    import uuid

    id = str(uuid.uuid4()).replace("-","_")
    session_id = email + "_" + id
    update_session_context(session_id=session_id) 
    log.info(f"New chat session created for user: {email} with session ID: {session_id}")
    return session_id

@app.get('/download')
async def download(filename: str = Query(...), sub_dir_name: str = Query(None)):
    base_path = Path("user_uploads")

    # Compose the path safely
    if sub_dir_name:
        file_path = base_path / sub_dir_name / filename
    else:
        file_path = base_path / filename

    log.info(f"Download request for file: {file_path}")

    if file_path.exists() and file_path.is_file():
        return FileResponse(file_path, media_type='application/octet-stream', filename=filename)
    else:
        return {"error": f"File not found: {file_path}"}

@router.receive(AgentInferenceRequest)
async def websocket_endpoint(websocket: WebSocket, request: AgentInferenceRequest):
    try:
        current_user_email.set(request.session_id.split("_")[0])
        await agent_inference(request, websocket)
    except Exception as e:
        return f"Exception is {e}"


app.include_router(router, prefix="/ws")

@app.get("/get-tools-by-pages/{page}")
async def get_tools_by_pages(page: int = 1, limit : int = Query(20, ge=1)):
    """
    Retrieves tools from the database with pagination.

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
    tools = await get_tools_by_page(page=page, limit=limit)
    if not tools:
        raise HTTPException(status_code=404, detail="No tools found")
    return tools


@app.get("/get-agents-by-pages/{page}")
async def get_agents_by_pages(page: int = 1, user_email: str= None, agent_type: str = None, limit: int = 10, is_admin: bool = True):
    """
    Retrieves agents from the database with pagination.

    Parameters:
    ----------
    Pagination : Pagination
        The request body containing pagination details.

    Returns:
    -------
    list
        A list of agents for the specified page.
    """
    agents = await get_agents_by_page(page=page, limit = limit, user_email_id=user_email, agentic_application_type=agent_type, is_admin=is_admin)
    if not agents:
        raise HTTPException(status_code=404, detail="No agents found")
    return agents

@app.get("/get-tools-by-search/{tool_name}")
async def get_tools_by_search(tool_name):
    """
    Retrieves tools from the tool table in PostgreSQL.

    Args:
        tool_name (str): The name of the tool to search for.

    Returns:
        list: A list of tools from the tool table, represented as dictionaries.
    """
    # Connect to the PostgreSQL database asynchronously
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Build the query with a LIKE search for the tool_name
        query = f"SELECT * FROM tool_table WHERE tool_name LIKE $1 ORDER BY created_on DESC;"
        parameters = (f"{tool_name}%",)  # Ensure this is a tuple for parameterization

        # Execute the query asynchronously
        rows = await connection.fetch(query, *parameters)

        # Convert the result rows into a list of dictionaries
        results_as_dicts = [dict(row) for row in rows]

        # Add tags for each result
        tool_id_to_tags = await get_tool_tags_from_mapping_as_dict()
        for result in results_as_dicts:
            result['tags'] = tool_id_to_tags.get(result['tool_id'], [])

        return results_as_dicts

    except asyncpg.PostgresError as e:
        return []

    finally:
        # Close the connection asynchronously
        await connection.close()

@app.get("/get-agents-by-search/{agent_name}")
async def get_agents_by_search(agentic_application_type=None, agent_table_name="agent_table", agent_name: str = None):
    # Connect to the PostgreSQL database asynchronously
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        # Build the query based on whether a filter is provided
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]

            # Create placeholders for the IN clause
            placeholders = ', '.join(f'${i + 1}' for i in range(len(agentic_application_type)))
            query = f"""
                SELECT *
                FROM {agent_table_name}
                WHERE agentic_application_type IN ({placeholders})
                ORDER BY created_on DESC
            """
            parameters = tuple(agentic_application_type)
        else:
            query = f"SELECT * FROM {agent_table_name} WHERE agentic_application_name LIKE $1;"
            parameters = (f"{agent_name}%",)  # Make sure it's a tuple for the query

        # Execute the query asynchronously
        rows = await connection.fetch(query, *parameters)

        # Convert the result into a list of dictionaries
        results_as_dicts = [dict(row) for row in rows]

        # Add tags for each result
        agent_id_to_tags = await get_agent_tags_from_mapping_as_dict()
        for result in results_as_dicts:
            result['tags'] = agent_id_to_tags.get(result['agentic_application_id'], [])

        return results_as_dicts

    except asyncpg.PostgresError as e:
        return []

    finally:
        # Close the connection asynchronously
        await connection.close()

@app.post("/get-tools-by-list")
async def get_tools_by_list(tool_ids: list[str]):
    tools = []
    for tool_id in tool_ids:
        tool = await get_tools_by_id(tool_id=tool_id)
        if tool:
            tools.append(tool[0])
    return tools

@app.post("/get-agents-by-list")
async def get_agents_by_list(agent_ids: list[str]):
    agents=[]
    for agent_id in agent_ids:
        agent = await get_agents_by_id(agentic_application_id=agent_id)
        if agent:
            agents.append(agent[0])
    return agents

@app.get("/get-tools-search-paginated/")
async def get_tools_by_search_paginated(search_value: str = None, page_number: int = 1, page_size: int = 10, connection=None):
    """
    Fetches tools from the database with pagination, filtering by tool_name.

    Args:
        tool_name (str): The name or partial name of the tool to search for.
        page_number (int): The current page number (1-indexed). Defaults to 1.
        page_size (int): The number of results per page. Defaults to 10.
        connection: An existing database connection object (e.g., from asyncpg.create_pool).

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents a tool.
    """
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    # Calculate OFFSET based on page_number and page_size
    # OFFSET is 0-indexed, so for page 1, offset is 0; for page 2, offset is page_size, etc.
    offset = (page_number - 1) * page_size

    # The query now includes LIMIT and OFFSET clauses
    # We use $1 for tool_name, $2 for page_size (LIMIT), and $3 for offset (OFFSET)
    if search_value is not None:
        query = f"""
            SELECT * FROM tool_table
            WHERE tool_name ILIKE $1 -- Using ILIKE for case-insensitive search
            ORDER BY created_on DESC
            LIMIT $2 OFFSET $3;
        """
        parameters = (f"{search_value}%", page_size, offset)

    else:
        # If no tool_name is provided, fetch all tools with pagination
        query = """
            SELECT * FROM tool_table
            ORDER BY created_on DESC
            LIMIT $1 OFFSET $2;
        """
        parameters = (page_size, offset)

    try:
        # Execute the query asynchronously
        rows = await connection.fetch(query, *parameters)

        # Convert the result rows into a list of dictionaries
        results_as_dicts = [dict(row) for row in rows]

        # Add tags for each result
        tool_id_to_tags = await get_tool_tags_from_mapping_as_dict()
        for result in results_as_dicts:
            result['tags'] = tool_id_to_tags.get(result['tool_id'], [])

        return results_as_dicts

    except Exception as e:
        log.error(f"Error fetching tools with pagination: {e}")
        return []
    finally:
        # Close the connection asynchronously
        await connection.close()

@app.get("/get-agents-search-paginated/")
async def get_agents_by_search_paginated(
    agentic_application_type=None,
    agent_table_name="agent_table",
    search_value: str = None,
    page_number: int = 1,  # New parameter for pagination
    page_size: int = 10    # New parameter for pagination
):
    """
    Fetches agents from the database with pagination, filtering by agentic_application_type
    or searching by agent_name.

    Args:
        agentic_application_type (Union[str, list[str], None]): The type(s) of agentic applications to filter by.
                                                                 If None, searches by agent_name.
        agent_table_name (str): The name of the table containing agent data.
        agent_name (str, optional): The name or partial name of the agent to search for.
                                    Used if agentic_application_type is None.
        page_number (int): The current page number (1-indexed). Defaults to 1.
        page_size (int): The number of results per page. Defaults to 10.

    Returns:
        list[dict]: A list of dictionaries, where each dictionary represents an agent.
    """
    # Calculate OFFSET based on page_number and page_size
    # OFFSET is 0-indexed: for page 1, offset is 0; for page 2, offset is page_size, etc.
    offset = (page_number - 1) * page_size

    # Connect to the PostgreSQL database asynchronously
    # In a production environment, consider using an asyncpg connection pool
    # instead of creating a new connection for each call.
    connection = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database=DATABASE,
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        query = ""
        parameters = ()
        param_counter = 1 # To manage parameter indexing ($1, $2, etc.)

        # Build the query based on whether agentic_application_type filter is provided
        if agentic_application_type:
            if isinstance(agentic_application_type, str):
                agentic_application_type = [agentic_application_type]

            # Create placeholders for the IN clause
            placeholders = ', '.join(f'${i + param_counter}' for i in range(len(agentic_application_type)))
            parameters = tuple(agentic_application_type)
            param_counter += len(agentic_application_type)

            query = f"""
                SELECT *
                FROM {agent_table_name}
                WHERE agentic_application_type IN ({placeholders})
                ORDER BY created_on DESC
                LIMIT ${param_counter} OFFSET ${param_counter + 1};
            """
            parameters += (page_size, offset)

        elif search_value is not None: # Use elif agent_name is not None to handle explicit search
            # If agentic_application_type is not provided, filter by agent_name
            # Using ILIKE for case-insensitive search in PostgreSQL
            query = f"""
                SELECT *
                FROM {agent_table_name}
                WHERE agentic_application_name ILIKE $1 -- Using ILIKE for case-insensitive search
                ORDER BY created_on DESC
                LIMIT $2 OFFSET $3;
            """
            parameters = (f"{search_value}%", page_size, offset)
        else:
            # If no filter is provided, fetch all agents with pagination
            query = f"""
                SELECT *
                FROM {agent_table_name}
                ORDER BY created_on DESC
                LIMIT $1 OFFSET $2;
            """
            parameters = (page_size, offset)


        # Execute the query asynchronously
        rows = await connection.fetch(query, *parameters)

        # Convert the result into a list of dictionaries
        results_as_dicts = [dict(row) for row in rows]

        # Add tags for each result
        agent_id_to_tags = await get_agent_tags_from_mapping_as_dict()
        for result in results_as_dicts:
            result['tags'] = agent_id_to_tags.get(result['agentic_application_id'], [])

        return results_as_dicts

    except asyncpg.PostgresError as e:
        log.error(f"PostgreSQL error: {e}")
        return []
    except Exception as e:
        log.error(f"An unexpected error occurred: {e}")
        return []
    finally:
        # Close the connection asynchronously
        await connection.close()


@app.get("/get-agents-details-for-chat")
async def get_agents_details():
    """
    Retrieves detailed information about agents for chat purposes.
    Returns:
    -------
    list
        A list of dictionaries containing agent details.
        If no agents are found, raises an HTTPException with status code 404.
    """
    agent_details = await get_agents_details_for_chat()
    return agent_details


@app.post("/secrets/create")
async def create_user_secret(request: SecretCreateRequest):
    """
    Create or update a user secret.
    
    Args:
        request (SecretCreateRequest): The request containing user email, secret name, and value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret creation fails.
    """
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Store the secret
        success = secrets_manager.store_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name,
            secret_value=request.secret_value
        )
        
        if success:
            log.info(f"Secret '{request.secret_name}' created/updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.secret_name}' created/updated successfully",
                "user_email": request.user_email,
                "secret_name": request.secret_name
            }
        else:
            log.error(f"Failed to create/update secret '{request.secret_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to create/update secret '{request.secret_name}'"
            )
            
    except Exception as e:
        log.error(f"Error creating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/secrets/get")
async def get_user_secret(request: SecretGetRequest):
    """
    Retrieve user secrets by name or get all secrets.
    
    Args:
        request (SecretGetRequest): The request containing user email and optional secret names.
    
    Returns:
        dict: The requested secrets or all secrets for the user.
    
    Raises:
        HTTPException: If secret retrieval fails or secrets not found.
    """
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        if request.secret_name:
            # Get a specific secret
            secret_value = secrets_manager.get_user_secret(
                user_email=request.user_email,
                secret_name=request.secret_name
            )
            
            if secret_value is not None:
                log.info(f"Secret '{request.secret_name}' retrieved successfully for user: {request.user_email}")
                return {
                    "success": True,
                    "user_email": request.user_email,
                    "secret_name": request.secret_name,
                    "secret_value": secret_value
                }
            else:
                log.warning(f"Secret '{request.secret_name}' not found for user: {request.user_email}")
                raise HTTPException(
                    status_code=404,
                    detail=f"Secret '{request.secret_name}' not found for user"
                )
                
        elif request.secret_names:
            # Get multiple specific secrets
            secrets_dict = secrets_manager.get_user_secrets(
                user_email=request.user_email,
                secret_names=request.secret_names
            )
            
            log.info(f"Multiple secrets retrieved successfully for user: {request.user_email}")
            return {
                "success": True,
                "user_email": request.user_email,
                "secrets": secrets_dict
            }
            
        else:
            # Get all secrets for the user
            secrets_dict = secrets_manager.get_user_secrets(
                user_email=request.user_email
            )
            
            log.info(f"All secrets retrieved successfully for user: {request.user_email}")
            return {
                "success": True,
                "user_email": request.user_email,
                "secrets": secrets_dict
            }
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving secrets for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.put("/secrets/update")
async def update_user_secret(request: SecretUpdateRequest):
    """
    Update an existing user secret.
    
    Args:
        request (SecretUpdateRequest): The request containing user email, secret name, and new value.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret update fails or secret doesn't exist.
    """
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Check if secret exists first
        existing_secret = secrets_manager.get_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name
        )
        
        if existing_secret is None:
            log.warning(f"Secret '{request.secret_name}' not found for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.secret_name}' not found for user"
            )
        
        # Update the secret
        success = secrets_manager.store_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name,
            secret_value=request.secret_value
        )
        
        if success:
            log.info(f"Secret '{request.secret_name}' updated successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.secret_name}' updated successfully",
                "user_email": request.user_email,
                "secret_name": request.secret_name
            }
        else:
            log.error(f"Failed to update secret '{request.secret_name}' for user: {request.user_email}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to update secret '{request.secret_name}'"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.delete("/secrets/delete")
async def delete_user_secret_endpoint(request: SecretDeleteRequest):
    """
    Delete a user secret.
    
    Args:
        request (SecretDeleteRequest): The request containing user email and secret name.
    
    Returns:
        dict: Success or error response.
    
    Raises:
        HTTPException: If secret deletion fails or secret doesn't exist.
    """
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Delete the secret
        success = secrets_manager.delete_user_secret(
            user_email=request.user_email,
            secret_name=request.secret_name
        )
        
        if success:
            log.info(f"Secret '{request.secret_name}' deleted successfully for user: {request.user_email}")
            return {
                "success": True,
                "message": f"Secret '{request.secret_name}' deleted successfully",
                "user_email": request.user_email,
                "secret_name": request.secret_name
            }
        else:
            log.warning(f"Secret '{request.secret_name}' not found for deletion for user: {request.user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{request.secret_name}' not found for user"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error deleting secret for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/secrets/list")
async def list_user_secrets_endpoint(request: SecretListRequest):
    """
    List all secret names for a user (without values).
    
    Args:
        request (SecretListRequest): The request containing user email.
    
    Returns:
        dict: List of secret names or error response.
    
    Raises:
        HTTPException: If listing secrets fails.
    """
    try:
        # Set the user context
        current_user_email.set(request.user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Get list of secret names
        secret_names = secrets_manager.list_user_secret_names(
            user_email=request.user_email
        )
        
        log.info(f"Secret names listed successfully for user: {request.user_email}")
        return {
            "success": True,
            "user_email": request.user_email,
            "secret_names": secret_names,
            "count": len(secret_names)
        }
        
    except Exception as e:
        log.error(f"Error listing secrets for user {request.user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# Alternative GET endpoint for retrieving a single secret
@app.get("/secrets/{user_email}/{secret_name}")
async def get_single_user_secret(user_email: str, secret_name: str):
    """
    Retrieve a single user secret by URL parameters.
    
    Args:
        user_email (str): The user's email address.
        secret_name (str): The name of the secret to retrieve.
    
    Returns:
        dict: The requested secret or error response.
    
    Raises:
        HTTPException: If secret retrieval fails or secret not found.
    """
    try:
        # Set the user context
        current_user_email.set(user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Get the secret
        secret_value = secrets_manager.get_user_secret(
            user_email=user_email,
            secret_name=secret_name
        )
        
        if secret_value is not None:
            log.info(f"Secret '{secret_name}' retrieved successfully for user: {user_email}")
            return {
                "success": True,
                "user_email": user_email,
                "secret_name": secret_name,
                "secret_value": secret_value
            }
        else:
            log.warning(f"Secret '{secret_name}' not found for user: {user_email}")
            raise HTTPException(
                status_code=404,
                detail=f"Secret '{secret_name}' not found for user"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error retrieving secret for user {user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# Alternative GET endpoint for listing all secret names
@app.get("/secrets/{user_email}/list")
async def list_user_secrets_get(user_email: str):
    """
    List all secret names for a user using GET endpoint.
    
    Args:
        user_email (str): The user's email address.
    
    Returns:
        dict: List of secret names or error response.
    
    Raises:
        HTTPException: If listing secrets fails.
    """
    try:
        # Set the user context
        current_user_email.set(user_email)
        
        # Initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        # Get list of secret names
        secret_names = secrets_manager.list_user_secret_names(
            user_email=user_email
        )
        
        log.info(f"Secret names listed successfully for user: {user_email}")
        return {
            "success": True,
            "user_email": user_email,
            "secret_names": secret_names,
            "count": len(secret_names)
        }
        
    except Exception as e:
        log.error(f"Error listing secrets for user {user_email}: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

# Health check endpoint for secrets functionality
@app.get("/secrets/health")
async def secrets_health_check():
    """
    Health check endpoint for secrets management functionality.
    
    Returns:
        dict: Health status of the secrets management system.
    """
    try:
        # Try to initialize secrets manager
        secrets_manager = setup_secrets_manager()
        
        return {
            "success": True,
            "message": "Secrets management system is healthy",
            "timestamp": str(asyncio.get_event_loop().time())
        }
        
    except Exception as e:
        log.error(f"Secrets health check failed: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"Secrets management system is unhealthy: {str(e)}"
        )


@app.get("/recycle-bin/{param}")
async def restore_tools(param:Literal["tools", "agents"],user_email_id: str):
    """
    Restores tools from the recycle bin.

    Returns:
    -------
    list
        A list of restored tools. If no tools are found, raises an HTTPException with status code 404.
    """
    connection_login = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="login",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    # Check if the user's role is admin or not in the login database
    query = "SELECT role FROM login_credential WHERE mail_id = $1;"

    user_role = await connection_login.fetchval(query, user_email_id)
    if user_role.lower() != "admin":
        return HTTPException(status_code=403, detail="You are not authorized to access this resource")

    connection_recycle = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="recycle",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    try:
        if param == "tools":
            # Fetch all tools from the recycle bin
            query = "SELECT * FROM recycle_tool;"
        elif param == "agents":
            # Fetch all agents from the recycle bin
            query = "SELECT * FROM recycle_agent;"
        else:
            return HTTPException(status_code=400, detail="Invalid parameter. Use 'tools' or 'agents'.")
        rows = await connection_recycle.fetch(query)
        restored_tools = [dict(row) for row in rows]
        if not restored_tools:
            return HTTPException(status_code=404, detail=f"No {param} found in recycle bin")
        return restored_tools
    except asyncpg.PostgresError as e:
        log.error(f"Error retrieving {param} from recycle bin: {e}")
        return HTTPException(status_code=500, detail="Internal server error")
    finally:
        await connection_recycle.close()


@app.post("/restore/{param}")
async def restore(param: Literal["tools", "agents"], item_id: str,user_email_id):
    """
    Restores a tool or agent from the recycle bin.

    Parameters:
    ----------
    param : Literal["tools", "agents"]
        The type of item to restore, either "tools" or "agents".
    item_id : str
        The ID of the tool or agent to restore.

    Returns:
    -------
    dict
        A dictionary containing the restored item details.
        If the item is not found, raises an HTTPException with status code 404.
    """
    connection_login = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="login",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    # Check if the user's role is admin or not in the login database
    query = "SELECT role FROM login_credential WHERE mail_id = $1;"

    user_role = await connection_login.fetchval(query, user_email_id)
    if user_role.lower() != "admin":
        return HTTPException(status_code=403, detail="You are not authorized to access this resource")
    if param == "tools":
        return await restore_recycle_tool_by_id(item_id)
    elif param == "agents":
        return await restore_recycle_agent_by_id(item_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid parameter. Use 'tools' or 'agents'.")
    
@app.delete("/delete/{param}")
async def delete(param: Literal["tools", "agents"], item_id: str,user_email_id):
    """
    Deletes a tool or agent permanently from the recycle bin.

    Parameters:
    ----------
    param : Literal["tools", "agents"]
        The type of item to delete, either "tools" or "agents".
    item_id : str
        The ID of the tool or agent to delete.

    Returns:
    -------
    dict
        A dictionary containing the deleted item details.
        If the item is not found, raises an HTTPException with status code 404.
    """
    connection_login = await asyncpg.connect(
        host=POSTGRESQL_HOST,
        database="login",
        user=POSTGRESQL_USER,
        password=POSTGRESQL_PASSWORD
    )

    # Check if the user's role is admin or not in the login database
    query = "SELECT role FROM login_credential WHERE mail_id = $1;"

    user_role = await connection_login.fetchval(query, user_email_id)
    if user_role.lower() != "admin":
        return HTTPException(status_code=403, detail="You are not authorized to access this resource")
    if param == "tools":
        return await delete_recycle_tool_by_id(item_id)
    elif param == "agents":
        return await delete_recycle_agent_by_id(item_id)
    else:
        raise HTTPException(status_code=400, detail="Invalid parameter. Use 'tools' or 'agents'.")


@app.get("/export-agents")
async def download_multipleagent_export(
    agent_ids: List[str] = Query(..., description="List of agent IDs to export"),
    background_tasks: BackgroundTasks = BackgroundTasks()
):
    """
    Downloads a zip archive of the specified agent's data and associated files.
    """
    try:
        zip_file_path = await export_agent_by_id(agent_ids)

        if not os.path.exists(zip_file_path):
            raise HTTPException(status_code=500, detail="Generated zip file not found.")

        filename = os.path.basename(zip_file_path)
        media_type = "application/zip"

        # Define the cleanup function
        async def cleanup_files():
            print(f"Cleanup: Starting background task for {zip_file_path}")
            temp_base_dir = "temp_agent_exports"
            temp_working_dir = os.path.join(temp_base_dir, f"export")
            try:
                if os.path.exists(zip_file_path):
                    os.remove(zip_file_path)
                    print(f"Cleanup: Removed zip file: {zip_file_path}")
                if os.path.exists(temp_working_dir):
                    shutil.rmtree(temp_working_dir)
                    print(f"Cleanup: Removed temp working directory: {temp_working_dir}")
            except Exception as e:
                print(f"Cleanup Error: Failed to clean up files: {e}")

        # Add the cleanup function to background tasks
        background_tasks.add_task(cleanup_files)

        # Return the FileResponse
        return FileResponse(
            path=zip_file_path,
            media_type=media_type,
            filename=filename
        )

    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"Error serving file: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")

async def export_agent_by_id(agent_ids: List[str]) -> str:

    if len(agent_ids)==1:
        adict={}
        agent_data_list = await get_agents_by_id(agentic_application_id=agent_ids[0])
        if not agent_data_list or not isinstance(agent_data_list, list) or len(agent_data_list) == 0:
            raise HTTPException(status_code=404, detail=f"Agent ID: '{agent_ids[0]}' not found.")

        agent_dict = agent_data_list[0]
        agent_for_json_dump = agent_dict.copy()
        for key, value in agent_for_json_dump.items():
            if isinstance(value, datetime):
                agent_for_json_dump[key] = value.isoformat()
        adict[agent_ids[0]]=agent_for_json_dump
        if agent_dict.get('agentic_application_type') == 'react_agent':

            STATIC_EXPORTING_FOLDER = "Export_Agent/React_Export"

            if not os.path.isdir(STATIC_EXPORTING_FOLDER):
                os.makedirs(STATIC_EXPORTING_FOLDER, exist_ok=True)
        if agent_dict.get('agentic_application_type') == 'meta_agent':

            STATIC_EXPORTING_FOLDER = "Export_Agent/Meta_Export"

            if not os.path.isdir(STATIC_EXPORTING_FOLDER):
                os.makedirs(STATIC_EXPORTING_FOLDER, exist_ok=True)
        if agent_dict.get('agentic_application_type') == 'multi_agent':

            STATIC_EXPORTING_FOLDER = "Export_Agent/Multi_Export"

            if not os.path.isdir(STATIC_EXPORTING_FOLDER):
                os.makedirs(STATIC_EXPORTING_FOLDER, exist_ok=True)
        if agent_dict.get('agentic_application_type') == 'planner_meta_agent':

            STATIC_EXPORTING_FOLDER = "Export_Agent/Planner_Meta_Export"

            if not os.path.isdir(STATIC_EXPORTING_FOLDER):
                os.makedirs(STATIC_EXPORTING_FOLDER, exist_ok=True)

        temp_base_dir = os.path.join(tempfile.gettempdir(), "your_app_agent_exports")

        unique_export_id = os.urandom(8).hex() # Re-add your unique export ID here
        temp_working_dir = os.path.join(temp_base_dir, f"{agent_ids[0]}_{unique_export_id}") # Append unique ID here
        final_zip_content_folder_name = agent_dict.get('agentic_application_name')
        target_export_folder_path = os.path.join(temp_working_dir, final_zip_content_folder_name)

        zip_file_full_path = None

        try:
            if os.path.exists(temp_working_dir):
                shutil.rmtree(temp_working_dir)
                print(f"Cleaned up existing unique temp directory: {temp_working_dir}")


            os.makedirs(os.path.dirname(target_export_folder_path), exist_ok=True)
            shutil.copytree(STATIC_EXPORTING_FOLDER, target_export_folder_path)
            print(f"Copied static folder from '{STATIC_EXPORTING_FOLDER}' to '{target_export_folder_path}'")
            agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/agent_data.py')
            with open(agent_data_file_path, 'w') as f:
                f.write('agent_data = ')
                json.dump(adict, f, indent=4)
            print(f"agent_data.py saved to: {agent_data_file_path}")
            if agent_dict.get('agentic_application_type') == 'react_agent' or agent_dict.get('agentic_application_type') == 'multi_agent':
                await get_tool_data(agent_dict, export_path=target_export_folder_path)

                output_zip_name = f"agent_export"
                # The zip file will also be created in the system temp directory
                zip_base_name = os.path.join(temp_base_dir, output_zip_name)
                zip_file_full_path = shutil.make_archive(zip_base_name, 'zip', temp_working_dir)

                print(f"Created zip file: {zip_file_full_path}")
                return zip_file_full_path
            if agent_dict.get('agentic_application_type') in ['meta_agent','planner_meta_agent']:
                worker_agent_ids=agent_dict.get("tools_id")
                print(worker_agent_ids)
                worker_agents={}
                for agent in json.loads(worker_agent_ids):
                    agent_data = await get_agents_by_id(agentic_application_id=agent)
                    if agent_data:
                        agent_dict= agent_data[0]
                        processed_agent_dict = {}
                        for key, value in agent_dict.items():
                            if isinstance(value, datetime):
                                processed_agent_dict[key] = value.isoformat()
                            else:
                                processed_agent_dict[key] = value
                        worker_agents[agent] = processed_agent_dict
                    else:
                        worker_agents[agent] = None
                worker_agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/worker_agents_data.py')
                with open(worker_agent_data_file_path, 'w') as f:
                    f.write('worker_agents = ')
                    json.dump(worker_agents, f, indent=4)
                tool_list=[]
                for i in worker_agents:
                    tool_list=tool_list+(json.loads(worker_agents[i]["tools_id"]))
                await get_tool_data(agent_dict, export_path=target_export_folder_path,tools=tool_list)
                output_zip_name = f"agent_export"
                # The zip file will also be created in the system temp directory
                zip_base_name = os.path.join(temp_base_dir, output_zip_name)
                zip_file_full_path = shutil.make_archive(zip_base_name, 'zip', temp_working_dir)

                print(f"Created zip file: {zip_file_full_path}")
                return zip_file_full_path

        except Exception as e:
            print(f"An error occurred during export: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to export agent: {str(e)}")
    else:
        STATIC_EXPORTING_FOLDER = "Export_Agent/MultipleAgents"
        workerids=set()
        app_types=set()
        toolids=set()
        adict={}
        for agent_id in agent_ids:
            agent_data_list = await get_agents_by_id(agentic_application_id=agent_id)
            if not agent_data_list or not isinstance(agent_data_list, list) or len(agent_data_list) == 0:
                raise HTTPException(status_code=404, detail=f"Agent with ID '{agent_id}' not found.")

            agent_dict = agent_data_list[0]
            agent_for_json_dump = agent_dict.copy()
            for key, value in agent_for_json_dump.items():
                if isinstance(value, datetime):
                    agent_for_json_dump[key] = value.isoformat()
            adict[agent_id]=agent_for_json_dump
            app_types.add(agent_for_json_dump['agentic_application_type'])
            if agent_dict.get("agentic_application_type") in ["meta_agent","planner_meta_agent"]:
                ids=json.loads(agent_dict.get('tools_id'))
                for i in ids:
                    workerids.add(i)
            else:
                ids=json.loads(agent_dict.get('tools_id'))
                for i in ids:
                    toolids.add(i)
        temp_base_dir = os.path.join(tempfile.gettempdir(), "your_app_agent_exports")

        unique_export_id = os.urandom(8).hex() # Re-add your unique export ID here
        temp_working_dir = os.path.join(temp_base_dir, f"exportagent_{unique_export_id}") # Append unique ID here
        final_zip_content_folder_name = "MultipleAgents"#agent_dict.get('agentic_application_name')
        target_export_folder_path = os.path.join(temp_working_dir, final_zip_content_folder_name)

        zip_file_full_path = None

        try:
            if os.path.exists(temp_working_dir):
                shutil.rmtree(temp_working_dir)
                print(f"Cleaned up existing unique temp directory: {temp_working_dir}")


            os.makedirs(os.path.dirname(target_export_folder_path), exist_ok=True)
            shutil.copytree(STATIC_EXPORTING_FOLDER, target_export_folder_path)
            backendfile_path = os.path.join(target_export_folder_path, 'Agent_Backend')
            for i in app_types:
                if i=='react_agent':
                    shutil.copy('Export_Agent/React_Export/Agent_Backend/react_inference.py', backendfile_path)                
                elif i=='meta_agent':
                    shutil.copy('Export_Agent/Meta_Export/Agent_Backend/meta_inference.py', backendfile_path)
                elif i=='multi_agent':
                    shutil.copy('Export_Agent/Multi_Export/Agent_Backend/multi_inference.py', backendfile_path)
                    shutil.copy('Export_Agent/Multi_Export/Agent_Backend/multiagent_without_hitl.py', backendfile_path)
                    shutil.copy('Export_Agent/Multi_Export/Agent_Backend/multiagent_with_hitl.py', backendfile_path)
                elif i=='planner_meta_agent':
                    shutil.copy('Export_Agent/Planner_Meta_Export/Agent_Backend/plannermeta_inference.py', backendfile_path)
                    
            print(f"Copied static folder from '{STATIC_EXPORTING_FOLDER}' to '{target_export_folder_path}'")
            agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/agent_data.py')
            with open(agent_data_file_path, 'w') as f:
                f.write('agent_data = ')
                json.dump(adict, f, indent=4)
            print(f"agent_data.py saved to: {agent_data_file_path}")
            worker_agents={}
            for agent in list(workerids):
                agent_data = await get_agents_by_id(agentic_application_id=agent)
                if agent_data:
                    agent_dict= agent_data[0]
                    processed_agent_dict = {}
                    for key, value in agent_dict.items():
                        if isinstance(value, datetime):
                            processed_agent_dict[key] = value.isoformat()
                        else:
                            processed_agent_dict[key] = value
                    worker_agents[agent] = processed_agent_dict
                else:
                    worker_agents[agent] = None
            worker_agent_data_file_path = os.path.join(target_export_folder_path, 'Agent_Backend/worker_agents_data.py')
            with open(worker_agent_data_file_path, 'w') as f:
                f.write('worker_agents = ')
                json.dump(worker_agents, f, indent=4)
            tool_list=[]
            for i in worker_agents:
                tool_list=tool_list+(json.loads(worker_agents[i]["tools_id"]))
            for i in tool_list:
                toolids.add(i)
            await get_tool_data(adict, export_path=target_export_folder_path,tools=list(toolids))
            output_zip_name = f"agent_export"
                # The zip file will also be created in the system temp directory
            zip_base_name = os.path.join(temp_base_dir, output_zip_name)
            zip_file_full_path = shutil.make_archive(zip_base_name, 'zip', temp_working_dir)

            print(f"Created zip file: {zip_file_full_path}")
            return zip_file_full_path
                
        except Exception as e:
            print(f"An error occurred during export: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to export agent: {str(e)}")        
                   