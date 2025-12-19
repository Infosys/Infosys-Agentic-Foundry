## 1. Semantic Memory

Semantic memory is a core component of agent intelligence, enabling agents to store, recall, and utilize facts or information provided by users across sessions. This persistent memory allows agents to deliver more personalized, context-aware, and efficient interactions.

During agent onboarding, the model generates a system prompt for each agent. This system prompt includes the agent's goal, workflow description, and a dynamically generated list of tools required for the agent's operation. By default, the system prompt now also includes the Manage Memory and Search Memory tools, ensuring that every agent is equipped with semantic memory capabilities from the outset.

**Purpose**

Semantic memory is designed for storing facts, preferences, or contextual information shared by the user for future reference and retrieval.

By leveraging semantic memory, agents can:

- Remember user-provided details (e.g., preferences, important facts)
- Reference past interactions to provide continuity and relevance
- Reduce repetitive questioning and improve user experience

**Implementation**

Semantic memory in Agentic Foundry is implemented using two specialized tools:


**1. Manage Memory Tool**

- **Function:** Stores facts or information shared by the user during conversations.
- **Trigger:** In chat inference, when a user interacts with the agent and provides a query containing facts or information, the agent automatically calls the Manage Memory Tool and stores this information in long-term memory.
- **Storage:**
    - The implementation uses Redis cache for fast, in-memory storage and a Postgres database for persistent storage.
    - User interactions are initially stored in Redis, which provides low-latency access and efficient indexing for quick retrieval during active sessions.
    - When a defined threshold (such as memory size or time interval) is reached, Redis synchronizes its data with the Postgres database, ensuring long-term persistence and durability.
    - All new entries are first written to Redis; updates and deletions are performed on both Redis and Postgres to maintain consistency across the in-memory and persistent layers.
    - This hybrid approach ensures that frequently accessed or recently updated information is quickly available, while all critical data is reliably stored in Postgres for future reference and compliance.
    - Information is indexed by user ID, session, or semantic tags to support efficient search and retrieval operations.
!!! Example "Example Use Cases"
    - Remembering a user's preferred tool or configuration
    - Storing important project or workflow details


**2. Search Memory Tool**

- **Function:** Retrieves previously stored information to answer user queries.
- **Trigger:** The agent calls this tool when the user asks questions related to previously stored information, or when relevant context is needed for reasoning.
- **Operation:** The tool searches stored memory using semantic similarity, enabling retrieval of relevant facts even if the query is phrased differently from the original input.
!!! Example "Example Use Cases"
    - Answering questions about previously shared preferences or project details
    - Providing reminders or recalling key information from earlier sessions

**Semantic Memory in All Agent Templates**

All six agent templates **React**, **React Critic**, **Planner Executor Critic**, **Planner Critic**, **Meta**, and **Planner Meta** have semantic memory implemented. This ensures that regardless of the agent type, the ability to remember and retrieve user-specific information is always available. Each template is configured to:

- Capture and store relevant user data using the Manage Memory Tool
- Retrieve and utilize stored information via the Search Memory Tool
- Maintain context and continuity across sessions and conversations

During agent onboarding, these tools are integrated into the system prompt and configuration, ensuring seamless access to semantic memory features for all agent types.

---

## 2. Episodic Memory

Episodic memory is a foundational capability implemented across all agent templates. It enables agents to learn from past conversational experiences by storing and utilizing specific query-response examples. This supports few-shot learning, allowing agents to improve future responses based on real user interactions and feedback, and to adapt dynamically to user preferences and expectations.

**Purpose**

The primary objective of episodic memory is to enhance agent learning and adaptability by capturing conversational examples—both positive and negative. These examples inform and refine future agent behavior, resulting in more context-aware, user-aligned, and effective responses.

**Automatic Conversation Analysis**

Episodic memory also supports automatic extraction and storage of conversational examples without explicit user feedback. This approach is implemented for all agent templates and leverages both short-term memory and LLM-based analysis:

- The system maintains a short-term memory buffer, typically containing the latest four conversations.
- When analyzing for learning opportunities, the system makes an LLM call to process these recent conversations and extract appropriate query-to-final-response pairs.
- The analysis focuses on identifying explicit or implicit user feedback (positive or negative) and links it to the original, meaningful user query and the final AI response that was evaluated.
- Only substantive queries are considered; clarifications, format requests, and meta-requests are ignored.
- Tool usage patterns from successful interactions are preserved for future learning.

**Conversation Analysis Criteria**

- **Positive Indicators:** Explicit signals (e.g., "helpful", "thank you", "good"), engagement, or resolution.
- **Negative Indicators:** Explicit negatives (e.g., "wrong", "not correct"), rejections, corrections, or signs of dissatisfaction.
- **No Feedback:** If the user moves on without evaluative feedback, the pair is ignored.

**Similarity Scoring and Example Retrieval**

To retrieve the most relevant examples from episodic memory, the system employs advanced similarity scoring techniques:

- **Bi-Encoders:** Used to generate embeddings for both stored examples and the incoming user query, enabling efficient retrieval of candidate examples based on vector similarity in the embedding space.
- **Cross-Encoders:** Applied to the top candidate examples for more precise, context-aware similarity scoring between the user query and stored examples. This ensures that the most contextually relevant positive and negative examples are selected for few-shot learning.

By leveraging bi-encoders and cross-encoders, the agent can accurately identify and utilize examples that are most similar to the current user query, resulting in more effective and contextually appropriate responses.

**Learning Application and Continuous Improvement**

- **Positive Example Usage:**
	- The agent follows successful response formats, tool usage, and explanation styles from positive examples.
- **Negative Example Learning:**
	- The agent avoids unsuccessful approaches, prevents repeated errors, and develops alternative strategies for similar contexts.

**Retrieval and Application Process**

1. The new user query is analyzed for similarity to stored examples.
2. The system finds relevant positive and negative examples using similarity scoring.
3. Retrieved examples are formatted as guidance context for the agent.
4. The agent uses these examples to inform response style, tool selection, and approach.
5. Each new interaction becomes a potential example for future learning, supporting continuous improvement and adaptation.

**Manual Feedback System**

The chat inference interface allows users to provide feedback on each AI response. Users can mark a response as positive or negative, which stores the current query-response pair as a positive or negative example. If the same feedback is clicked again, the stored example is deleted. Switching feedback updates the example type. The system processes these actions through backend API calls and provides visual feedback to indicate the current state. This mechanism helps the agent learn from user preferences and improve future responses.

**Episodic Memory Chat Inference**

The following example illustrates how episodic memory operates during chat inference:

- The user submits a query and then requests the response in a specific format (e.g., JSON).
- The system stores the original query and the final response (in JSON) as an episodic example, based on explicit user satisfaction.
- For subsequent queries, if a similar context is detected, the agent references the stored example:
	- If the previous example was positive, the agent follows the same response format.
	- If the previous example was negative, the agent avoids generating a similar response.