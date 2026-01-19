import { useState } from "react";
import styles from "./Installation.module.css";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader";

/**
 * RestartServer Component
 * Provides server restart functionality
 */
const RestartServer = () => {
  const [loading, setLoading] = useState(false);
  const [activeAction, setActiveAction] = useState("");
  const [restartResult, setRestartResult] = useState(null);

  const { postData } = useFetch();
  const { addMessage } = useMessage();

  /**
   * Restart the server
   */
  const handleRestartServer = async () => {
    setLoading(true);
    setActiveAction("restart");
    setRestartResult(null);
    try {
      const response = await postData(APIs.RESTART_SERVER);

      if (response?.is_restart || response?.success === true) {
        setRestartResult({ type: "success", message: response?.message });
        addMessage(response?.message, "success");
      } else {
        const errorMsg = response?.detail || response?.message;
        setRestartResult({ type: "error", message: errorMsg });
        addMessage(errorMsg, "error");
      }
    } catch (error) {
      const errorMsg = error?.response?.data?.message || error?.response?.data?.detail;
      setRestartResult({ type: "error", message: errorMsg });
      addMessage(errorMsg, "error");
    } finally {
      setLoading(false);
      setActiveAction("");
    }
  };

  return (
    <div className={styles.installationContainer}>
      {loading && <Loader contained />}

      <div className={styles.tabContent}>
        <div className={styles.tabHeader}>
          <p className={styles.tabDescription}>
            Restart the backend server to apply installed dependencies or configuration changes.
          </p>
        </div>

        <div className={styles.restartSection}>
          <div className={styles.restartCard}>
            <div className={styles.restartIcon}>🔄</div>
            <h3 className={styles.restartTitle}>Server Restart</h3>
            <p className={styles.restartDescription}>
              Clicking the button below will initiate a server restart. This may take a few moments. The server will be temporarily
              unavailable during the restart process.
            </p>
            <button className="iafButton iafWarningButton" onClick={handleRestartServer} disabled={loading}>
              {activeAction === "restart" ? (
                <>
                  <span className={styles.spinner}></span> Restarting...
                </>
              ) : (
                "Restart Server"
              )}
            </button>
          </div>

          {/* Restart Result */}
          {restartResult && (
            <div className={`${styles.restartResult} ${restartResult.type === "success" ? styles.restartSuccess : styles.restartError}`}>
              <span className={styles.restartResultIcon}>{restartResult.type === "success" ? "✓" : "✗"}</span>
              <p className={styles.restartResultMessage}>{restartResult.message}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default RestartServer;
