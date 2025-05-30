# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import ast
import astor
from langchain.prompts import PromptTemplate
from langchain_core.output_parsers.string import StrOutputParser
from src.prompts.prompts import tool_prompt_generator

def is_syntax_valid(function_string):
    """
    Checks if the given string represents valid Python syntax.

    Args:
        function_string: A string containing the Python code to be checked.

    Returns:
        True if the string contains valid Python syntax, False otherwise.
    """
    try:
        # Parse the string to check for syntax validity
        ast.parse(function_string)
        return True
    except SyntaxError as e:
        return False

def update_docstring(code, new_docstring):
    if new_docstring.startswith('"""') or new_docstring.startswith("'''"):
        new_docstring = new_docstring[3:-3]
    new_docstring=new_docstring.replace('\n','\n    ')
    tree = ast.parse(code)

    if sum(isinstance(node, ast.FunctionDef) for node in tree.body) != 1:
        raise ValueError('Input must be a single function definition')

    if not isinstance(tree.body[-1], ast.FunctionDef):
        raise ValueError("There should be no scripts after the function defination")

    for node in tree.body[:-1]:
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            raise ValueError("Only import statements are allowed in global scope (i.e. only import statements can be used before function defination)")


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
    return astor.to_source(updated_tree)

def generate_docstring_tool_onboarding(llm, tool_code_str, tool_description=""):
    if not is_syntax_valid(tool_code_str):
        try:
            ast.parse(tool_code_str)
            return f"Tool Onboarding Failed"
        except Exception as e:
            return f"Tool Onboarding Failed: Function parsing error.\n{e}"

    tool_docstring_prompt_template = PromptTemplate.from_template(tool_prompt_generator)
    tool_docstring_gen = tool_docstring_prompt_template | llm | StrOutputParser()

    docstring = tool_docstring_gen.invoke({"tool_code_str": tool_code_str, "tool_description": tool_description})
    docstring = docstring.replace("```python", "").replace("```", "").strip()
    updated_tool_code_str = update_docstring(tool_code_str, docstring).strip()
    return updated_tool_code_str
