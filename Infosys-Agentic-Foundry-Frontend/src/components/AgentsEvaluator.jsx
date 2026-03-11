import { useState, useEffect, useRef } from "react";
import { APIs } from "../constant";
import Loader from "./commonComponents/Loader";
import { useMessage } from "../Hooks/MessageContext";
import styles from "../css_modules/AgentsEvaluator.module.css";
import useFetch from "../Hooks/useAxios";
import NewCommonDropdown from "./commonComponents/NewCommonDropdown";
import Button from "../iafComponents/GlobalComponents/Buttons/Button";

const AgentsEvaluator = ({ onResponse }) => {
  const [modelOptions, setModelOptions] = useState([]);
  const [model1, setModel1] = useState("");
  const [model2, setModel2] = useState("");
  const [response, setResponse] = useState([]);
  const [loading, setLoading] = useState(false);
  const { addMessage } = useMessage();
  const hasInitialized = useRef(false);
  const { fetchData, postDataStream } = useFetch();
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
        const formattedModels = res.models.map((m) => ({ label: m, value: m }));
        setModelOptions(formattedModels);

        // Auto-select default model for Model 1, and a different model for Model 2
        const defaultModel = res.default_model_name;
        if (defaultModel) {
          if (!model1) setModel1(defaultModel);
          if (!model2) {
            const otherModel = formattedModels.find((m) => m.value !== defaultModel);
            setModel2(otherModel ? otherModel.value : "");
          }
        }
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

    const apiUrl = `${APIs.PROCESS_UNPROCESSED}?evaluating_model1=${encodeURIComponent(model1)}&evaluating_model2=${encodeURIComponent(model2)}`;

    try {
      let latestFormatted = null;

      // Stream chunk handler
      const onStreamChunk = (obj) => {
        const formatted = JSON.stringify(obj, null, 2);
        setResponse((prev) => {
          const updated = [...prev, formatted];
          if (onResponse) onResponse(formatted);
          return updated;
        });
        latestFormatted = formatted;
      };

      // Use postDataStream from useAxios for consistent streaming (null body = no request payload)
      await postDataStream(apiUrl, null, {}, onStreamChunk);

      if (onResponse && latestFormatted) onResponse(latestFormatted);
      setIsStreaming(false);
    } catch (error) {
      addMessage("Failed to start evaluation (stream)", "error");
      setIsStreaming(false);
    }
  };

  return (
    <>
      <div className={styles.evaluationLanding}>
        {loading && <Loader />}
        <div className={styles.evaluationLayout}>
          {/* Input Card */}
          <div className={styles.inputCard}>
            <h2 className={styles.cardTitle}>LLM As Judge</h2>

            <div>
              {/* Model Selection Grid */}
              <div className={styles.modelGrid}>
                <div className={styles.modelField}>
                  <NewCommonDropdown
                    label="Model 1"
                    options={modelOptions.filter((opt) => opt.value !== model2).map((opt) => opt.value)}
                    selected={model1}
                    onSelect={(value) => setModel1(value)}
                    placeholder="Select Model 1"
                    showSearch={true}
                    width="100%"
                    disabled={isStreaming}
                  />
                </div>
                <div className={styles.modelField}>
                  <NewCommonDropdown
                    label="Model 2"
                    options={modelOptions.filter((opt) => opt.value !== model1).map((opt) => opt.value)}
                    selected={model2}
                    onSelect={(value) => setModel2(value)}
                    placeholder="Select Model 2"
                    showSearch={true}
                    width="100%"
                    disabled={isStreaming}
                  />
                </div>
              </div>

              {/* Evaluate Button */}
              <div className={styles.buttonRow}>
                <Button type="primary" onClick={handleEvaluate} disabled={loading || modelOptions.length === 0 || !model1 || !model2 || isStreaming}>
                  Evaluate
                </Button>
              </div>
            </div>
          </div>

          {/* Results Card - Bottom */}
          {response && response.length > 0 && (
            <div className={styles.resultsCard}>
              <h3 className={styles.cardTitle}>Evaluation Results</h3>
              {(() => {
                const item = response[response.length - 1];
                let parsed;
                try {
                  parsed = JSON.parse(item);
                } catch {
                  parsed = {};
                }
                return (
                  <div className={styles.resultsGrid}>
                    <div className={styles.resultItem}>
                      <span className={styles.resultLabel}>Evaluation ID</span>
                      <p className={styles.resultValue}>{parsed.evaluation_id || "-"}</p>
                    </div>
                    <div className={styles.resultItem}>
                      <span className={styles.resultLabel}>Status</span>
                      <p className={styles.resultValue}>{parsed.status || parsed.message || item}</p>
                    </div>
                    <div className={styles.resultItem}>
                      <span className={styles.resultLabel}>Model 1</span>
                      <p className={styles.resultValue}>{model1 || "-"}</p>
                    </div>
                    <div className={styles.resultItem}>
                      <span className={styles.resultLabel}>Model 2</span>
                      <p className={styles.resultValue}>{model2 || "-"}</p>
                    </div>
                    <div className={styles.resultItem}>
                      <span className={styles.resultLabel}>Processed</span>
                      <p className={styles.resultValue}>{typeof parsed.processed !== "undefined" ? parsed.processed : "-"}</p>
                    </div>
                    <div className={styles.resultItem}>
                      <span className={styles.resultLabel}>Remaining</span>
                      <p className={styles.resultValue}>{typeof parsed.remaining !== "undefined" ? parsed.remaining : "-"}</p>
                    </div>
                  </div>
                );
              })()}
            </div>
          )}
        </div>
      </div>
    </>
  );
};
export default AgentsEvaluator;
