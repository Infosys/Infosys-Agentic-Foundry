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
- **All parameter types are JSON-serializable (i.e., `str`, `int`, `float`, `bool`, `list`, `dict`,`tuple`,`set`,`Dict`, `List`, `Tuple`, `Set`).
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
## Task
Perform a Comprehensive security analysis on the provided python function to detect highly risk malicious or suspicious activity
## Role
Act as a highly skilled and cybersecurity analyst with expertise in Python code review and threat detection.
## Objective
Analyze the code for high risk malicious or suspicious activity.
Evaluate the code safety based on the analysis
Evaluate whether a given Python function performs unsafe or potentially dangerous operations and determine if it is safe or unsafe.
Determine whether a function is **safe** or **unsafe** based on strict security and safety criteria. A function is considered **unsafe** if it performs any of the following:
- **Performs system shutdown or restart (e.g., `shutdown`, `reboot`)
- **Kills or modifies system processes
- **Executes arbitrary or destructive shell/system commands
- **Makes irreversible changes to system configurations
- **Contains code injection or in-memory manipulation
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
		"suggestion": <Specify which unsafe operation was detected and suggest ways in removing or modifying it to ensure safety>'
   }}
   ```
- **Do **not** explain your decision.
- **Keep the suggestion short, specific, and actionable.
- **Do **not** explain the decision. Just return the boolean and the suggestion.
- **NEVER check for Hardcoded values, API keys, passwords, tokens, or other sensitive data if they access through get_user_secrets(),get_public_key(), os.environ[] and os.getenv().
- **Only** check for malicious code which might cause harm to the system.
- **Do **not** check for any other validations except unsafe code.
- **Do **not** check for eval() and exec() functions as unsafe code.
- **Do **not** flag code that uses subprocess,os and shutil module as unsafe unless it performs any of the unsafe operations mentioned above.
- **Do **not** flag code that uses system commands like 'ls', 'pwd', 'echo', 'dir', 'cd' as unsafe unless it performs any of the unsafe operations mentioned above.
- **Do **not** flag code based on variable names that include terms like 'delete', 'remove', 'kill', 'shutdown', 'reboot', 'exec', 'eval', 'command', 'process', 'permission', 'privilege' etc., unless the function actually performs an unsafe operation as defined above.
- **Do **not** flag file operations like reading, writing, or appending to files as unsafe.
- **Do **not** flag file operations like creating, moving, or copying files and directories as unsafe.
- **Do **not** flag network operations like making HTTP requests, opening sockets, or interacting with APIs as unsafe.
- **Do **not** consider the information provided in comments when determining if a function is safe or unsafe.
- **Do **not** consider the information provided in docstring when determining if a function is safe or unsafe.
- **Do **not** consider the information provided in variable names when determining if a function is safe or unsafe.
# """

hardcoded_values="""
## Objective
Detect the presence of hardcoded sensitive data such as passwords, API keys, and personally identifiable information (PII) within Python functions.
Validate that the function does **not** contain any hardcoded values such as:
- **API keys,endpoints
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
- **Check for any hardcoded values that resemble API keys, secrets, tokens, passwords only it is fine if they access through get_user_secrets(),get_public_key(), os.environ[] and os.getenv().
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
		"suggestion": <specify which values are hardcoded and suggest to store them securely using secret vault and access by using functions like get_user_secrets(),get_public_secrets()>
   }}
   ```
- **Return a single-line feedback message** — both in the `suggestion` field only.
- **Do NOT use a separate `code` field.**
- **Do **not** explain your decision. Just return the boolean and the suggestion.
- **Keep the suggestion as it is.
- **Allow** flag if the hardcoded values are inside  get_user_secrets(), get_public_key(), os.environ[], or os.getenv() like get_user_secrets('base_url', 'https://default-weather-api.com'),get_public_secrets('url',"https://openai-ppcazure017.openai.azure.com/") anything.
- **Check for only Keys,email ids, passwords, tokens, endpoints and urls if they are hardcoded directly in the code.
- **Ignore other hardcoded values like str,integers, float, list, dict, tuples, set etc if they not come under confidential data.
- **Ignore if they access through get_user_secrets(),get_public_key(), os.environ[] and os.getenv().
- **Do NOT check for public constants,internal identifiers,environment specific tags,client specific tags,models and non-confidential data.
- **Do **not** check any other validations except hardcoded values like API keys,tokens,urls, email ids,passwords and endpoints.
- **Do not flag default string values like 'faiss_index_hsbc' in function parameters as hardcoded secrets. These are internal configuration identifiers and are allowed unless they contain sensitive data such as credentials, API keys, or client-specific secrets.
- **Do not flag placeholder values like 'your_api_key_here' or 'your_password_here' as hardcoded secrets. These are commonly used in example code and documentation to indicate where users should insert their own sensitive information.
- **Do not flag non-sensitive hardcoded values like 'localhost', 'http://example.com', 'admin', 'user', 'password123', or '12345' as hardcoded secrets. These are generic and do not pose a security risk.
- **Do not flag hardcoded values that are part of comments or docstrings within the code. These do not affect the execution of the program and are typically used for explanatory purposes.
- **Do not flag hardcoded values that are assigned to variables or constants but are not sensitive in nature, such as configuration settings, feature flags, or non-confidential identifiers.
- **Do **not** flag based on variable names that include terms like 'key', 'token', 'password', 'secret', or 'credential' unless the assigned value is actually a sensitive hardcoded value.
- **Do **not** flag if the hardcoded values are inside  get_user_secrets(), get_public_key(), os.environ[], or os.getenv() like get_user_secrets('base_url', 'https://default-weather-api.com'),get_public_secrets('url',"https://openai-ppcazure017.openai.azure.com/") anything.
- **Do **not** flag code that uses external libraries or modules to manage secrets, such as `dotenv`, `keyring`, or cloud provider SDKs, unless they contain hardcoded sensitive values as defined above.
- **Do **not** flag if the values are hardcoded inside triple quotes (""" """) or (''' ''') as they are generally used for multi-line strings or docstrings.
- **Do **not** flag if the values are hardcoded inside function definition parameters with default values.
- **Do **not** flag file paths, directory names, or other non-sensitive strings that do not contain confidential information.
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

