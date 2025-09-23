import { useState, useEffect ,useRef} from "react";
import { evaluate } from "./EvaluateService";
import { APIs } from "../constant";
import Loader from "./commonComponents/Loader";
import { useMessage } from "../Hooks/MessageContext";
import styles from "../css_modules/AgentsEvaluator.module.css";
import useFetch from "../Hooks/useAxios";

const AgentsEvaluator = () => {
  const [modelOptions, setModelOptions] = useState([]);
  const [model1, setModel1] = useState("");
  const [model2, setModel2] = useState("");  const [response, setResponse] = useState(null);
  const [loading, setLoading] = useState(false);
  const {addMessage} = useMessage();
  const hasInitialized = useRef(false);
  const {fetchData} = useFetch();
  const fetchModels = async() => {
      setLoading(true);
      try {
        const res = await fetchData(APIs.GET_MODELS);
        if (res.models && Array.isArray(res.models)) {
          setModelOptions(res.models.map(m => ({ label: m, value: m })));
        } else {
          addMessage("Invalid models response","error");
        }
      } catch (error) {
        addMessage("Failed to fetch models","error");
      }
      finally {
        setLoading(false);
      }
    }
  useEffect(() => {
    if (hasInitialized.current) return;
    fetchModels();
    hasInitialized.current = true;
  }, []);

  const handleEvaluate = async () => {
    setLoading(true);
    setResponse(null);
    const res = await evaluate(model1, model2);
    setResponse(res);
    setLoading(false);
  };  

  return (
    <>
      <div className={"evaluationLanding"}>
        <div className={styles.container}>
          <h2 className={styles.heading}>Evaluate Agents</h2>
          {loading && <Loader/> }
            <div className={styles.form}>
              <div className={styles.row}>
                <label className={styles.label}>Model 1:</label>
                <select value={model1} onChange={e => setModel1(e.target.value)} className={styles.select}>
                  <option value="" disabled>Select Model 1</option>
                  {modelOptions.map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <div className={styles.row}>
                <label className={styles.label}>Model 2:</label>
                <select value={model2} onChange={e => setModel2(e.target.value)} className={styles.select}>
                  <option value="" disabled>Select Model 2</option>
                  {modelOptions.filter(opt => opt.value !== model1).map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              <div className={styles.buttonContainer}>
                <button onClick={handleEvaluate} disabled={loading || modelOptions.length === 0 || !model1 || !model2} className={styles.button}>
                  Evaluate
                  {loading && <Loader/>}
                </button>
              </div>
              {response && (
                <pre className={styles.response}>
                  {response?.error
                    ? (typeof response.error === 'string' ? response.error : JSON.stringify(response.error, null, 2))
                    : (typeof response === 'string' ? response : JSON.stringify(response, null, 2))}
                </pre>
              )}
            </div>
        </div>
      </div>
    </>
  );
}
export default AgentsEvaluator;
