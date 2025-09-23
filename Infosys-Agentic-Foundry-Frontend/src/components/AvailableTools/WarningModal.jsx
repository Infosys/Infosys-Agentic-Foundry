import React from "react";
import style from "../../css_modules/WarningModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";

export function WarningModal({ show, messages = [], onClose, onForceAdd, showForceAdd = false, isUpdate = false }) {
    if (!show) return null;

    return (
      <div className={style.modalOverlay}>
        <div className={style.modalContent}>
          <div className={style.warningContainer}>  
            <div className={style.warningsList}>
              <ul>
                {messages.map((msg, index) => {
                  const isCodeBlock = msg.includes('```') || /def\s+\w+\(.*\):|return|raise|if\s+.*:/.test(msg);
                  if (isCodeBlock) {
                    const cleanedCode = msg.replace(/```(python)?|```/g, '');
                    return (
                      <li key={`code-${index}`} className={style.warningListItem}>
                        <span className={style.warningIcon}>
                          <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B"/>
                        </span>
                        <pre className={style.codeBlock}><code className={style.codeInner}>{cleanedCode}</code></pre>
                      </li>
                    );
                  }
                  return (
                    <li key={`message-${index}`} className={style.warningListItem}>
                      <span className={style.warningIcon}>
                        <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B"/>
                      </span>
                      <span>{msg}</span>
                    </li>
                  );
                })}
              </ul>

            </div>
          </div>
          {showForceAdd && (
            <div className={style.confirmationText}>
                Do you want to proceed and {isUpdate ? 'update' : 'add'} the tool?
            </div>
          )}

        <div className={style.modalFooter}>
          <div className={style.buttonContainer}>
            <button 
              onClick={onClose} 
              className={style.cancelButton}
            >
            CANCEL
            </button>
            {showForceAdd && (
              <button 
                onClick={onForceAdd} 
                className={style.forceButton}
              >
              {isUpdate ? "YES, UPDATE TOOL" : "YES, ADD TOOL"}
              </button>
            )}
          </div>
          </div>
        </div>
      </div>
    );
  }

