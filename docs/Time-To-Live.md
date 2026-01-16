# Time-To-Live (TTL) Implementation

The Time-To-Live (TTL) feature is implemented to manage the lifecycle of both short-term and long-term memory records within the system. This ensures efficient storage management and compliance with data retention policies.

The agent conversation summary table maintains the `agent Id` and `session Id` for each chat session, storing a summary of the conversation. This table also includes an `updated on` column to track the last activity. If the `updated on` timestamp for a record is older than 30 days, both the short-term and long-term memory records associated with that `agent Id` and `session Id` are deleted as part of the TTL process.

## Short-Term Memory (Checkpoints)

Short-term memory is managed through checkpoint tables (`checkpoints`, `checkpoint_writes`, and `checkpoint_blobs`). These checkpoints store chat history, which is displayed in the Inference Chat History tab.

**Deletion Policy**

- `Checkpoints older than 30 days` are automatically deleted from the database.
- Before deletion, records are moved to the `Recycle`, where they are retained for 15 days. During this period, records can be restored if needed.

## Long-Term Memory

For each agent, a dedicated table is created upon onboarding to store all long-term chat history. When checkpoints are deleted, the corresponding long-term chat history is also removed to maintain consistency.

**Deletion Policy**

- `Long-term chat history older than 30 days` is deleted from the database.
- Deleted records are first moved to the `Recycle` and kept for 15 days, allowing for restoration within this window.

## Tools and Agents

TTL is also applied to tools and agents:

- When a tool or agent is deleted, it is moved to the `Recycle Bin`.
- After 15 days in the Recycle Bin, the tool or agent is permanently deleted, including the removal of the agent's table from the database.

**Recycle Manager**

The Recycle Manager acts as a holding area for deleted records (checkpoints, long-term records, tools, and agents). All items remain in the recycle area for `15 days` before permanent deletion. Restoration is possible during this period based on the number of days since deletion.

## Automated Cleanup with Scheduler

A daily task scheduler (cron job) is implemented to automate the cleanup process:

- The cleanup script runs daily at 3 AM, ensuring timely deletion and recycling of records according to the TTL policies.

---

**Summary of TTL Policies:**

1. **Short-term memory (checkpoints):** Deleted after 30 days, retained in recycle for 15 days.
2. **Long-term memory (chat history):** Deleted after 30 days, retained in recycle for 15 days.
3. **Tools & agents:** Moved to recycle bin on deletion, permanently deleted after 15 days.
4. **Automated cleanup:** Scheduled daily at 3 AM.

This TTL implementation ensures efficient data management, reduces storage overhead, and provides a safety net for accidental deletions through the recycle manager.
