# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
name_descriptiveness="""
## Objective
Analyze the following Python function for **name clarity** and determine if the function name is clear, specific, and descriptive based on the following rules.
- **The function name must be **clear, specific, and descriptive**.
- **Avoid vague or generic names such as:
  - 'run', 'do', 'handle', 'go', 'process', etc.

## User Inputs
Please consider the following details:

### Python Function
{function_code}

## Instructions
- **You will be provided with a Python function in a code block.
- **Assess whether the function name clearly communicates its purpose.
- **Return your analysis using the format below.
- **If the name is **descriptive**:
   ```json
   {{
		"validation": True
   }}
   ```
- **- If the name is **not descriptive**:
   ```json
   {{
		"validation": False,
		"suggestion": Rename '<old_name>' to something like '<better_name>'
   }}
   ```
- **Do **not** explain your decision.
- **Keep the suggestion short, specific, and actionable.
- **Do **not** explain the decision. Just return the boolean and the suggestion.
"""

validate_inputs="""
## Objective
Validate Python function parameters for clarity, typing, and JSON-compatibility.

## User Inputs
Please consider the following details:
-- 
### Python Function
{function_code}

## Instructions
You will be provided with a Python function, analyzes its parameters, and checks if:
- **All parameters are explicitly named (no `*args` or `**kwargs`).
- **All parameters include type hints.
- **All parameter types are JSON-serializable (i.e., `str`, `int`, `float`, `bool`, `list`, `dict`).
- **Return your analysis using the format below.
- **If all parameters meet the rules:
   ```json
   {{
		"validation": True
   }}
   ```
- **If any parameter breaks the rules:
   ```json
   {{
		"validation": False,
		"suggestion": <fix for parameter issues>'
   }}
   ```
- **Do **not** explain your decision.
- **Keep the suggestion short, specific, and actionable.
- **Do **not** explain the decision. Just return the boolean and the suggestion.
"""

safe_validation="""
## Objective
Evaluate whether a given Python function performs unsafe or potentially dangerous operations and determine if it is safe or unsafe.
Determine whether a function is **safe** or **unsafe** based on strict security and safety criteria. A function is considered **unsafe** if it performs any of the following:
- **Deletes files or directories (e.g., `rm -rf`, `os.remove`, `shutil.rmtree`)
- **Performs system shutdown or restart (e.g., `shutdown`, `reboot`)
- **Kills or modifies system processes
- **Executes arbitrary or destructive shell/system commands
- **Makes irreversible changes to system configurations
- **Contains code injection or in-memory manipulation
- **Sends sensitive data insecurely
- **Modifies user permissions or performs unauthorized privilege escalation

## User Inputs
Please consider the following details:
-- 
### Python Function
{function_code}

## Instructions
You will be provided with a Python function and must:
- **Detect any operations that may compromise system integrity, user safety, or security.
- **Follow clearly defined criteria for classifying functions as **unsafe**.
- **Suggest a concise fix when applicable.
- **Return your analysis using the format below.
- **If the function is **safe**:
   ```json
   {{
		"validation": True
   }}
   ```
- **If the function is **unsafe**:
   ```json
   {{
		"validation": False,
		"suggestion": <Brief improvement tip>'
   }}
   ```
- **Do **not** explain your decision.
- **Keep the suggestion short, specific, and actionable.
- **Do **not** explain the decision. Just return the boolean and the suggestion.
"""

hardcoded_values="""
## Objective
Detect the presence of hardcoded sensitive data such as passwords, API keys, and personally identifiable information (PII) within Python functions.
Validate that the function does **not** contain any hardcoded values such as:
- **API keys,endponits
- **Passwords
- **Authentication tokens
- **Personally identifiable information (PII)
- **Secrets embedded directly in the code
A function is considered **invalid** if it includes any of the above directly in the source code.

## User Inputs
Please consider the following details:
-- 
### Python Function
{function_code}

## Instructions
You will be provided with a Python function and:
- **Check for any hardcoded values that resemble API keys, secrets, tokens, passwords, or other forms of sensitive data.
- **Classify the function as valid or invalid based on this criterion.
- **Return a short and practical suggestion if invalid.
- **Return your analysis using the format below.
- **If the function is **valid**:
   ```json
   {{
		"validation": True
   }}
   ```
- **If the function is **invalid**:
   ```json
   {{
		"validation": False,
		"suggestion": <single-line feedback>\\n<corrected function code>
   }}
   ```
- **Return a single-line feedback message followed by the corrected code** — both in the `suggestion` field only.
- **Do NOT use a separate `code` field.**
- **Do **not** explain your decision.
- **Keep the suggestion short, specific, and actionable.
- **Do **not** explain the decision. Just return the boolean and the suggestion.
"""

error_handling= """
## Objective
Assess the Python function for correctness, clean coding standards, and robustness.
Evaluate a Python function for:
- **Syntax or logical errors
- **Presence of input/output functions like `input()` or `print()`
- **Compliance with clean coding practices
If any issues are found, the function is marked invalid and a corrected version should be suggested.

## User Inputs
Please consider the following details:
-- 
### Python Function
{function_code}

## Instructions
You will be provided with a Python function and:
- **Validate the function's correctness and appropriateness (no `print()` or `input()` allowed).
- **If invalid, suggest a corrected version of the code with:
   - **Type hints
   - **Error handling
   - **No I/O functions
   - **Clean and maintainable structure
- **Return a short and practical suggestion if invalid.
- **Return your analysis using the format below.
- If there are **no errors** and **no input/output functions**, respond with:
- **If there are **no errors** and **no input/output functions**:
   ```json
   {{
		"validation": True
   }}
   ```
- **If there **are errors** or **I/O functions**:
   ```json
   {{
		"validation": False,
		"suggestion": <provide the corrected version of the function>
   }}
   ```

- **Do **not** change the function's core logic.
- **Keep the suggestion short, clear, and practical.  
- **Do **not** explain the decision. Just return the boolean and the corrected version of function.

"""

docstring_length = """
## Objective
Evaluate whether a given Python function has a docstring that is too long (exceeds 1024 characters), which can reduce readability or violate documentation standards.

## User Inputs
Please consider the following details:
-- 
### Python Function
{function_code}

## Instructions
- **Analyze the given Python function.
- **Extract the docstring.
- **Measure its character length.
- **Determine if it is **valid** (≤ 1024 characters) or **invalid** (> 1024 characters).
- **If the docstring exceeds 1024 characters, rewrite it in a concise form while retaining key information.
- **Return your analysis using the format below.
- **If the function is **valid**:
   ```json
   {{
		"validation": True
   }}
   ```
- **If the function is **invalid**:
   ```json
   {{
		"validation": False,
		"suggestion": <a revised docstring under 1024 characters>
   }}
   ```
- **Preserve original intent and tone when rewriting.
- **Do **not** remove meaningful content unless necessary for brevity.
- **Do **not** provide additional explanation. Just return the status and new docstring. 
- **Do **not** explain the decision. Just return the boolean and the suggestion.

"""

