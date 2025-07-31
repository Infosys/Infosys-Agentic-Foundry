# Chat Screen Revamp PRD: AskAssistant2.jsx, ChatInput, ChatBubble

## Objective

Revamp the chat screen by migrating from `AskAssistant.jsx` to `AskAssistant2.jsx` with the following goals:
- **Clearer logic and conditional rendering**
- **Modular, reusable components for chat bubbles and input**
- **Improved UI/UX**
- **Robust handling of all chat variations and states**
- **Subtle in-chat loader for async operations**
- **Accurate error fallback and toast notifications**
- **Consistent disabling of inputs during processing**

---

## Chat Variations & Conditions

### 1. **Agent Type Variations**
- **PLANNER_META_AGENT**: Plan steps, feedback, continue button, special plan handling.
- **CUSTOM_TEMPLATE**: Custom plan steps, feedback UI.
- **REACT_AGENT / MULTI_AGENT**: Standard chat, feedback buttons, plan handling.
- **META_AGENT**: Coordination and orchestration messages.

### 2. **Tool Interrupt**
- If `toolInterrupt` is true and `isHuman` is false and no `additional_details`, show error fallback.
- If `toolInterrupt` is true and `isHuman` is true, show plan feedback/input UI.

### 3. **Human-in-the-Loop**
- If `isHuman` is true, show plan feedback/input UI for plans.
- If `isHuman` is false, show standard bot chat and feedback UI.

### 4. **Message vs Plan Data**
- **data.message !== ""**: Render bot response, possibly with plan steps.
- **data.message === "" & data.plan.length > 0**: Render plan steps and feedback UI.
- **data.message === "" & additional_details present**: Render tool argument editing UI.
- **data.message === "" & additional_details missing & toolInterrupt**: Show error message.

### 5. **Feedback UI**
- Feedback buttons (like/dislike/regenerate) shown based on agentType, message, and plan.
- If feedback is "dislike", show feedback textarea and send button.

### 6. **Continue Button**
- For PLANNER_META_AGENT, show "continue..." button to proceed with plan.

### 7. **Loading/Processing States**
- Disable all inputs (chat, dropdowns, buttons) during loading, processing, or generating.
- Show a subtle loader inside the chat area (not full-page) until response is received.

### 8. **Error Handling**
- On error response, show fallback message in chat bubble and display toast notification.

### 9. **Editability**
- If editing tool arguments, show edit/send buttons and editable fields.

### 10. **Old Chats**
- If old chats exist, adjust rendering logic (e.g., placeholder not shown).

### 11. **lastIndex**
- Many UI elements (feedback, plan, edit, etc.) only shown for the last message in the chat.

### 12. **likeIcon**
- If `likeIcon` is true, some feedback buttons are hidden for messages with empty text.

---

## Componentization & Modularization

### **ChatBubble**
- Handles rendering of each chat message (bot/user/plan/error).
- Accepts props for type, content, steps, tools, feedback state, error state, etc.
- Handles feedback actions (like/dislike/regenerate) via callbacks.
- Handles plan steps and continue button modularly.
- Handles error fallback rendering.

### **ChatInput**
- Handles user input, agent/model/agent selection, and input state.
- Disables input during loading/processing/generating.
- Handles file upload, new chat, delete chat, live tracking actions.
- Modular dropdowns for agent/model selection.

### **Loader**
- Subtle loader shown inside chat area during async operations.

### **ToastMessage**
- Shows toast notifications for errors, feedback, and status updates.

---

## UI/UX Guidelines

- **Inputs and controls** are disabled whenever chat is loading, processing, or generating.
- **Loader** is shown inside chat area, not as a full-page overlay.
- **Error fallback** is shown as a chat bubble with a clear message and toast notification.
- **Feedback UI** is modular and only shown for relevant messages/plans.
- **Plan steps** and **continue button** are rendered modularly based on agent type and plan data.
- **Old chats/history** are accessible via a modular component.
- **UI styles** Stick with the minimal font size, spacing, padding,margin as  implemented in AskAssistant2, ChatBubble, etc..

---

## Summary Table

| Condition                                      | UI Variation                                      |
|------------------------------------------------|---------------------------------------------------|
| agentType === PLANNER_META_AGENT               | Plan steps, feedback, continue button             |
| agentType === CUSTOM_TEMPLATE                  | Custom plan steps, feedback UI                    |
| agentType === REACT_AGENT / MULTI_AGENT        | Standard chat, feedback buttons                   |
| toolInterrupt && !isHuman && !additional_details | Error fallback message                            |
| toolInterrupt && isHuman                       | Plan feedback/input UI                            |
| data.message === "" && data.plan.length > 0    | Plan steps and feedback UI                        |
| data.message === "" && additional_details      | Tool argument editing UI                          |
| Feedback === "dislike"                         | Feedback textarea and send button                 |
| PLANNER_META_AGENT && continueButton           | "continue..." button                              |
| Loading/Processing/Generating                  | Disable all inputs, show subtle loader            |
| Error Response                                 | Error fallback bubble, toast notification         |
| lastIndex                                      | Feedback/edit/plan UI only for last message       |
| likeIcon                                       | Hide feedback buttons for empty messages          |

---

## Implementation Checklist

- [ ] Modularize chat bubble rendering (ChatBubble)
- [ ] Modularize input and controls (ChatInput)
- [ ] Implement subtle loader in chat area
- [ ] Disable all inputs during async operations
- [ ] Implement error fallback and toast notifications
- [ ] Handle all agent, tool, human, plan, and feedback variations
- [ ] Avoid deeply nested/multiple if conditions; use clean props and state
- [ ] Ensure old chat/history and file upload are modular
- [ ] Document all props and state transitions for maintainability

---

## References

- Original `AskAssistant.jsx` and `MsgBox.jsx` logic
- Identified variations and conditions above

---

**This PRD should be used as the blueprint for the chat screen revamp, guiding the implementation of `AskAssistant2.jsx`, `ChatInput`, and `ChatBubble` components.**