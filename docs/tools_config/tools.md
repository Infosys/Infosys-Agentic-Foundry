# Tools Configuration

## What Are Tools?

Tools are external functions or actions that an AI agent can call to perform tasks. it can't do with language alone—like searching the web, doing math, or querying a database.

Tools give the agent real-world abilities—they act like plugins or helpers that the agent can call when it needs to go beyond generating text.

Scenario: The AI agent is asked:
"What’s 1234 multiplied by 9876?"

* `Without a tool:` The agent might try to calculate it just by generating the answer with text prediction. It could get it wrong, especially with large numbers, since LLMs aren’t perfect at arithmetic.

* `With a tool:` We give the agent access to a calculator tool (a Python function).

```python
def multiply_numbers(x: int, y: int) -> int:
    return x * y
```

Now, when asked "What’s 1234 multiplied by 9876?"

The agent thinks: This looks like a math problem. I should use the multiply_numbers tool."
So it calls multiply_numbers(1234, 9876) and fetches the correct result .

## Tools Format

To maintain consistency and reliability, each tool should follow a standard format While onboarding .

* `Description:` A short explanation of what the tool does.
* `Code Block:` The tool’s logic, properly indented and syntactically correct.
* `Created By:` Email of the tool creator, used to prevent unauthorized edits.
* `Model:` Once the  model is selected, a doc string for the tool will be generated.
* `Domain Tags:` Optional labels (e.g., manufacturing, logistics) indicating the domain the tool applies to.



## Onboarding Tool

Let's proceed by using the example of onboarding a `Weather Information Retrieval Tool`.

**Step 1:** Provide a short description of the tool.

- Write a clear, concise description explaining what the tool does
- For example: "This tool retrieves current weather information for a specified location"

**Step 2:** Add the python tool code into code snippet.

- Write the complete Python function with proper syntax
- Include all necessary imports and dependencies
You can either paste the complete Python function directly into the code block or upload a `.py` file containing the tool code. The system will support both manual code entry and `.py` file uploads for onboarding tool logic.

**Step 3:** Specify the required model and enter your email.

- Select the appropriate AI model from the dropdown menu
- Enter your email address as the tool creator
- This email will be used for authorization when updating or deleting the tool

**Step 4:** Select the appropriate domain and click `Add Tool`.

- Choose relevant domain tags (e.g., Logistics, utilities, General)
- Review all entered information for accuracy
- Click the "Add Tool" button to complete the onboarding process


## Updating Tool

If we want to modify a tool that has already been onboarded, we must first ensure that the tool is not currently being referenced by any agent.  

If it is, remove the dependency before starting the update process. Once the tool has been updated, you can re-establish the dependency.

To update a tool, you must also provide the `creator email address`

**Step 1:** Select the Edit option from the tool management interface

**Step 2:** Make your desired changes to the tool configuration

**Step 3:** Enter the authorized creator's email ID 

**Step 4:** Click on `Update` to save your changes



## Deleting a Tool

If you want to delete an existing tool, make sure to first remove any dependencies from agents that are using it.  

Once all dependencies are cleared, you can proceed with deleting the tool.

To delete a tool, you must also provide the `creator email address`

**Step 1:** Select the Delete option from the tool management interface

**Step 2:** Enter the authorized creator's email ID 

**Step 3:** Click on `Delete` to permanently remove the tool


!!! warning "Important"
    Only the original creator of the tool has permission to update or delete it. Other users do not have access to modify or remove these resources.

## Tool File Storage

Tools are saved as files on the server during the onboarding and update process. This file-based storage approach ensures:

- **Persistence**: Tool code is stored as physical files on the server, aligned with database records
- **Update Support**: When a tool is updated, the corresponding file on the server is also updated
- **Delete Support**: When a tool is deleted, the file is removed from the server
- **Restore Support**: Deleted tools can be restored from the recycle bin, which also restores the associated tool file

!!! info

    This file management logic is synchronized with the database operations, ensuring consistency between the tool records in the database and the actual tool files on the server.