# 🚀 API Response Formats Documentation
## Complete Guide for UI Development

This document provides comprehensive documentation of all response formats returned by the Infosys Agent Framework APIs. This will serve as the definitive reference for UI development teams to implement proper response handling and display logic.

---

## 📋 Table of Contents

1. [Main Chat Inference Response](#main-chat-inference-response)
2. [Streaming Response Format (SSE)](#streaming-response-format-sse)
3. [Tool Interaction Responses](#tool-interaction-responses)
4. [Feedback Response Formats](#feedback-response-formats)
5. [Agent Evaluation Responses](#agent-evaluation-responses)
6. [Error Response Formats](#error-response-formats)
7. [Chat History Response](#chat-history-response)
8. [Memory Management Responses](#memory-management-responses)
9. [Session Management Responses](#session-management-responses)

---

## 🎯 Main Chat Inference Response

### 📍 Endpoint: `POST /chat/inference` & `POST /chat/v2/inference`

This is the primary response format returned when an agent completes processing a user query.

### 🏗️ Complete Response Structure

```json
{
  "epoch": 1,
  "query": "what is 30+9*90",
  "errors": [],
  "response": "The answer is: 840.",
  "model_name": "gpt-4o",
  "preference": "",
  "session_id": "test_12345678901",
  "context_flag": true,
  "end_timestamp": "2025-10-14T13:13:49.388573",
  "tool_feedback": "yes",
  "critique_points": [
    "The response correctly calculated the expression...",
    "The final answer was presented clearly...",
    "The response could be improved by providing..."
  ],
  "start_timestamp": "2025-10-14T13:10:18.923191",
  "evaluation_score": null,
  "executor_messages": [
    {
      "content": "hi",
      "additional_kwargs": {},
      "response_metadata": {},
      "type": "human",
      "name": null,
      "id": "369f8fe8-79c1-4161-a737-0638a9cd2fda",
      "example": false,
      "role": "user_query",
      "response_time": 15.23
    },
    {
      "content": "The answer is: 840.",
      "additional_kwargs": {},
      "response_metadata": {},
      "type": "ai",
      "name": null,
      "id": "f79d3cef-c394-415e-9f01-d3e770bdb3c5",
      "example": false,
      "tool_calls": [],
      "invalid_tool_calls": [],
      "usage_metadata": null
    }
  ],
  "workflow_description": "use all the tool to complete any maths operation and get the final answer",
  "agentic_application_id": "e3cb950e-ba71-4170-8e01-f7445215b996",
  "response_quality_score": 0.9,
  "response_formatting_flag": true,
  "past_conversation_summary": "Summary:\n\nThe user initiated the conversation..."
}
```

### 📝 Field Descriptions

#### **Core Response Fields**
| Field | Type | Description | UI Usage |
|-------|------|-------------|----------|
| `response` | `string` | The main response content from the agent | **Display as primary response text** |
| `query` | `string` | Original user query that was processed | Show as conversation context |
| `model_name` | `string` | LLM model used (e.g., "gpt-4o", "claude-3") | Display in response metadata |
| `session_id` | `string` | Unique identifier for conversation session | Use for session management |
| `agentic_application_id` | `string` | UUID of the agent that processed the request | Agent identification |

#### **Timing & Performance**
| Field | Type | Description | UI Usage |
|-------|------|-------------|----------|
| `start_timestamp` | `string` | ISO timestamp when processing began | Calculate response duration |
| `end_timestamp` | `string` | ISO timestamp when processing completed | Calculate response duration |
| `response_time` | `number` | Processing time in seconds (in executor_messages) | **Show response time to users** |

#### **Quality Assessment**
| Field | Type | Description | UI Usage |
|-------|------|-------------|----------|
| `response_quality_score` | `number` | Quality score from 0.0 to 1.0 | **Display quality indicator** |
| `critique_points` | `array[string]` | Detailed feedback points about response quality | Show detailed feedback |
| `evaluation_score` | `number/null` | Evaluation score if evaluation_flag was enabled | Additional quality metric |

#### **Conversation Context**
| Field | Type | Description | UI Usage |
|-------|------|-------------|----------|
| `executor_messages` | `array[object]` | Complete conversation history with metadata | **Render conversation thread** |
| `past_conversation_summary` | `string` | AI-generated summary of previous conversation | Context tooltip/sidebar |
| `preference` | `string` | User preferences extracted from conversation | Personalization display |

#### **Configuration Flags**
| Field | Type | Description | UI Usage |
|-------|------|-------------|----------|
| `context_flag` | `boolean` | Whether conversation context was used | Debug information |
| `response_formatting_flag` | `boolean` | Whether response formatting was applied | Determine rendering mode |
| `tool_feedback` | `string` | Tool execution feedback status | Tool interaction status |

#### **Processing Information**
| Field | Type | Description | UI Usage |
|-------|------|-------------|----------|
| `epoch` | `number` | Number of processing iterations | Show refinement count |
| `errors` | `array[string]` | Any errors encountered during processing | **Error handling & display** |
| `workflow_description` | `string` | Description of agent's workflow/capabilities | Agent information display |

---

## 🌊 Streaming Response Format (SSE)

### 📍 Endpoint: `POST /chat/v2/inference` (with streaming enabled)

When streaming is enabled, responses arrive as Server-Sent Events (SSE) with different message types.

### 🏗️ Streaming Message Types

#### **1. Node Status Updates**
```json
{
  "Node Name": "Generate Past Conversation Summary",
  "Status": "Started"
}
```
```json
{
  "Node Name": "Generate Past Conversation Summary",
  "Status": "Completed"
}
```

**UI Usage:** Show processing progress indicators, workflow visualization

#### **2. Tool Execution Notifications**
```json
{
  "Node Name": "Tool Call",
  "Status": "Started",
  "Tool Name": "multiply_two_numbers",
  "Tool Arguments": {
    "a": 9,
    "b": 90
  }
}
```
```json
{
  "Tool Name": "multiply_two_numbers",
  "Tool Output": "810"
}
```
```json
{
  "Node Name": "Tool Call",
  "Status": "Completed",
  "Tool Name": "multiply_two_numbers"
}
```

**UI Usage:** Show tool execution progress, display tool inputs/outputs

#### **3. Raw Processing Data**
```json
{
  "raw": {
    "Critic Score": 0.9
  }
}
```
```json
{
  "raw": {
    "Critique Points": [
      "The response correctly calculated...",
      "The final answer was presented clearly..."
    ]
  }
}
```

**UI Usage:** Real-time quality feedback, detailed processing insights

#### **4. Decision Points**
```json
{
    "raw": {
        "analysing": "Moving to final response as response feels fine"
    }
}
```

**UI Usage:** Show AI decision-making process, workflow transparency

#### **5. Tool Verification Requests**
```json
{
    "raw": {
        "tool_verifier": "Please Confirm me for executing the tool"
    }
}
```

**UI Usage:** **Prompt user for tool execution approval**

---

## 🔧 Tool Interaction Responses

### Tool Execution with Human-in-the-Loop

When `tool_verifier_flag` is enabled, the system will pause for user confirmation before executing tools.

#### **Tool Approval Request Format**
```json
{
  "tool_verifier": "Please Confirm me for executing the tool",
  "Node Name": "Tool Call",
  "Status": "Started",
  "Tool Name": "send_email",
  "Tool Arguments": {
    "to": "user@example.com",
    "subject": "Meeting Reminder",
    "body": "Don't forget about our meeting tomorrow"
  }
}
```

#### **Expected User Response**
- `"yes"` - Approve tool execution
- JSON string with modified arguments - Modify and execute
- Any other text - Reject execution

#### **Tool Execution Results**
```json
{
  "Tool Name": "send_email",
  "Tool Output": "Email sent successfully"
}
```

**UI Implementation:**
1. Display tool details in a confirmation dialog
2. Show tool arguments in an editable format
3. Provide approve/reject/modify options
4. Display execution results

---

## 💬 Feedback Response Formats

### 📍 Endpoint: `POST /chat/get/feedback-response/{feedback_type}`

#### **Like Feedback Response**
```json
{
  "status": "success",
  "message": "Feedback recorded successfully",
  "feedback_type": "like"
}
```

#### **Regenerate Response**
Returns the same format as [Main Chat Inference Response](#main-chat-inference-response) but with regenerated content.

#### **Submit Feedback Response**
Returns the same format as [Main Chat Inference Response](#main-chat-inference-response) but incorporates user feedback.

**UI Usage:** Show feedback confirmation, update UI state, display improved response

---

## 📊 Agent Evaluation Responses

When `evaluation_flag` is enabled, responses include detailed evaluation metrics.

### 🏗️ Evaluation Data Structure

```json
{
  "evaluation_score": 0.85,
  "evaluation_feedback": "**Fluency Feedback:** The response is well-structured...\n\n**Relevancy Feedback:** Directly addresses the query...",
  "executor_messages": [
    {
      "content": [
        {
          "evaluation_score": 0.85,
          "evaluation_details": {
            "fluency_evaluation": {
              "fluency_rating": 0.9,
              "feedback": "The response is well-structured and easy to understand"
            },
            "relevancy_evaluation": {
              "relevancy_rating": 0.8,
              "feedback": "Directly addresses the user's query"
            },
            "coherence_evaluation": {
              "coherence_score": 0.85,
              "feedback": "Response flows logically"
            },
            "groundedness_evaluation": {
              "groundedness_score": 0.85,
              "feedback": "Well-grounded in factual information"
            }
          },
          "feedback": "Compiled feedback from all dimensions"
        }
      ],
      "role": "evaluator-response"
    }
  ]
}
```

### 📝 Evaluation Metrics

| Metric | Range | Description | UI Display |
|--------|-------|-------------|------------|
| `fluency_rating` | 0.0-1.0 | Language quality and readability | Fluency score bar |
| `relevancy_rating` | 0.0-1.0 | How well response addresses query | Relevancy score bar |
| `coherence_score` | 0.0-1.0 | Logical flow and consistency | Coherence score bar |
| `groundedness_score` | 0.0-1.0 | Factual accuracy and reliability | Groundedness score bar |
| `evaluation_score` | 0.0-1.0 | Overall aggregate score | **Main quality indicator** |

**UI Usage:** Create quality dashboard, show detailed feedback, quality trend tracking

---

## ❌ Error Response Formats

### 🏗️ Error Response Structure

#### **Validation Errors (400)**
```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "agentic_application_id"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

#### **Not Found Errors (404)**
```json
{
  "detail": "Agentic Application ID abc123 not found."
}
```

#### **Internal Server Errors (500)**
```json
{
  "detail": "Internal Server Error: Database connection failed"
}
```

#### **Concurrent Request Errors (499)**
```json
{
  "detail": "Parallel inference requests are not allowed for this session. Previous request is still processing."
}
```

#### **Response with Errors (200 with errors field)**
```json
{
  "response": "I encountered some issues but here's what I could determine...",
  "errors": [
    "Error Occurred in Executor Agent: Tool 'weather_api' is temporarily unavailable",
    "Warning: Falling back to cached data"
  ],
  "query": "What's the weather like today?",
  // ... other response fields
}
```

**UI Error Handling:**
1. Display appropriate error messages
2. Show retry options for transient errors
3. Provide helpful guidance for validation errors
4. Implement graceful degradation for partial failures

---

## 📚 Chat History Response

### 📍 Endpoint: `POST /chat/get/history`

```json
{
  "history": [
    {
      "human_message": "Hello, how are you?",
      "ai_message": "I'm doing well, thank you! How can I assist you today?",
      "timestamp": "2025-01-14T10:30:00Z",
      "message_id": "msg_001",
      "response_time": 2.5
    },
    {
      "human_message": "What's 2+2?",
      "ai_message": "2 + 2 = 4",
      "timestamp": "2025-01-14T10:31:15Z",
      "message_id": "msg_002",
      "response_time": 1.2
    }
  ],
  "total_messages": 4,
  "session_metadata": {
    "session_id": "user@example.com",
    "agent_id": "math_agent_001",
    "created_at": "2025-01-14T10:30:00Z",
    "last_activity": "2025-01-14T10:31:15Z"
  }
}
```

**UI Usage:** Render conversation history, show timestamps, display performance metrics

---

## 🧠 Memory Management Responses

### 📍 Store Example: `POST /chat/memory/store-example`

#### **Success Response**
```json
{
  "success": true,
  "message": "Successfully stored interaction as positive example",
  "stored_as": "positive"
}
```

#### **Duplicate Detection**
```json
{
  "success": false,
  "message": "Duplicate interaction detected. Cannot store - this query-response pair already exists",
  "stored_as": null
}
```

#### **Invalid Interaction**
```json
{
  "success": false,
  "message": "Cannot store example: Query and response are identical (invalid interaction)",
  "stored_as": null
}
```

### 📍 Get Examples: `GET /chat/memory/get-examples/`

```json
{
  "user_id": "agent_123",
  "total_examples": 5,
  "examples": [
    {
      "key": "example_001",
      "query": "Calculate compound interest",
      "response": "To calculate compound interest, use the formula A = P(1 + r/n)^(nt)...",
      "label": "positive",
      "tool_calls": ["calculator", "formula_helper"],
      "timestamp": "2025-01-14T09:00:00Z",
      "usage_count": 3
    }
  ]
}
```

**UI Usage:** Memory management interface, example quality indicators, usage analytics

---

## 🔄 Session Management Responses

### 📍 Clear History: `DELETE /chat/clear-history`

#### **Success Response**
```json
{
  "status": "success",
  "message": "Chat history cleared successfully for session user@example.com"
}
```

#### **Error Response**
```json
{
  "status": "error",
  "message": "Session not found or already cleared"
}
```

### 📍 New Session: `GET /chat/get/new-session-id`

```json
"user@example.com_20250114_103045_abc123"
```

### 📍 Old Conversations: `POST /chat/get/old-conversations`

```json
{
  "session_001": [
    {
      "human_message": "Previous question 1",
      "ai_message": "Previous answer 1",
      "timestamp": "2025-01-13T14:20:00Z"
    }
  ],
  "session_002": [
    {
      "human_message": "Previous question 2",
      "ai_message": "Previous answer 2",
      "timestamp": "2025-01-12T16:45:00Z"
    }
  ]
}
```

**UI Usage:** Session history navigation, conversation restoration, session analytics

---

## 💡 UI Implementation Guidelines

### 🎨 **Display Priorities**

1. **Primary Content:** `response` field - main agent response
2. **Secondary Info:** Quality scores, timing, tool interactions
3. **Metadata:** Session info, agent details, configuration flags
4. **Debug Info:** Error arrays, processing details, workflow information

### 🚦 **Status Indicators**

- **Processing:** Show node status updates during streaming
- **Quality:** Visual indicators for response_quality_score (0.7+ = good)
- **Errors:** Clear error states with retry options
- **Tools:** Interactive tool approval/modification interfaces

### 📱 **Responsive Considerations**

- **Mobile:** Focus on core response, collapse metadata
- **Desktop:** Full detail view with expandable sections
- **Progressive Enhancement:** Start with basic response, add details as they arrive

### 🔄 **Real-time Updates**

- **Streaming:** Progressive rendering of response components
- **Status Updates:** Live workflow progress indicators  
- **Error Handling:** Graceful degradation and retry mechanisms

### 🎯 **User Interaction Points**

1. **Tool Approval:** Interactive dialogs for tool execution
2. **Feedback:** Like/dislike, regenerate, detailed feedback options
3. **Quality Review:** Expandable evaluation details
4. **Memory Management:** Store examples, review stored interactions
5. **Session Control:** Clear history, switch conversations

---

## 🔧 Implementation Examples

### React Component Structure Example

```jsx
// Main Response Component
const AgentResponse = ({ responseData }) => {
  return (
    <div className="agent-response">
      <ResponseHeader 
        model={responseData.model_name}
        quality={responseData.response_quality_score}
        responseTime={responseData.executor_messages?.[0]?.response_time}
      />
      <ResponseContent content={responseData.response} />
      <ResponseActions 
        onLike={() => handleFeedback('like')}
        onRegenerate={() => handleFeedback('regenerate')}
        onFeedback={(text) => handleFeedback('submit_feedback', text)}
      />
      {responseData.errors?.length > 0 && (
        <ErrorDisplay errors={responseData.errors} />
      )}
    </div>
  );
};

// Streaming Handler Example
const useStreamingResponse = (sessionId) => {
  const [streamData, setStreamData] = useState([]);
  
  useEffect(() => {
    const eventSource = new EventSource(`/chat/v2/inference?session=${sessionId}`);
    
    eventSource.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data["Node Name"]) {
        updateProcessingStatus(data);
      } else if (data["Tool Name"]) {
        updateToolExecution(data);
      } else if (data.raw) {
        updateRawData(data.raw);
      }
    };
    
    return () => eventSource.close();
  }, [sessionId]);
};
```

This documentation provides all the necessary information for UI teams to implement comprehensive interfaces that handle all aspects of the Infosys Agent Framework API responses. Each response format includes specific UI usage guidance to ensure optimal user experience.