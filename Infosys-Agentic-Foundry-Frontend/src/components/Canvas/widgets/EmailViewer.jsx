import React, { useState, useRef, useMemo} from "react";
import styles from "./EmailViewer.module.css";

const EmailViewer = ({
  content,
  messageId,
  is_last,
  sendUserMessage,
}) => {

  const isLast = Boolean(is_last);
  const emailData = useMemo(() => {
    if (!content) return { to: "", subject: "", body: "" };
    if (content.to || content.subject || content.body) {
      return content;
    }
    if (content.data) {
      return content.data;
    }
    if (typeof content === "string") {
      try {
        const parsed = JSON.parse(content);
        return parsed.data || parsed;
      } catch {
        return { to: "", subject: "", body: content };
      }
    }
    return { to: "", subject: "", body: "" };
  }, [content]);

  // Track original values for editing detection
  const originalToRef = useRef(emailData.to || "");
  const originalSubjectRef = useRef(emailData.subject || "");
  const originalBodyRef = useRef(emailData.body || "");

  const [toValue, setToValue] = useState(emailData.to || "");
  const [subjectValue, setSubjectValue] = useState(emailData.subject || "");
  const [bodyValue, setBodyValue] = useState(emailData.body || "");

 
  // Helper to determine if any field is edited
  const isEdited = () => {
    return (
      toValue !== originalToRef.current ||
      subjectValue !== originalSubjectRef.current ||
      bodyValue !== originalBodyRef.current
    );
  };
  return (
    <div>
      <div className={styles.emailContent}>
        <div className={styles.emailCards}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "stretch", marginBottom: 0 }}>
            {isLast && (
              <div style={{ display: "flex", flexDirection: "column", justifyContent: "center", marginRight: "16px" }}>
                <button
                  className={styles.sendButton}
                  style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", border: "1px solid #ccc", borderRadius: "8px", background: "#fff", width: "60px", height: "50px" }}
                  title="Send Email"
                  onClick={async () => {
                    const editedFields = {};
                    if (toValue !== originalToRef.current) editedFields.to = toValue;
                    if (subjectValue !== originalSubjectRef.current) editedFields.subject = subjectValue;
                    if (bodyValue !== originalBodyRef.current) editedFields.body = bodyValue;
                    const query = isEdited()
                      ? `editing with content: ${JSON.stringify(editedFields)} and send`
                      : "approved and send";
                    // Always set flags in payload
                    const payload = {
                      query,
                      context_flag: true,
                      response_formatting_flag: false
                    };
                    const response = sendUserMessage(payload);
                  }}
                >
                  <svg width="32" height="32" viewBox="0 0 24 24" fill="none" style={{ marginBottom: "4px" }}>
                    <path d="M3 20L21 12L3 4V10L15 12L3 14V20Z" stroke="#222" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span style={{ fontSize: "16px", color: "#222" }}>Send</span>
                </button>
              </div>
            )}
            <div style={{ flex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", marginBottom: 0 }}>
                <span style={{ fontWeight: "500", color: "#333", width: "120px", textAlign: "left" }}>To</span>
                {isLast ? (
                  <input
                    type="text"
                    autoFocus
                    value={toValue}
                    onChange={e => setToValue(e.target.value)}
                    style={{ color: "#333", flex: 1, border: "none", outline: "none", fontSize: "15px", background: "#fff" }}
                  />
                ) : (
                  <span style={{ color: "#333", flex: 1 }}>{toValue}</span>
                )}
              </div>
              <div style={{ margin: "0 0 8px 0" }}>
                <hr style={{ border: "none", borderTop: "1px solid #eee" }} />
              </div>
              <div style={{ display: "flex", alignItems: "center", marginBottom: 0 }}>
                <span style={{ fontWeight: "500", color: "#333", width: "120px", textAlign: "left" }}>Subject</span>
                {isLast ? (
                  <input
                    type="text"
                    value={subjectValue}
                    onChange={e => setSubjectValue(e.target.value)}
                    style={{ marginLeft: "16px", color: "#333", flex: 1, border: "none",outline: "none", fontSize: "15px", background: "#fff" }}
                  />
                ) : (
                  <span style={{ marginLeft: "16px", color: "#333", flex: 1 }}>{subjectValue}</span>
                )}
              </div>
            </div>
          </div>
          <div style={{ margin: "0 0 16px 0" }}>
            <hr style={{ border: "none", borderTop: "1px solid #eee" }} />
          </div>
        </div>
        {/* Email Body */}
        <div className={styles.emailBody}>
          <div
            className={styles.bodyContent}
            style={{
              overflowY: "auto",
              width: "100%"
            }}
          >
       <pre contentEditable={isLast} onInput={e => setBodyValue(e.target.textContent)} className={styles.bodyText} style={{ margin: 0, whiteSpace: "pre-wrap" }}>{emailData.body}</pre>          </div>
        </div>
      </div>
    </div>
  );
}
export default EmailViewer;