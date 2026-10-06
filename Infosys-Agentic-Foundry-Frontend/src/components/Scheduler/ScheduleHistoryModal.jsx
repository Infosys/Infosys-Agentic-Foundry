import React, { useState, useEffect } from "react";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import Loader from "../commonComponents/Loader";
import styles from "./Scheduler.module.css";

const STATUS_ICON = {
  succeeded: "✓",
  failed: "✕",
  queued: "◦",
  dispatched: "▸",
};

const ScheduleHistoryModal = ({
  isOpen,
  onClose,
  jobId,
  scheduleName,
  onLoadHistory,
  onLoadDetail,
}) => {
  const [executions, setExecutions] = useState([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [selectedExec, setSelectedExec] = useState(null);
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    if (isOpen && jobId) {
      loadHistory();
    }
    return () => {
      setExecutions([]);
      setSelectedExec(null);
      setDetail(null);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, jobId]);

  const loadHistory = async () => {
    setLoading(true);
    try {
      const data = await onLoadHistory(jobId, { limit: 50 });
      setExecutions(data?.executions || []);
      setTotal(data?.total || 0);
    } catch {
      setExecutions([]);
    } finally {
      setLoading(false);
    }
  };

  const handleExecClick = async (exec) => {
    setSelectedExec(exec);
    setDetailLoading(true);
    try {
      const data = await onLoadDetail(jobId, exec.execution_id);
      setDetail(data);
    } catch {
      setDetail(null);
    } finally {
      setDetailLoading(false);
    }
  };

  const handleBack = () => {
    setSelectedExec(null);
    setDetail(null);
  };

  const getStatusClass = (status) => {
    switch (status) {
      case "succeeded": return styles.statusSucceeded;
      case "failed": return styles.statusFailed;
      default: return styles.statusQueued;
    }
  };

  const footer = selectedExec ? (
    <div className={styles.modalFooter}>
      <IAFButton type="secondary" onClick={handleBack}>
        ← Back to List
      </IAFButton>
      <IAFButton type="secondary" onClick={onClose}>
        Close
      </IAFButton>
    </div>
  ) : (
    <div className={styles.modalFooter}>
      <IAFButton type="secondary" onClick={onClose}>
        Close
      </IAFButton>
    </div>
  );

  return (
    <FullModal
      isOpen={isOpen}
      onClose={onClose}
      title={selectedExec ? "Execution Detail" : `History — ${scheduleName || jobId}`}
      headerInfo={!selectedExec ? [{ label: "Total Executions", value: total }] : undefined}
      footer={footer}
    >
      {selectedExec ? (
        detailLoading ? (
          <Loader />
        ) : (
          <ExecutionDetail exec={selectedExec} detail={detail} />
        )
      ) : loading ? (
        <Loader />
      ) : executions.length === 0 ? (
        <div className={styles.emptyState}>
          <div className={styles.emptyIcon}>—</div>
          <div className={styles.emptyText}>No executions recorded yet.</div>
        </div>
      ) : (
        <div className={styles.historyList}>
          {executions.map((exec) => (
            <div
              key={exec.execution_id}
              className={styles.historyItem}
              onClick={() => handleExecClick(exec)}
            >
              <div className={`${styles.historyStatus} ${getStatusClass(exec.status)}`}>
                {STATUS_ICON[exec.status] || "?"}
              </div>
              <div className={styles.historyMeta}>
                <div className={styles.historyMetaPrimary}>
                  {new Date(exec.scheduled_at).toLocaleString()}
                  {exec.error_message && (
                    <span style={{ color: "#ef4444", marginLeft: 8, fontSize: "0.75rem" }}>
                      {exec.error_message}
                    </span>
                  )}
                </div>
                <div className={styles.historyMetaSecondary}>
                  {exec.status} · task: {exec.task_id || "—"} · {exec.execution_id}
                </div>
              </div>
              <div className={styles.historyDuration}>
                {exec.duration_ms != null ? `${exec.duration_ms}ms` : "—"}
              </div>
            </div>
          ))}
        </div>
      )}
    </FullModal>
  );
};

const ChatMessage = ({ role, type, content }) => {
  const isUser = role === "user" || role === "human" || type === "human";
  return (
    <div className={`${styles.chatMessage} ${isUser ? styles.chatMessageUser : styles.chatMessageAssistant}`}>
      <div className={styles.chatRole}>{isUser ? "You" : "Assistant"}</div>
      <div className={styles.chatContent}>
        {typeof content === "string" ? content : JSON.stringify(content, null, 2)}
      </div>
    </div>
  );
};

const extractChatMessages = (merged) => {
  const ch = merged.chat_history;

  // chat_history is an object with executor_messages
  if (ch && typeof ch === "object" && !Array.isArray(ch)) {
    const execMsgs = ch.executor_messages;
    if (Array.isArray(execMsgs) && execMsgs.length > 0) {
      const msgs = [];
      execMsgs.forEach((em) => {
        if (em.user_query) msgs.push({ role: "user", content: em.user_query });
        if (em.final_response) msgs.push({ role: "assistant", content: em.final_response });
      });
      if (msgs.length > 0) return msgs;
    }
    // fallback to query/response inside chat_history object
    if (ch.query || ch.response) {
      const msgs = [];
      if (ch.query) msgs.push({ role: "user", content: ch.query });
      if (ch.response) msgs.push({ role: "assistant", content: ch.response });
      return msgs;
    }
  }

  // chat_history is an array
  if (Array.isArray(ch) && ch.length > 0) {
    return ch;
  }

  // top-level fallbacks
  if (Array.isArray(merged.messages) && merged.messages.length > 0) {
    return merged.messages;
  }
  if (Array.isArray(merged.executor_messages) && merged.executor_messages.length > 0) {
    const msgs = [];
    merged.executor_messages.forEach((em) => {
      if (em.user_query) msgs.push({ role: "user", content: em.user_query });
      if (em.final_response) msgs.push({ role: "assistant", content: em.final_response });
    });
    if (msgs.length > 0) return msgs;
  }
  if (merged.query || merged.response) {
    const msgs = [];
    if (merged.query) msgs.push({ role: "user", content: merged.query });
    if (merged.response) msgs.push({ role: "assistant", content: merged.response });
    return msgs;
  }
  return [];
};

const ExecutionDetail = ({ exec, detail }) => {
  const merged = { ...exec, ...detail };
  const chatHistory = extractChatMessages(merged);

  return (
    <div>
      <div className={styles.detailGrid}>
        <DetailItem label="Execution ID" value={merged.execution_id} />
        <DetailItem label="Status" value={merged.status} />
        <DetailItem label="Task ID" value={merged.task_id || "—"} />
        <DetailItem label="Session ID" value={merged.session_id || "—"} />
        <DetailItem
          label="Scheduled At"
          value={merged.scheduled_at ? new Date(merged.scheduled_at).toLocaleString() : "—"}
        />
        <DetailItem
          label="Dispatched At"
          value={merged.dispatched_at ? new Date(merged.dispatched_at).toLocaleString() : "—"}
        />
        <DetailItem
          label="Completed At"
          value={merged.completed_at ? new Date(merged.completed_at).toLocaleString() : "—"}
        />
        <DetailItem
          label="Duration"
          value={
            merged.completed_at && merged.dispatched_at
              ? `${((new Date(merged.completed_at) - new Date(merged.dispatched_at)) / 1000).toFixed(1)}s`
              : "—"
          }
        />
        {merged.error_message && (
          <div className={`${styles.detailItem}`} style={{ gridColumn: "1 / -1" }}>
            <div className={styles.detailLabel}>Error</div>
            <div className={styles.detailValue} style={{ color: "#ef4444" }}>
              {merged.error_message}
            </div>
          </div>
        )}
      </div>

      {chatHistory.length > 0 && (
        <div className={styles.chatSection}>
          <div className={styles.responseTitle}>Chat History</div>
          <div className={styles.chatContainer}>
            {chatHistory.map((msg, idx) => (
              <ChatMessage
                key={idx}
                role={msg.role}
                type={msg.type}
                content={msg.content || msg.message || msg.text || msg}
              />
            ))}
          </div>
        </div>
      )}

      {chatHistory.length === 0 && merged.response && (
        <>
          <div className={styles.responseTitle}>Agent Response</div>
          <div className={styles.responseBlock}>
            {typeof merged.response === "string"
              ? merged.response
              : JSON.stringify(merged.response, null, 2)}
          </div>
        </>
      )}
    </div>
  );
};

const DetailItem = ({ label, value }) => (
  <div className={styles.detailItem}>
    <div className={styles.detailLabel}>{label}</div>
    <div className={styles.detailValue}>{value}</div>
  </div>
);

export default ScheduleHistoryModal;
