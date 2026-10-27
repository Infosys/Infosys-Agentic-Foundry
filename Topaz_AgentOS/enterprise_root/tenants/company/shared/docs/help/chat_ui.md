# Chat UI Help

The main chat page is the primary AgentPro conversation surface. It supports multi-turn chat, skill routing, tool visibility, approvals, memory teaching, and Ask Twin.

## Ask Twin

Ask Twin is the bottom-right page-aware help assistant. It routes through the same chat pipeline as normal chat:

- WebSocket: `/ws/chat?token=<jwt>`
- HTTP fallback: `/api/chat`
- Forced skill: `iaf_guide`
- Adds `source_page` and `page_context` so the guide can answer for the current page

Ask Twin answers should be compact and suited to the narrow side panel.

## Chat Basics

- Press Enter to send and Shift+Enter for a newline.
- Use the skill selector to force a specific skill, or leave routing on auto.
- Use Fresh/Deep mode depending on whether the answer needs memory and context loading.
- Human Approval controls whether write operations pause for confirmation.

## Human Approval

When approval is enabled, the agent pauses before risky or write operations. Pending approvals also appear in Dashboard V2.

## Memory And Feedback

Users can teach facts, give thumbs feedback, and let the agent retrieve saved knowledge in future turns.

## Conversation History

Recent conversations are persisted in the tenant agent memory store and shown in the sidebar. Refreshing the chat page restores the active conversation when available, otherwise it opens the most recent stored session. In local dev mode with authentication disabled, the sidebar uses the same browser/query user id as chat so `demo` conversations remain visible after refresh.
