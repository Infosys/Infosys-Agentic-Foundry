import React, { useState } from "react";
import styles from "./GenerateServerModal.module.css";
import Loader from "../commonComponents/Loader";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import SVGIcons from "../../Icons/SVGIcons";
import TextareaWithActions from "../commonComponents/TextareaWithActions";

/**
 * GenerateServerModal - Modal for generating a server from selected tools
 *
 * @param {Function} onClose - Callback to close the modal
 * @param {Function} onGenerate - Callback to generate server (serverName, serverDescription)
 * @param {boolean} loading - Whether the generate request is in progress
 * @param {number} selectedCount - Number of selected tools
 */
const GenerateServerModal = ({ onClose, onGenerate, loading = false, selectedCount = 0 }) => {
  const [serverName, setServerName] = useState("");
  const [serverDescription, setServerDescription] = useState("");

  const handleSubmit = (e) => {
    e.preventDefault();
    onGenerate(serverName.trim(), serverDescription.trim());
  };

  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget && !loading) {
      onClose();
    }
  };

  return (
    <div className={styles.generateModalOverlay} onClick={handleOverlayClick}>
      {loading && <Loader />}
      <div className={styles.generateModalContainer} onClick={(e) => e.stopPropagation()}>
        <div className={styles.generateModalHeader}>
          <h2 className={styles.generateModalTitle}>Generate Server</h2>
          <button type="button" className={styles.modalCloseBtn} onClick={onClose} disabled={loading} aria-label="Close modal">
            <SVGIcons icon="x" width={20} height={20} color="var(--text-primary)" />
          </button>
        </div>

        <form onSubmit={handleSubmit} className={styles.generateModalForm}>
          <div className={styles.generateModalContent}>
            <p className={styles.generateModalInfo}>
              Generating server from <strong>{selectedCount}</strong> selected tool{selectedCount !== 1 ? "s" : ""}.
            </p>

            <div className={styles.generateFormGroup}>
              <label htmlFor="serverName" className={styles.generateFormLabel}>
                Server Name
              </label>
              <input
                type="text"
                id="serverName"
                className={styles.generateFormInput}
                value={serverName}
                onChange={(e) => setServerName(e.target.value)}
                placeholder="Enter server name"
                disabled={loading}
              />
            </div>

            <div className={styles.generateFormGroup}>
              <TextareaWithActions
                name="serverDescription"
                label="Server Description"
                value={serverDescription}
                onChange={(e) => setServerDescription(e.target.value)}
                placeholder="Enter server description"
                rows={4}
                disabled={loading}
                showCopy={false}
                showExpand={false}
              />
            </div>
          </div>

          <div className={styles.generateModalFooter}>
            <Button type="secondary" onClick={onClose} disabled={loading}>
              Cancel
            </Button>
            <Button type="primary" htmlType="submit" disabled={loading} loading={loading}>
              Generate
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
};

export default GenerateServerModal;
