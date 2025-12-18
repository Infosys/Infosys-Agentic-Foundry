# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
from langgraph.graph import StateGraph
from pydantic import BaseModel, Field
from typing import Optional, Any
import json,re,ast
# from src.models.model import load_model
# llm = load_model('gpt-4o', temperature=0.0)
from pydantic import BaseModel
from typing import Optional,Annotated
from telemetry_wrapper import logger as log, update_session_context
from src.prompts.tool_validation_prompts import docstring_length,error_handling,safe_validation,validate_inputs,hardcoded_values,name_descriptiveness


class ToolValidationState(BaseModel):
    code: Annotated[Optional[str],lambda x, y: x or y] = None
    model: Annotated[Optional[str],lambda x, y: x or y] = None
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
    validation_case8: Annotated[Optional[bool],lambda x, y: x or y] = None
    feedback_case8: Annotated[Optional[str],lambda x, y: x or y] = None

async def get_llm(model_name: str):
    from src.api.dependencies import ServiceProvider
    model_service = ServiceProvider.get_model_service()
    # if model_name=="gpt-35-turbo":
    #     if "gpt-4o" in model_service.available_models:
    #         model_name="gpt-4o"
    llm = await model_service.get_llm_model(model_name=model_name)
    return llm
def extract_json(response):
    start=response.find('{')
    if start == -1:
        return response.strip()
    bc=0
    end=None
    for i in range(start,len(response)):
        if response[i]=='{':
            bc+=1
        elif response[i]=='}':
            bc-=1
            if bc ==0:
                end=i+1
                break
    if end is None:
        return response.strip()
    json_str=response[start:end]
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        return json_str.strip()

async def test_Case1_is_code_compilable(func_code: str) -> bool:
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

async def test_Case2_docstring_lengthlimit(function_code: str, model: str):
    prompt = docstring_length.format(function_code=function_code)
    llm= await get_llm(model)
    # temperature=get_temperature_for_model(model)
    # response = await llm.ainvoke(prompt,temperature=temperature)
    response = await llm.ainvoke(prompt)
    response = response.content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    return raw_output

async def test_Case3_validate_function_name_descriptiveness(function_code: str, model: str, temperature: float = 0.0) -> str:
    prompt = name_descriptiveness.format(function_code=function_code)
    llm= await get_llm(model)
    # temperature=get_temperature_for_model(model)
    # response = await llm.ainvoke(prompt,temperature=temperature)
    response = await llm.ainvoke(prompt)
    response = response.content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    else:
        raw_output = extract_json(response)
    return raw_output

async def test_Case4_validate_function_inputs(function_code: str, model: str) -> str:
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

async def test_Case5_error_handling(function_code: str, model:str, temperature: float = 0.0):
    prompt = error_handling.format(function_code=function_code)
    llm= await get_llm(model)
    # temperature=get_temperature_for_model(model)
    # response = await llm.ainvoke(prompt,temperature=temperature)
    response = await llm.ainvoke(prompt)
    response = response.content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    else:
        raw_output = extract_json(response)
    return raw_output
async def test_Case6_malicious_code_detection(function_code: str, model:str,temperature: float = 0.0):
    prompt = safe_validation.format(function_code=function_code)
    llm = await get_llm(model)
    # temperature=get_temperature_for_model(model)
    # response = await llm.ainvoke(prompt,temperature=temperature)
    response = await llm.ainvoke(prompt)
    response = response.content.strip()
    if response.startswith("```json"):
        raw_output = response.removeprefix("```json").removesuffix("```").strip()
    elif response.startswith("```"):
        raw_output = response.removeprefix("```").removesuffix("```").strip()
    else:
        raw_output = extract_json(response)
    return raw_output

def rename_function(code_str: str) -> str:
    class FunctionRenamer(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            node.name = "test"
            return node

    try:
        tree = ast.parse(code_str)
        tree = FunctionRenamer().visit(tree)
        ast.fix_missing_locations(tree)
        new_code = ast.unparse(tree)
        return new_code
    except Exception as e:
        return f"Error: {e}"
async def test_Case7_hardcoded_values(function_code: str, model:str):
    import re
    from flask import json

    function_code = rename_function(function_code)
    patterns = {
        "emails": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b",
        "phone_numbers": r"\b(?:\+?\d{1,3})?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b",
        # "api_keys": r"\b[A-Za-z0-9]{32,}\b",
        "urls": r"https?://[^\s'\"]+",
        "passwords":r'\b(password|pwd|passwd)\s*=\s*[\'"].+[\'"]',
        "env_vars": r"os\\.environ\\[['\"]?[A-Za-z_]+['\"]?\\]",
        "git_pat": r"ghp_[A-Za-z0-9]{36}",
        "git_username": r"(?i)(git[_-]?username)[\\s:=]+['\"]?[A-Za-z0-9._-]+['\"]?"
    }

    findings = {key: [] for key in patterns}

    for line in function_code.splitlines():
        # Skip lines containing get_public_secrets or os.environ
        if "get_public_secrets" in line or "os.environ" in line or "get_user_secrets" in line or "os.getenv" in line:
            continue

        for key, pattern in patterns.items():
            matches = re.findall(pattern, line)
            if matches:
                findings[key].extend(matches)

    # Remove duplicates
    for key in findings:
        findings[key] = list(set(findings[key]))
    prompt = f"""
    You are given a dictionary of detected patterns from a code scan for hardcoded sensitive data:

    {json.dumps(findings, indent=4)}

    Your task:
    1. Identify which items are truly sensitive (e.g., real API keys, tokens, passwords, secrets).
    2. Ignore false positives like field names or generic API endpoints.
    3. Return a refined dictionary with only sensitive items.

    Rules:
    - URLs are sensitive only if they contain tokens, secrets, or API keys in query params.
    - Ignore placeholders like {{drive_id}}, {{site_id}}, {{config}}.
    - Ignore descriptive field names like 'accountNameAndAccountSpecificDocuments'.
    - Keep actual API keys (e.g., long random strings like '373446e8af1a462fa4d245d9a92a7697').
    - **Ignore** the http and https urls where the secrets are represented as placeholders(e.g., {"https://${uname}:${pat}@github.com/Infosys-Generative-AI/Agentic-Pro-UI.git"})

    Output format:
    Return a Python dictionary with the same keys but only sensitive items retained.
    Return Only the dictionary as output, no explanations.  
    """
    llm = await get_llm(model)
    # temperature=get_temperature_for_model(model)
    # response = await llm.ainvoke(prompt, temperature=temperature)
    response = await llm.ainvoke(prompt)
    response = response.content.strip()
    refined=""
    if response.startswith("```python"):
        refined = response.removeprefix("```python").removesuffix("```").strip() 
    elif response.startswith("```"):
        refined = response.removeprefix("```").removesuffix("```").strip()
    else:
        refined = str(extract_json(response))
    if not refined:
        refined = response
    refined = ast.literal_eval(refined)
    refined["emails"]=findings["emails"]
    detected = [key for key, items in refined.items() if items]

    if detected:
        message = (
            f"Avoid hardcoding secrets like {', '.join(detected)} in tool, Use Secret Vault"
        )
        return json.dumps({
            "validation": False,
            "suggestion": message
        })

    return json.dumps({"validation": True})

async def test_Case8_is_valid_function_name(function_code:str):
    import re
    try:
        import ast
        tree = ast.parse(function_code)
        for node in tree.body:
            # if isinstance(node, ast.FunctionDef):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                func_name = node.name
                if len(func_name) > 64:
                    return False, f"Tool name exceeds 64 characters."               
                if not re.match(r'^[A-Za-z0-9_]+$', func_name):
                    return False, f"Tool name contains invalid characters."               
                return True, f"Tool name '{func_name}' is valid."        
        return False, "No function definition found in the code."    
    except SyntaxError as e:
        return False, f"Syntax error in code: {e}"


async def node_case1(state: ToolValidationState):
    code = state.code
    raw = await test_Case1_is_code_compilable(code)
    updated_state = state.model_copy(update={
        "validation_case1": raw["validation"],
        "feedback_case1": raw.get("suggestion", None)
    })  
    return updated_state

async def node_case2(state: ToolValidationState):
    try:
        code = state.code
        model = state.model
        raw_output = await test_Case2_docstring_lengthlimit(code,model)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case2": parsed.get("validation"),
            "feedback_case2": parsed.get("suggestion") 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating docstring length limit: {str(e)}")

async def node_case3(state:ToolValidationState):
    try:
        code = state.code
        model = state.model
        raw_output = await test_Case3_validate_function_name_descriptiveness(code,model)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        if isinstance(raw_output, str):
            # parsed = json.loads(raw_output)       
            try:
                parsed = json.loads(raw_output)  # Try JSON first
            except json.JSONDecodeError:
                parsed = ast.literal_eval(raw_output)
        else:
            parsed = ast.literal_eval(raw_output)

        # parsed=json.loads(raw_output)
        updated_state = state.model_copy(update={
            "validation_case3": parsed.get("validation"),
            "feedback_case3": parsed.get("suggestion") 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating function name descriptiveness: {str(e)}")

async def node_case4(state:ToolValidationState):
    try:
        code = state.code
        model = state.model
        raw_output = await test_Case4_validate_function_inputs(code, model)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        # parsed=json.loads(raw_output)
        if isinstance(raw_output, str):
            # parsed = json.loads(raw_output)
            try:
                parsed = json.loads(raw_output)  # Try JSON first
            except json.JSONDecodeError:
                parsed = ast.literal_eval(raw_output)
        else:
            parsed = ast.literal_eval(raw_output)
        updated_state = state.model_copy(update={
            "validation_case4": parsed.get("validation"),
            "feedback_case4": "Data Types Not Mentioned for the arguments of the function" if parsed.get("suggestion") else None
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating function inputs: {str(e)}")

async def node_case5(state:ToolValidationState):
    try:
        code = state.code
        model = state.model
        raw_output = await test_Case5_error_handling(code, model)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        # parsed=json.loads(raw_output)
        if isinstance(raw_output, str):
            # parsed = json.loads(raw_output)
            try:
                parsed = json.loads(raw_output)  # Try JSON first
            except json.JSONDecodeError:
                parsed = ast.literal_eval(raw_output)
        else:
            parsed = ast.literal_eval(raw_output)
        if parsed.get("validation"):
                feedback = "No Suggestion"
        else:
            if len(parsed.get("suggestion")) < 150:
                feedback = parsed.get("suggestion")
            else:
                feedback = "Please ensure proper error handling using try-except blocks to prevent unexpected crashes and improve code reliability."
        updated_state = state.model_copy(update={
            "validation_case5": parsed.get("validation"),
            "feedback_case5": feedback
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating error handling: {str(e)}")

async def node_case6(state:ToolValidationState):
    try:
        code = state.code
        model = state.model
        raw_output = await test_Case6_malicious_code_detection(code, model)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        # parsed=json.loads(raw_output)
        if isinstance(raw_output, str):
            # parsed = json.loads(raw_output)
            try:
                parsed = json.loads(raw_output)  # Try JSON first
            except json.JSONDecodeError:
                parsed = ast.literal_eval(raw_output)
        else:
            parsed = ast.literal_eval(raw_output)
        updated_state = state.model_copy(update={
            "validation_case6": parsed.get("validation"),
            "feedback_case6": parsed.get("suggestion") 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating malicious code detection: {str(e)}")

async def node_case7(state: ToolValidationState):
    try:
        code = state.code
        model = state.model
        raw_output = await test_Case7_hardcoded_values(code, model)
        raw_output = raw_output.replace("True", "true").replace("False", "false") if isinstance(raw_output, str) else raw_output
        # parsed=json.loads(raw_output)
        if isinstance(raw_output, str):
            # parsed = json.loads(raw_output)
            try:
                parsed = json.loads(raw_output)  # Try JSON first
            except json.JSONDecodeError:
                parsed = ast.literal_eval(raw_output)
        else:
            parsed = ast.literal_eval(raw_output)
        updated_state = state.model_copy(update={
            "validation_case7": parsed.get("validation"),
            "feedback_case7": parsed.get("suggestion") 
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating hardcoded values: {str(e)}")

async def node_case8(state: ToolValidationState):
    try:
        code=state.code
        is_valid, message = await test_Case8_is_valid_function_name(code)
        updated_state = state.model_copy(update={
            "validation_case8": is_valid,
            "feedback_case8": message if not is_valid else None
        })
        return updated_state
    except Exception as e:
        log.error(f"Error while validating function name: {str(e)}")

#Create a langgraph workflow

workflow = StateGraph(state_schema=ToolValidationState)


workflow.add_node("case1", node_case1)
workflow.add_node("case3", node_case3)
workflow.add_node("case4", node_case4)
workflow.add_node("case5", node_case5)
workflow.add_node("case6", node_case6)
workflow.add_node("case7", node_case7)
workflow.add_node("case8", node_case8)

workflow.set_entry_point("case1")
workflow.add_edge("case1", "case3")
workflow.add_edge("case1", "case4")
workflow.add_edge("case1", "case5")
workflow.add_edge("case1", "case6")
workflow.add_edge("case1", "case7")
workflow.add_edge("case1", "case8")
workflow.set_finish_point("case3")
workflow.set_finish_point("case4")
workflow.set_finish_point("case5")
workflow.set_finish_point("case6")
workflow.set_finish_point("case7")
workflow.set_finish_point("case8")

graph = workflow.compile()

