# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field
from typing import Optional, Any
import json
from src.models.model import load_model
llm = load_model('gpt-4o')
from pydantic import BaseModel
from typing import Optional,Annotated
from telemetry_wrapper import logger as log, update_session_context
from src.prompts.tool_validation_prompts import docstring_length,error_handling,safe_validation,validate_inputs,hardcoded_values,name_descriptiveness
class ToolValidationState(BaseModel):
    code: Annotated[Optional[str],lambda x, y: x or y] = None
    validation_case1: Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case1: Annotated[Optional[str],lambda x, y: x or y] = None
    validation_case2: Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case2: Annotated[Optional[str],lambda x, y: x or y] = None
    validation_case3: Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case3: Annotated[Optional[str],lambda x, y: x or y] = None
    validation_case4: Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case4: Annotated[Optional[str],lambda x, y: x or y] = None
    validation_case5:Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case5: Annotated[Optional[str],lambda x, y: x or y] = None
    validation_case6: Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case6: Annotated[Optional[str],lambda x, y: x or y] = None
    validation_case7: Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case7: Annotated[Optional[str],lambda x, y: x or y] = None

def test_Case1_is_code_compilable(func_code: str) -> bool:
    try:
        exec(func_code, {})
        return {
            "validation": True
        }
    except Exception as e:
        return {
            "validation": False,
            "suggestion": str(e)
        }
def test_Case2_docstring_lengthlimit(function_code:str):
    prompt = docstring_length.format(function_code=function_code)
    response = llm.invoke(prompt, temperature=0.0).content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    return raw_output
def test_Case3_validate_function_name_descriptiveness(function_code: str) -> str:
    prompt = name_descriptiveness.format(function_code=function_code)
    response = llm.invoke(prompt, temperature=0.0).content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    return raw_output

def test_Case4_validate_function_inputs(function_code: str) -> str:
    import ast
    parsed_code = ast.parse(function_code)
    for node in parsed_code.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for arg in node.args.args:
                if arg.annotation is None:
                    err = "Data Types Not Mentioned for the arguments of the function"
                    log.error(err)
                    return json.dumps({
                        "validation": False,
                        "suggestion": str(err)
                    })
    return json.dumps({ "validation": True })

def test_Case5_error_handling(function_code: str) -> str:
    prompt = error_handling.format(function_code=function_code)
    response = llm.invoke(prompt, temperature=0.0).content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    return raw_output
def test_Case6_malicious_code_detection(function_code: str) -> tuple[bool, str | None]:
    prompt = safe_validation.format(function_code=function_code)
    response = llm.invoke(prompt, temperature=0.0).content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    return raw_output
def test_Case7_hardcoded_values(function_code:str):
    prompt = hardcoded_values.format(function_code=function_code)
    response = llm.invoke(prompt, temperature=0.0).content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    return raw_output


def node_case1(state: ToolValidationState):
    code = state.code
    raw = test_Case1_is_code_compilable(code)
    updated_state = state.model_copy(update={
        "validation_case1": raw["validation"],
        "feedback_case1": raw.get("suggestion", None)
    })  
    return updated_state

def node_case2(state: ToolValidationState):
    try:
        code = state.code
        raw_output = test_Case2_docstring_lengthlimit(code)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case2": parsed.get("validation"),
            "feedback_case2": parsed.get("suggestion") 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating docstring length limit: {str(e)}")

def node_case3(state:ToolValidationState):
    try:
        code = state.code
        raw_output = test_Case3_validate_function_name_descriptiveness(code)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case3": parsed.get("validation"),
            "feedback_case3": parsed.get("suggestion") 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating function name descriptiveness: {str(e)}")

def node_case4(state:ToolValidationState):
    try:
        code = state.code
        raw_output = test_Case4_validate_function_inputs(code)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case4": parsed.get("validation"),
            "feedback_case4": "Data Types Not Mentioned for the arguments of the function" if parsed.get("suggestion") else None
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating function inputs: {str(e)}")

def node_case5(state:ToolValidationState):
    try:
        code = state.code
        raw_output = test_Case5_error_handling(code)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case5": parsed.get("validation"),
            "feedback_case5": parsed.get("suggestion") if len(parsed.get("suggestion")) < 150 else "Please ensure proper error handling using try-except blocks to prevent unexpected crashes and improve code reliability." 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating error handling: {str(e)}")

def node_case6(state:ToolValidationState):
    try:
        code = state.code
        raw_output = test_Case6_malicious_code_detection(code)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case6": parsed.get("validation"),
            "feedback_case6": parsed.get("suggestion") 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating malicious code detection: {str(e)}")

def node_case7(state: ToolValidationState):
    try:
        code = state.code
        raw_output = test_Case7_hardcoded_values(code)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case7": parsed.get("validation"),
            "feedback_case7": parsed.get("suggestion") 
            # if len(parsed.get("suggestion")) < 250 else "Use secret Vault for storing sensitive information like API keys, endpoints, file paths, passwords, tokens and personal information etc. instead of hardcoding them."
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating hardcoded values: {str(e)}")


#Create a langgraph workflow

workflow = StateGraph(state_schema=ToolValidationState)


workflow.add_node("case1", node_case1)
workflow.add_node("case2", node_case2)
workflow.add_node("case3", node_case3)
workflow.add_node("case4", node_case4)
workflow.add_node("case5", node_case5)
workflow.add_node("case6", node_case6)
workflow.add_node("case7", node_case7)

# Define parallel edges
workflow.set_entry_point("case1")
workflow.add_edge("case1", "case2")
workflow.add_edge("case1", "case3")
workflow.add_edge("case1", "case4")
workflow.add_edge("case1", "case5")
workflow.add_edge("case1", "case6")
workflow.add_edge("case1", "case7")
workflow.set_finish_point("case2")
workflow.set_finish_point("case3")
workflow.set_finish_point("case4")
workflow.set_finish_point("case5")
workflow.set_finish_point("case6")
workflow.set_finish_point("case7")

graph = workflow.compile()
