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

