# Chat UI

The main chat stream shows user messages, assistant responses, routing/status
messages, HITL prompts, tool activity that requires user attention, and errors.

Provider reasoning events such as native reasoning previews and continuity
markers are not rendered as chat cards. They are routed to the right-side
reasoning panel so the conversation remains business-focused while diagnostics
remain available for debugging.

When an assistant response includes a fenced `skill_component` JSON block, the
chat UI loads the matching skill-local `component.html` from
`/api/skills/{skill}/component`, substitutes the provided props into
`{{placeholder}}` values, and renders the editable card inline. Informational
answers do not show a component unless the skill explicitly emits that block.

When an approval you are waiting on is resolved — including by an administrator in
the Command Center — the chat updates in real time over the same `/ws/chat`
socket: an `hitl_approval_resolved` event clears the inline Approve/Reject buttons
for that request and shows a toast with the outcome (approved/rejected) and who
decided it. This arrives immediately at resolve time, ahead of any final answer
produced by the background resume, so an urgent decision is never left with the
buttons hanging and no feedback.

When `RL_CAPTURE=true`, the server passively records completed chat turns into
the tenant RL/eval database through the neutral capture bridge. Assistant
response payloads include `rl_trajectory_id` and `rl_model_call_id` so
thumbs/correction actions can target the exact captured answer, but these IDs
are not rendered as visible chat cards.

For local manual testing with `AUTH_ENABLED=false`, the chat WebSocket uses a dev
identity when the browser has no token or still sends an expired token from a
previous authenticated session.

When `AUTH_ENABLED=true`, the chat shell redirects unauthenticated browsers to
`/login` by probing the protected `/auth/me` endpoint. After login, the user
avatar menu appears in the top bar and exposes the Sign Out action, which clears
the Studio token/session and, for SSO users, follows the Keycloak logout URL.

The conversation sidebar is backed by the tenant agent's persisted
`memory/history` JSONL files and `knowledge_index.db` session index. On refresh,
the chat page restores the active conversation when available, otherwise it opens
the most recent sidebar session. In local `AUTH_ENABLED=false` runs, conversation
listing honors the browser/query `user_id` so dev-mode history written as `demo`
remains visible after refresh.

Workstream progress sockets opened by the chat shell append
`iaf_access_token` to `/ws/workstreams/{name}`. Authenticated deployments verify
that token, tenant membership, and workstream read permission before sending
live progress; unauthenticated or unauthorized sockets are closed.
