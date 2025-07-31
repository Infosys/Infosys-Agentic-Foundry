# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
import ast
import json
from typing import List, Dict, Any
from pydantic import BaseModel, Field

from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, ChatMessage
from langchain_core.output_parsers import JsonOutputParser, StrOutputParser

from telemetry_wrapper import logger as log



class InferenceUtils:
    """
    Utility class providing static methods for common inference-related tasks
    like JSON repair, output parsing, and message formatting.
    """

    @staticmethod
    async def json_repair_exception_llm(incorrect_json: str, exception: Exception, llm: Any) -> Dict[str, Any] | str:
        """
        Attempts to repair an incorrect JSON response using an LLM.

        Args:
            incorrect_json (str): The incorrect JSON response.
            exception (Exception): The exception raised when parsing the JSON.
            llm (LLM): The LLM to use for repairing the JSON.

        Returns:
            dict or str: The repaired JSON response as a dictionary or string.
            If the LLM fails to repair the JSON, the original incorrect JSON is returned.
        """
        class CorrectedJSON(BaseModel):
            """
            Represents a corrected JSON object.

            Attributes:
                repaired_json (Dict): The repaired JSON object.
            """
            repaired_json: Dict = Field(description="Repaired JSON Object")
        json_correction_parser = JsonOutputParser(pydantic_object=CorrectedJSON)
        json_repair_template = """JSON Response to repair:
{json_response}

Exception Raised:
{exception}

Please review and fix the JSON response above based on the exception provided. Return your corrected JSON as an object with the key "repaired_json":
```json
{{
    "repaired_json": <your_corrected_json>
}}
```
"""
        try:
            try:
                json_repair_prompt = PromptTemplate.from_template(json_repair_template, partial_variables={"format_instructions": json_correction_parser.get_format_instructions()})
                json_repair_chain = json_repair_prompt | llm | json_correction_parser
                repaired_json = await json_repair_chain.ainvoke({'json_response': incorrect_json, 'exception': exception})
                data = repaired_json['repaired_json']
                if isinstance(data, dict):
                    return data
                else:
                    try:
                        return json.loads(data)
                    except Exception as e0:
                        try:
                            return ast.literal_eval(data)
                        except Exception as e:

                            return data
            except Exception as e1:
                json_repair_prompt = PromptTemplate.from_template(json_repair_template)
                json_repair_chain = json_repair_prompt | llm | StrOutputParser()
                repaired_json = await json_repair_chain.ainvoke({'json_response': incorrect_json, 'exception': exception}).strip()
                repaired_json = repaired_json.replace('```json', '').replace('```', '')
                try:
                    try:
                        repaired_json_response = json.loads(repaired_json)
                    except Exception as e2:

                        repaired_json_response = ast.literal_eval(repaired_json)
                    return repaired_json_response['repaired_json']
                except Exception as e3:

                    return repaired_json
        except Exception as e4:
            return incorrect_json

    @staticmethod
    async def output_parser(llm: Any, chain_1: Any, chain_2: Any, invocation_input: Dict[str, Any], error_return_key: str = "Error") -> Dict[str, Any]:
        """
        Parses the output of a chain invocation, attempting to handle errors gracefully.
        """
        try:
            formatted_response = await chain_1.ainvoke(invocation_input)
        except Exception as e:
            try:
                formatted_response = await chain_2.ainvoke(invocation_input)
                formatted_response = formatted_response.replace("```json", "").replace("```", "").replace('AI:', '').strip()
                try:
                    formatted_response = json.loads(formatted_response)
                except Exception as e:
                    try:
                        formatted_response = ast.literal_eval(formatted_response)
                    except Exception as e:
                        try:
                            formatted_response = await InferenceUtils.json_repair_exception_llm(incorrect_json=formatted_response, exception=e, llm=llm)
                        except Exception as e:
                            formatted_response = {error_return_key: [f'{formatted_response}']}
            except Exception as e:
                formatted_response = {error_return_key: [f'Processing error: {e}.\n\nPlease try again.']}
        return formatted_response

    @staticmethod
    async def format_list_str(list_input: List[str]) -> str:
        """
        Formats a list into a string with each element on a new line.

        Args:
            list_input: The list to format.

        Returns:
            A string containing the formatted list.
        """
        frmt_text = "\n".join(list_input)
        return frmt_text.strip()

    @staticmethod
    async def format_past_steps_list(past_input_messages: List[str], past_output_messages: List[str]) -> str:
        """
        Formats past input and output messages into a string, with "Response:" prefix for output.

        Args:
            past_input_messages: A list of past input messages.
            past_output_messages: A list of past output messages.

        Returns:
            A string containing the formatted past messages.
        """
        msg_formatted = ""
        for in_msg, out_msg in zip(past_input_messages, past_output_messages):
            msg_formatted += in_msg + "\n" + f"Response: {out_msg}" + "\n\n"
        return msg_formatted.strip()

    @staticmethod
    async def add_prompt_for_feedback(query: str) -> ChatMessage | HumanMessage:
        """
        Helper to format user query or feedback into a ChatMessage.
        """
        if query == "[regenerate:][:regenerate]":
            prompt = "The previous response did not meet expectations. Please review the query and provide a new, more accurate response."
            return ChatMessage(role="feedback", content=prompt)
        elif query.startswith("[feedback:]") and query.endswith("[:feedback]"):
            prompt = f"""The previous response was not satisfactory. Here is the feedback on your previous response:
{query[11:-11]}

Please review the query and feedback, and provide an appropriate answer.
"""
            return ChatMessage(role="feedback", content=prompt)
        else:
            return HumanMessage(content=query, role="user_query")

    @staticmethod
    async def update_preferences(preferences: str, user_input: str, llm: Any) -> str:
        """
        Update the preferences based on user input.
        """
        prompt = f"""
Current Preferences:
{preferences}

User Input:
{user_input}


Instructions:
- Understand the User query, now analyze is the user intention with query is to provide feedback or related to task.
- Understand the feedback points from the given query and add them into the feedback.
- Inputs related to any task are not preferences. Don't consider them.
- If user intention is providing feed back then update the preferences based on below guidelines.
- Update the preferences based on the user input.
- If it's a new preference or feedback, add it as a new line.
- If it modifies an existing preference or feedback, update the relevant line with detailed preference context.
- User input can include new preferences, feedback on mistakes, or corrections to model behavior.
- Store these preferences or feedback as lessons to help the model avoid repeating the same mistakes.
- The output should contain only the updated preferences, with no extra explanation or commentary.
- if no preferences are there then output should is "no preferences available".

Examples:
user query: output should in markdown format
- the user query is related to preference and should be added to the preferences.
user query: a person is running at 5km per hour how much distance he can cover by 2 hours
- The user query is related to task and should not be added to the preferences.
user query: give me the response in meters.
- This is a perference and should be added to the preferences.
"""+"""
Output:
```json
{
"preferences": "all new preferences with new line as separator are added here"
}
```

"""
        response = await llm.ainvoke(prompt)
        response = response.content.strip()
        if "```json" in response:
            response = response[response.find("```json") + len("```json"):]
        response = response.replace('```json', '').replace('```', '').strip()
        try:
            final_response = json.loads(response)["preferences"]
        except json.JSONDecodeError:
            log.error("Failed to decode JSON response from model.")
            return response
        log.info("Preferences updated successfully")
        return final_response

    @staticmethod
    async def format_feedback_learning_data(data: list) -> str:
        """
        Formats feedback learning data into a structured string.

        Args:
            data (list): List of feedback learning data.

        Returns:
            str: Formatted feedback learning data string.
        """
        formatted_data = ""
        for item in data:
            formatted_data += f"question: {item['query']}\n"
            formatted_data += f"first_response: {item['old_steps']}\n"
            formatted_data += f"user feedback: {item['feedback']}\n"
            formatted_data += f"final approved response: {item['new_steps']}\n"
            formatted_data += "------------------------\n"
        log.info(f"Formatted Feedback Learning Data")
        return formatted_data.strip()


