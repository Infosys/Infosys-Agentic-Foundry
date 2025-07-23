CONVERSATION_SUMMARY_PROMPT = conversation_summary_prompt = """
Task: Summarize the chat conversation provided below in a clear, concise, and organized way.

Instructions:
1. Summarize the conversation: Provide a brief but clear summary of the chat. The summary should capture the main ideas and events of the conversation in an easy-to-read format.

2. Focus on key elements:
- Include the most important points discussed.
- Highlight any decisions made during the conversation.
- Mention any actions taken or planned as a result of the conversation.
- List any follow-up tasks that were discussed or assigned.

3. Be organized and avoid unnecessary details:
- Make sure the summary is well-structured and easy to follow.
- Only include relevant information and omit any minor or unrelated details.

Chat History - This is the full transcript of the conversation you will summarize. Focus on extracting the key points and relevant actions from this text.
Chat History:
{chat_history}
"""