import React, { useState, useEffect, useCallback, useRef } from "react";
import { createPortal } from "react-dom";
import { subscribeToTokenRequest, resolveToken, rejectToken } from "../../utils/manualTokenBridge";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import "./ManualTokenModal.css";

function ManualTokenModal() {
  const [visible, setVisible] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState("");
  const textareaRef = useRef(null);

  useEffect(() => {
    const unsub = subscribeToTokenRequest(() => {
      setToken("");
      setError("");
      setVisible(true);
    });
    return unsub;
  }, []);

  useEffect(() => {
    if (visible && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [visible]);

  const handleSubmit = useCallback(() => {
    const trimmed = token.trim();
    if (!trimmed) {
      setError("Please paste a valid access token.");
      return;
    }
    setVisible(false);
    setToken("");
    resolveToken(trimmed);
  }, [token]);

  const handleCancel = useCallback(() => {
    setVisible(false);
    setToken("");
    setError("");
    rejectToken();
  }, []);

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
      if (e.key === "Escape") {
        handleCancel();
      }
    },
    [handleSubmit, handleCancel]
  );

  if (!visible) return null;

  return createPortal(
    <div className="mtm-overlay" role="dialog" aria-modal="true" aria-label="Enter access token">
      <div className="mtm-card">
        <h3 className="mtm-title">Enter Access Token</h3>
        <p className="mtm-desc">Paste your access token below. Press Enter or click Submit to continue.</p>
        <textarea
          ref={textareaRef}
          className="mtm-textarea"
          value={token}
          onChange={(e) => {
            setToken(e.target.value);
            setError("");
          }}
          onKeyDown={handleKeyDown}
          placeholder="Paste access token here..."
          rows={5}
          spellCheck={false}
          autoComplete="off"
        />
        {error && <span className="mtm-error">{error}</span>}
        <div className="mtm-actions">
          <Button type="secondary" onClick={handleCancel}>
            Cancel
          </Button>
          <Button type="primary" onClick={handleSubmit}>
            Submit
          </Button>
        </div>
      </div>
    </div>,
    document.body
  );
}

export default ManualTokenModal;