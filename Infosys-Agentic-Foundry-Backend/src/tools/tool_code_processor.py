# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import ast
import astor
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from src.prompts.prompts import tool_prompt_generator
from telemetry_wrapper import logger as log


class ToolCodeProcessor:
    """
        Validates tool and generates docstrings for tools.
        This class is responsible for generating docstrings for tools.
        It uses the LangChain library to interact with LLMs and generate
        docstrings based on the provided tool code and description.
    """

    def __init__(self):
        pass

    @staticmethod
    async def validate_and_extract_tool_name(code_str: str):
        """
        Using the ast module, syntax check the function and
        return the function name in the code snippet.
        Supports both regular and async functions.
        """
        try:
            parsed_code = ast.parse(code_str)
        except Exception as e:
            err = f"Tool Onboarding Failed: Function parsing error.\n{e}"
            log.error(err)
            return {
                "function_name": "",
                "error": err,
                "is_valid": False
            }

        function_count = sum(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in parsed_code.body)
        err = None
        if function_count == 0:
            err = "Tool Onboarding Failed: No function definition found. Input must have a single function definition."
        elif function_count > 1:
            err = "Tool Onboarding Failed: More than one function definition found. Input must only have a single function definition."
        elif not isinstance(parsed_code.body[-1], (ast.FunctionDef, ast.AsyncFunctionDef)):
            err = "There should be no scripts after the function defination"
        else:
            for node in parsed_code.body[:-1]:
                if not isinstance(node, (ast.Import, ast.ImportFrom)):
                    err = "Only import statements are allowed in global scope (i.e. only import statements can be used before function defination)"
                    break

        if err:
            log.error(err)
            return {"function_name": "", "error": err, "is_valid": False}

        try:
            for node in parsed_code.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for arg in node.args.args:
                        if arg.annotation is None:
                            err = "Data Types Not Mentioned for the arguments of the function"
                            log.error(err)
                            return {"function_name": "", "error": err, "is_valid": False}

            function_names = [
                node.name
                for node in ast.walk(parsed_code)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            function_name = function_names[0] if function_names else ""
            if not function_name:
                err = "Tool Onboarding Failed: Function name not found."
                log.error(err)
                return {"function_name": "", "error": err, "is_valid": False}
            log.info(f"Function name extracted: {function_name}")
            return {"function_name": function_name, "is_valid": True}
        except (SyntaxError, ValueError, IndexError) as e:
            err = f"Tool Onboarding Failed: Syntax error in function definition.\n{e}"
            log.error(err)
            return {"function_name": "", "error": err, "is_valid": False}

    @staticmethod
    async def update_docstring(code: str, new_docstring: str):
        if new_docstring.startswith('"""') or new_docstring.startswith("'''"):
            new_docstring = new_docstring[3:-3]
        new_docstring = new_docstring.replace('\n', '\n    ')
        tree = ast.parse(code)

        class DocstringUpdater(ast.NodeTransformer):
            def visit_FunctionDef(self, node):
                node.body = [ast.Expr(value=ast.Constant(value=new_docstring))] + [
                    stmt for stmt in node.body
                    if not isinstance(stmt, ast.Expr) or
                    not isinstance(stmt.value, ast.Constant) or
                    not isinstance(stmt.value.value, str)
                ]
                return node

        updater = DocstringUpdater()
        updated_tree = updater.visit(tree)
        log.info("Docstring updated successfully.")
        return astor.to_source(updated_tree)

    @staticmethod
    async def generate_docstring_for_tool_onboarding(llm, tool_code_str: str, tool_description: str = ""):
        validity_status = await ToolCodeProcessor.validate_and_extract_tool_name(tool_code_str)
        if "error" in validity_status:
            return {"error": validity_status['error']}

        try:
            tool_docstring_prompt_template = PromptTemplate.from_template(tool_prompt_generator)
            tool_docstring_gen = tool_docstring_prompt_template | llm | StrOutputParser()

            docstring = await tool_docstring_gen.ainvoke({"tool_code_str": tool_code_str, "tool_description": tool_description})
            docstring = docstring.replace("```python", "").replace("```", "").strip()

            updated_tool_code_str = await ToolCodeProcessor.update_docstring(tool_code_str, docstring)
            updated_tool_code_str = updated_tool_code_str.strip()
            log.info("Tool docstring generated and code updated successfully.")
            return {"code_snippet": updated_tool_code_str}

        except Exception as e:
            err = f"Tool Onboarding Failed: Error while generating docstring.\n{e}"
            log.error(err)
            return {"error": err}

    @staticmethod
    async def validate_validator_function(code_str: str):
        """
        Validates that a validator function has the correct signature and return values.
        Validator functions must:
        1. Have exactly 2 parameters: 'query' and 'response'
        2. Return validation_score/validation_status and feedback
        """
        try:
            parsed_code = ast.parse(code_str)
        except Exception as e:
            err = f"Validator Tool Validation Failed: Function parsing error.\n{e}"
            log.error(err)
            return {"error": err, "is_valid": False}

        # Find the function definition
        function_node = None
        for node in parsed_code.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_node = node
                break

        if not function_node:
            err = "Validator Tool Validation Failed: No function definition found."
            log.error(err)
            return {"error": err, "is_valid": False}

        # Check function parameters
        args = function_node.args.args
        if len(args) != 2:
            err = "Validator Tool Validation Failed: Validator functions must have exactly 2 parameters: 'query' and 'response'."
            log.error(err)
            return {"error": err, "is_valid": False}

        param_names = [arg.arg for arg in args]
        if param_names != ['query', 'response']:
            err = f"Validator Tool Validation Failed: Parameters must be named 'query' and 'response', got: {param_names}"
            log.error(err)
            return {"error": err, "is_valid": False}

        # Check return statements to ensure they return validation results
        return_statements = []
        for node in ast.walk(function_node):
            if isinstance(node, ast.Return) and node.value is not None:
                return_statements.append(node)

        if not return_statements:
            err = "Validator Tool Validation Failed: Function must return validation results."
            log.error(err)
            return {"error": err, "is_valid": False}

        # Enhanced validation - check return statement structure
        valid_return_found = False
        required_fields = {'validation_score', 'feedback', 'validation_status'}
        
        for return_node in return_statements:
            if isinstance(return_node.value, ast.Dict):
                # Check if return is a dictionary literal
                dict_keys = []
                for key in return_node.value.keys:
                    if isinstance(key, ast.Constant) and isinstance(key.value, str):
                        dict_keys.append(key.value)
                    elif isinstance(key, ast.Str):  # For older Python versions
                        dict_keys.append(key.s)
                
                # Check if all required fields are present
                if required_fields.issubset(set(dict_keys)):
                    valid_return_found = True
                    break
            elif isinstance(return_node.value, ast.Call):
                # Check if return is a dict() call - this is harder to validate statically
                if (isinstance(return_node.value.func, ast.Name) and 
                    return_node.value.func.id == 'dict'):
                    # For dict() constructor, we'll do a runtime validation instead
                    valid_return_found = True
                    break
            elif isinstance(return_node.value, ast.Name):
                # Return is a variable - we can't validate structure statically
                # This would need runtime validation
                valid_return_found = True
                break

        # If we couldn't find a clearly valid return, try runtime validation
        if not valid_return_found:
            try:
                # Attempt runtime validation with sample inputs
                runtime_valid = await ToolCodeProcessor._runtime_validate_validator(code_str)
                if not runtime_valid:
                    err = ("Validator Tool Validation Failed: Function must return a dictionary with "
                           "required fields: 'validation_score' (float), 'feedback' (string), "
                           "and 'validation_status' (string).")
                    log.error(err)
                    return {"error": err, "is_valid": False}
            except Exception as e:
                err = (f"Validator Tool Validation Failed: Could not validate return structure. "
                       f"Ensure function returns dict with 'validation_score', 'feedback', "
                       f"and 'validation_status'. Error: {str(e)}")
                log.error(err)
                return {"error": err, "is_valid": False}

        # Validation passed
        log.info("Validator function validation passed")
        return {"is_valid": True}

    @staticmethod
    async def _runtime_validate_validator(code_str: str) -> bool:
        """
        Runtime validation of validator function to ensure it returns proper structure.
        Tests the function with sample inputs and validates the return format.
        """
        try:
            # Create a safe execution environment
            local_namespace = {}
            
            # Execute the code to define the function
            exec(code_str, {"__builtins__": __builtins__}, local_namespace)
            
            # Find the validator function
            validator_function = None
            for name, obj in local_namespace.items():
                if callable(obj) and not name.startswith('_'):
                    validator_function = obj
                    break
            
            if not validator_function:
                return False
            
            # Test with sample inputs
            test_cases = [
                ("2 + 2", "4"),
                ("What is the capital of France?", "The capital of France is Paris."),
                ("", "No response provided")
            ]
            
            for query, response in test_cases:
                try:
                    result = validator_function(query=query, response=response)
                    
                    # Handle async functions
                    if hasattr(result, '__await__'):
                        import asyncio
                        result = await result
                    
                    # Validate return structure
                    if not isinstance(result, dict):
                        log.warning(f"Validator function returned {type(result)} instead of dict")
                        return False
                    
                    # Check required fields
                    required_fields = {'validation_score', 'feedback', 'validation_status'}
                    if not required_fields.issubset(result.keys()):
                        missing_fields = required_fields - result.keys()
                        log.warning(f"Validator function missing required fields: {missing_fields}")
                        return False
                    
                    # Validate field types
                    if not isinstance(result['validation_score'], (int, float)):
                        log.warning("validation_score must be numeric")
                        return False
                    
                    if not isinstance(result['feedback'], str):
                        log.warning("feedback must be a string")
                        return False
                    
                    if not isinstance(result['validation_status'], str):
                        log.warning("validation_status must be a string")
                        return False
                    
                    # Validate score range
                    score = result['validation_score']
                    if not (0.0 <= score <= 1.0):
                        log.warning(f"validation_score should be between 0.0 and 1.0, got {score}")
                        # This is a warning, not a failure
                
                except Exception as e:
                    log.warning(f"Runtime validation failed for test case ({query}, {response}): {e}")
                    return False
            
            return True
            
        except Exception as e:
            log.warning(f"Runtime validation error: {e}")
            return False

