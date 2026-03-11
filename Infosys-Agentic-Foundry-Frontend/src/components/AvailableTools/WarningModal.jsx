import style from "../../css_modules/WarningModal.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";

export function WarningModal({ show, messages = [], onClose, onForceAdd, showForceAdd = false, isUpdate = false }) {
  if (!show) return null;

  return (
    <div className={style.modalOverlay}>
      <div className={style.modalContent}>
        <div className={style.warningContainer}>
          <div className={style.warningsList}>
            <ul>
              {messages.map((msg, index) => {
                const isCodeBlock = msg.includes("```") || /def\s+\w+\(.*\):|return|raise|if\s+.*:/.test(msg);
                if (isCodeBlock) {
                  const cleanedCode = msg.replace(/```(python)?|```/g, "");
                  return (
                    <li key={`code-${index}`} className={style.warningListItem}>
                      <span className={style.warningIcon}>
                        <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B" />
                      </span>
                      <pre className={style.codeBlock}>
                        <code className={style.codeInner}>{cleanedCode}</code>
                      </pre>
                    </li>
                  );
                }
                return (
                  <li key={`message-${index}`} className={style.warningListItem}>
                    <span className={style.warningIcon}>
                      <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B" />
                    </span>
                    <span>{msg}</span>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
        {showForceAdd && <div className={style.confirmationText}>Do you want to proceed and {isUpdate ? "update" : "add"} the tool?</div>}

        <div className={style.modalFooter}>
          <div className={style.buttonContainer}>
            <IAFButton type="secondary" onClick={onClose} aria-label="Cancel">
              Cancel
            </IAFButton>
            <IAFButton type="primary" onClick={onForceAdd}>
              {isUpdate ? "Yes, Update Tool" : "Yes, Add Tool"}
            </IAFButton>
          </div>
        </div>
      </div>
    </div>
  );
}
