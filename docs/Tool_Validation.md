
# Tool Validation Rules
## Overview

This document outlines the validation process for onboarding new tools. Before any tool is added, it must pass through a validation checklist to ensure quality, security, and reliability.

## Validation Process

1. **Code Analysis**: Tool code is analyzed against validation criteria
2. **Result Classification**: Each item is marked as Pass, Warning, or Error
3. **User Decision**: If issues are found, user decides whether to proceed
4. **Tool Addition**: Tool is added or rejected based on user consent
## Validation Checklist

All tools must pass these validation rules before onboarding:
**1. Testing** :

- This is an **Error** level validation
- Must include test cases to validate the tool

**2. Tool Name** :

- This is a **Warning** level validation
- Tool names must be descriptive and unambiguous
- Avoid overloaded names

**3. Arguments** :

- This is an **Error** level validation
- All inputs must be explicitly named and typed
- Use JSON-serializable types (str, int, float, bool, list, dict)

**4. Fail-Safes** :

- This is a **Warning** level validation
- Include clear error messages and fallbacks for invalid inputs
- Enable meaningful error handling

**5. Side Effects** :

- This is an **Error** level validation
- Avoid tools with dangerous or irreversible side effects unless absolutely necessary
- Tools that delete data or send irreversible commands require justification

**6. Credential Handling** :

- This is a **Warning** level validation
- Use environment variables or secret managers
- Never hardcode API keys or credentials

**7. Import Statements**:

- This is an **Error** level validation
- Tools must include explicit and proper import statements for all dependencies

**8. Output and Input Handling**:

- This is an **Error** level validation
- Avoid using `print` statements within the tool
- Tools must not directly prompt for or accept user inputs in their code

## Rule Classifications

- **Error**: Critical issues that strongly indicate revision needed
- **Warning**: Issues that should be addressed but don't block deployment
- **Pass**: Requirements met