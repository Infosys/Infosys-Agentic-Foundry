## Feature Overview

Enable users to create custom tools through the conversational chat interface by describing their requirements in natural language. The system should interpret user intent, extract tool specifications, generate the tool code, and register it in the IAF platform.

## Business Objective

- Reduce time-to-deployment for new tools from hours to minutes
- Enable non-technical users to create automation tools
- Standardize tool creation with consistent quality and documentation

---

## Scope

- Natural language processing of tool creation requests
- Automatic extraction of tool name, description, parameters, and logic
- Code generation for tool functions
- Tool registration in the IAF system
- Validation and error handling
- User confirmation workflow before final creation
- Tool editing/modification via chat (future enhancement)
- External API integration setup
- Database connection configuration

---

## Functional Requirements

**1. Intent Detection**

| Field | Details |
|-------|---------|
| `Description` | System must detect when a user intends to create a new tool |
| `Trigger Phrases` | "Create a tool", "Make a tool", "I need a tool that", "Build a function", "Add a new tool" |
| `Acceptance Criteria` | System correctly identifies tool creation intent with 95%+ accuracy |

**2. Information Extraction**

| Field | Details |
|-------|---------|
| `Description` | System must extract required tool specifications from user conversation |
| `Required Fields` | Tool name, Tool description, Input parameters (name, type, description), Return type/description |
| `Optional Fields` | Business logic rules, Error handling requirements, Sample input/output |
| `Acceptance Criteria` | All required fields extracted or user prompted for missing information |

**3. Clarification Dialogue**

| Field | Details |
|-------|---------|
| `Description` | System must ask clarifying questions when information is incomplete |
| `Behavior` | Prompt user for missing required fields one at a time |
| `Acceptance Criteria` | User is never blocked; guided to provide complete information |

**4. Tool Specification Summary**

| Field | Details |
|-------|---------|
| `Description` | System must present a summary of extracted tool specifications for user confirmation |
| `Display Format` | Structured summary showing: Name, Purpose, Parameters (with types), Expected output, Business logic |
| `Acceptance Criteria` | User can review and confirm or request modifications |

**5. Code Generation**

| Field | Details |
|-------|---------|
| `Description` | System must generate valid Python function code based on specifications |
| `Requirements` | - Proper function signature with type hints<br>- Comprehensive docstring (Args, Returns)<br>- Implementation of specified business logic<br>- Error handling |
| `Acceptance Criteria` | Generated code passes syntax validation and follows IAF tool standards |

**6. Tool Registration**

| Field | Details |
|-------|---------|
| `Description` | System must register the created tool in IAF platform |
| `Actions` | - Save the tool and Register in tool database<br>- Make available for agent assignment |
| `Acceptance Criteria` | Tool appears in tool list and can be assigned to agents |

**7. Creation Confirmation**

| Field | Details |
|-------|---------|
| `Description` | System must confirm successful tool creation to user |
| `Response Content` | - Confirmation message<br>- Tool ID/name<br>- Next steps (how to use/assign) |
| `Acceptance Criteria` | User receives clear confirmation with actionable next steps |

**8. Error Handling**

| Field | Details |
|-------|---------|
| `Description` | System must handle errors gracefully during tool creation |
| `Error Types` | - Invalid tool name (duplicate, reserved words)<br>- Invalid parameter types<br>- Code generation failure<br>- Registration failure |
| `Acceptance Criteria` | User receives clear error message with suggested resolution |

---

## User Stories

**1. Basic Tool Creation**

- `As a` business user  
  `I want to` describe a tool I need in plain English  
  `So that` the system creates it without me writing code  

- Acceptance Criteria:

    User can describe tool in natural language
    System extracts specifications automatically
    Tool is created and registered successfully

**2. Guided Tool Creation**

- `As a` user unfamiliar with tool requirements  
  `I want to` be guided through the tool creation process  
  `So that` I don't miss any required information  

- Acceptance Criteria:

    System asks for missing required fields
    Questions are clear and non-technical
    Process feels conversational, not form-like

**3. Review Before Creation**

- `As a` user  
  `I want to` review the tool specifications before creation  
  `So that` I can catch any misunderstandings  

- Acceptance Criteria:

    Summary is presented before final creation
    User can confirm or request changes
    Changes can be made without starting over

**4. Immediate Tool Availability**

- `As a` developer  
  `I want` created tools to be immediately available  
  `So that` I can assign them to agents right away  

- Acceptance Criteria:

    Tool appears in tool list within seconds of creation
    Tool can be assigned to agents immediately
    No server restart required

---

## Tool Chatbot Interface

The Tool Chatbot provides an intelligent assistant to help with tool code generation, explanation, and management directly within the tool creation interface.

**Key Capabilities:**

**1. Code Generation**

The chatbot can generate tool code based on natural language descriptions:

- Describe your tool requirements in plain English
- Specify the functionality, inputs, and expected outputs
- The chatbot generates complete, executable Python code
- Generated code appears in the code snippet block automatically

**2. Code Explanation**

When you have existing code in the code snippet block:

- The chatbot can explain what the code does line-by-line
- Ask questions like "Explain this code" or "What does this function do?"
- Get detailed breakdowns of logic, parameters, and return values
- Understand dependencies and potential improvements

**3. Code Restoration**

The chatbot maintains a version history of your code:

- An option to **restore old code** is available if you want to revert changes
- Easily switch back to previous versions if new changes don't work as expected
- Prevents accidental loss of working code during modifications

**How It Works:**

1. **Open the Chatbot** — Click the chat icon in the tool creation interface
2. **Describe Your Needs** — Type your request (generate, explain, or modify code)
3. **Review Generated Code** — The code appears in the code snippet block
4. **Iterate as Needed** — Ask follow-up questions or request modifications
5. **Restore if Needed** — Use the restore option to revert to previous code versions

**Example Use Cases:**

- "Generate a tool that fetches weather data for a given city"
- "Explain what this database connection code does"
- "Modify this function to handle error cases"
- "Add input validation to this tool"
- "Restore the previous version of this code"

!!! tip "Best Practice"
    Start with a clear description of what you want the tool to do. The more specific you are about inputs, outputs, and logic, the better the generated code will be.

---

## User Interface Requirements

**Chat Interface Behavior**

| State | UI Behavior |
|-------|-------------|
| `Intent Detected` | Show typing indicator, then confirmation message |
| `Gathering Info` | Display current progress (what's collected, what's needed) |
| `Summary Review` | Formatted card/box with tool specifications |
| `Creating` | Loading indicator with status message |
| `Success` | Success message with tool details and next steps |
| `Error` | Error message with clear explanation and retry option |

---

## Integration Points

**Existing Systems**

| System | Integration Type | Purpose |
|--------|-----------------|---------|
| IAF Chat API | API Call | Process user messages |
| Tool Service | API Call | Register new tools |
| LLM Service | API Call | Extract specs, generate code |


**API Endpoints Required**

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/tools/generate/pipeline/chat` | POST | Initiate tool creation from chat |


---

## Dependencies

| Dependency | Type | Status |
|------------|------|--------|
| LLM Model (GPT-4o or equivalent) | Required | Available |
| IAF Tool Service | Required | Available |
| Chat Infrastructure | Required | Available |

---

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation |
|------|--------|-------------|------------|
| LLM generates invalid code | High | Medium | Code validation layer, syntax checking |
| Duplicate tool names | Medium | Medium | Pre-creation uniqueness check |
| User provides incomplete info | Medium | High | Guided clarification dialogue |
| Generated tool has security issues | High | Low | Code sanitization, dangerous operation blocking |

---

## Acceptance Criteria Summary

The feature is complete when:

- Users can create tools by describing them in natural language
- System correctly extracts tool specifications from conversation
- Missing information is requested through clarifying questions
- User can review and confirm specifications before creation
- Valid Python code is generated with proper structure
- Tool is registered and immediately available for use
- Errors are handled gracefully with clear messages
- All validation rules are enforced

---

## Sample Conversation Flow

```
User: I want to create a tool.  
System: What type of tool would you like to create?  

User: I want to create an addition tool that will add 2 numbers.  
System: Great! What input parameters will the tool require?  

User: The tool will need two input parameters:  
  - `num1` (float): The first number to add  
  - `num2` (float): The second number to add  

System: Got it. What should the tool return as output?  

User: The tool should return the sum of the two numbers as a float.  

System: Here's the generated Python code snippet:  

```python
def add_numbers(num1: float, num2: float) -> float:
    """
    Adds two numbers and returns their sum.

    Args:
        num1 (float): The first number.
        num2 (float): The second number.

    Returns:
        float: The sum of num1 and num2.
    """
    return num1 + num2


System: Does this look good to you? If confirmed, we will validate the code and save it into the IAF. 

```

## Example Generated Code

```python
def add_numbers(num1: float, num2: float) -> float:
    """
    Adds two numbers and returns their sum.

    Args:
        num1 (float): The first number.
        num2 (float): The second number.

    Returns:
        float: The sum of num1 and num2.
    """
    return num1 + num2
```

---