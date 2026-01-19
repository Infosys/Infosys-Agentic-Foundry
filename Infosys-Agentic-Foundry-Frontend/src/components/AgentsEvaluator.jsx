import { useState, useEffect, useRef } from "react";
import { APIs } from "../constant";
import Loader from "./commonComponents/Loader";
import { useMessage } from "../Hooks/MessageContext";
import styles from "../css_modules/AgentsEvaluator.module.css";
import useFetch from "../Hooks/useAxios";
import { storageService } from "../core/storage/storageService";

const AgentsEvaluator = ({ onResponse }) => {
  const [modelOptions, setModelOptions] = useState([]);
  const [model1, setModel1] = useState("");
  const [model2, setModel2] = useState("");
  const [response, setResponse] = useState([]);
  const [loading, setLoading] = useState(false);
  const { addMessage } = useMessage();
  const hasInitialized = useRef(false);
  const { fetchData } = useFetch();
  const [isStreaming, setIsStreaming] = useState(false);

  // Reset response when model1 or model2 changes
  useEffect(() => {
    setResponse([]);
    if (onResponse) onResponse(null);
  }, [model1, model2]);

  const fetchModels = async () => {
    setLoading(true);
    try {
      const res = await fetchData(APIs.GET_MODELS);
      if (res.models && Array.isArray(res.models)) {
        setModelOptions(res.models.map((m) => ({ label: m, value: m })));
      } else {
        addMessage("Invalid models response", "error");
      }
    } catch (error) {
      addMessage("Failed to fetch models", "error");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    if (hasInitialized.current) return;
    fetchModels();
    hasInitialized.current = true;
  }, []);

  const handleEvaluate = async () => {
    setResponse([]);
    if (onResponse) onResponse(null);
    setIsStreaming(true);

    // Use BASE_URL from constant.js
    const baseUrl = process.env.REACT_APP_BASE_URL || "";
    const apiUrl = `${baseUrl}${APIs.PROCESS_UNPROCESSED}?evaluating_model1=${encodeURIComponent(model1)}&evaluating_model2=${encodeURIComponent(model2)}`;

    try {
      // Get JWT token from storage service instead of direct cookie access
      const jwtToken = storageService.getCookie("jwt-token");
      const postMethod = "POST";
      const response = await fetch(apiUrl, {
        method: postMethod,
        headers: {
          Accept: "text/event-stream",
          ...(jwtToken ? { Authorization: `Bearer ${jwtToken}` } : {}),
        },
        credentials: "omit", // previously was include , but due to sast and not using any cookie changed to omit
      });
      if (!response.body) {
        addMessage("No response stream received", "error");
        setIsStreaming(false);
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let done = false;
      let shouldStop = false;
      let latestFormatted = null;
      while (!done && !shouldStop) {
        const { value, done: streamDone } = await reader.read();
        done = streamDone;
        if (value) {
          const chunk = decoder.decode(value, { stream: true });
          // Split by SSE event delimiter\n\n
          const events = chunk.split("\n\n");
          for (const event of events) {
            if (event.trim()) {
              // Remove 'data:' prefix if present
              const lines = event.split("\n").map((l) => l.replace(/^data:/, "").trim());
              const eventData = lines.join("\n");
              let formatted;
              try {
                const parsed = JSON.parse(eventData);
                formatted = JSON.stringify(parsed, null, 2);
                if (parsed.status === "all_done") {
                  shouldStop = true;
                }
              } catch {
                formatted = eventData;
              }
              setResponse((prev) => {
                const updated = [...prev, formatted];
                if (onResponse) onResponse(formatted);
                return updated;
              });
              latestFormatted = formatted;
            }
          }
        }
      }
      if (onResponse && latestFormatted) onResponse(latestFormatted);
      setIsStreaming(false);
    } catch (error) {
      addMessage("Failed to start evaluation (stream)", "error");
      setIsStreaming(false);
    }
  };

  return (
    <>
      <div className={"evaluationLanding"}>
        <div className={styles.container}>
          {loading && <Loader />}
          <div className="iafPageSubHeader">
            <h6>LLM as Judge</h6>
          </div>
          <div className={styles.form}>
            <div className={styles.row}>
              <div style={{ width: "100%", display: "flex", alignItems: "center" }}>
                <label className={styles.label}>Model 1:</label>
                <select value={model1} onChange={(e) => setModel1(e.target.value)} className={styles.select}>
                  <option value="" disabled>
                    Select Model 1
                  </option>
                  {modelOptions.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
              <div style={{ width: "100%", display: "flex", alignItems: "center" }}>
                <label className={styles.label}>Model 2:</label>
                <select value={model2} onChange={(e) => setModel2(e.target.value)} className={styles.select}>
                  <option value="" disabled>
                    Select Model 2
                  </option>
                  {modelOptions
                    .filter((opt) => opt.value !== model1)
                    .map((opt) => (
                      <option key={opt.value} value={opt.value}>
                        {opt.label}
                      </option>
                    ))}
                </select>
              </div>
            </div>
            <div className={styles.row}>
              <div className={styles.buttonContainer}>
                <button onClick={handleEvaluate} disabled={loading || modelOptions.length === 0 || !model1 || !model2 || isStreaming} className="iafButton iafButtonPrimary">
                  Evaluate
                  {loading && <Loader />}
                </button>
              </div>
            </div>

            {response && response.length > 0 && (
              <div style={{ padding: "16px 0" }}>
                <div style={{ display: "flex", flexDirection: "column", gap: "5px" }}>
                  {(() => {
                    const item = response[response.length - 1];
                    let parsed;
                    try {
                      parsed = JSON.parse(item);
                    } catch {
                      parsed = {};
                    }
                    let stepName = parsed.evaluation_id ? `Evaluation Id  ${parsed.evaluation_id}` : `Latest Status`;
                    let description = parsed.status || item;
                    if (parsed.status === "done" || parsed.status === "all_done") {
                      stepName = parsed.status === "done" ? "Done" : "All Done";
                      description = parsed.message || parsed.status;
                    }
                    return (
                      <div style={{ display: "flex", alignItems: "flex-start" }}>
                        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginRight: "12px" }}></div>
                        <div
                          style={{
                            background: "#f8f8f8",
                            padding: "10px 16px",
                            borderRadius: "4px",
                            minWidth: 180,
                            width: "100%",
                            height: "112px",
                            textAlign: "center",
                            margin: "20px 0",
                          }}>
                          <div style={{ fontWeight: 600, color: "#222", marginBottom: 4 }}>{stepName}</div>
                          <div style={{ color: "#555", fontSize: 14 }}>{description}</div>
                          {typeof parsed.processed !== "undefined" && (
                            <div style={{ color: "#555", fontSize: 14 }}>
                              <strong>Processed:</strong> {parsed.processed}
                            </div>
                          )}
                          {typeof parsed.remaining !== "undefined" && (
                            <div style={{ color: "#555", fontSize: 14 }}>
                              <strong>Remaining:</strong> {parsed.remaining}
                            </div>
                          )}
                        </div>
                      </div>
                    );
                  })()}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  );
};
export default AgentsEvaluator;
