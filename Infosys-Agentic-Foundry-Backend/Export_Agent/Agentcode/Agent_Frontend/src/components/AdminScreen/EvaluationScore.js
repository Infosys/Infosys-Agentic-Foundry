import React, { useState, useEffect, useRef } from "react";
import { evaluate, getEvaluationData, getToolMetricsData, getAgentMetricsData, createLazyLoadHandler } from "../../components/EvaluateService.js";
import Loader from "../commonComponents/Loader";
import { useMessage } from "../../Hooks/MessageContext";
import styles from "./EvaluationScore.module.css";
import AgentsMultiSelect from "../AgentsMultiSelect";
import SVGIcons from "../../Icons/SVGIcons";

// Helper to test scroll manually
function simulateScroll(element) {
    if (!element?.current) return;

    // Create and dispatch a scroll event
    const scrollEvent = new Event('scroll', { bubbles: true });
    element.current.dispatchEvent(scrollEvent);
    
}

const EvaluationScore = () => {
    const [activeTab, setActiveTab] = useState("Evaluation Records");
    const [evaluationData, setEvaluationData] = useState([]);
    const [toolMetricsData, setToolMetricsData] = useState([]);
    const [agentMetricsData, setAgentMetricsData] = useState([]);
    const [selectedAgentNames, setSelectedAgentNames] = useState([]);
    const [evaluationRecords, setEvaluationRecords] = useState([]);
    const [isFiltering, setIsFiltering] = useState(false);
    const [loading, setLoading] = useState(false);
    const [isTableView, setIsTableView] = useState(true); // Add this state

    
    // Added for lazy loading
    const [page, setPage] = useState(1);
    const [isLoadingMore, setIsLoadingMore] = useState(false);
    const limit = 10; // Number of items per page
    // Add hasMore flags for each tab
    const [hasMoreEvaluationData, setHasMoreEvaluationData] = useState(true);
    const [hasMoreToolMetricsData, setHasMoreToolMetricsData] = useState(true);
    const [hasMoreAgentMetricsData, setHasMoreAgentMetricsData] = useState(true);
    
    // Refs for table containers
    const evaluationTableRef = useRef(null);
    const toolMetricsTableRef = useRef(null);
    const agentMetricsTableRef = useRef(null);
    
    const { addMessage } = useMessage();
    const hasInitialized = useRef(false);
    const prevSelectedAgentsLength = useRef(0);

    useEffect(() => {
        if (hasInitialized.current) return;
        fetchEvaluationRecord();
        hasInitialized.current = true;
    }, []);
    // Setup scroll event listeners for lazy loading
    useEffect(() => {
        const currentTableRef = getCurrentTableRef();
        
        if (!currentTableRef?.current) {
            return;
        }
        
        let handleScroll;
        
        switch(activeTab) {
            case "Evaluation Records":
                handleScroll = createLazyLoadHandler(
                    "evaluation",
                    evaluationTableRef,
                    evaluationData,
                    setEvaluationData,
                    page,
                    setPage,
                    limit,
                    selectedAgentNames.length > 0 ? selectedAgentNames.join(',') : null,
                    setIsLoadingMore,
                    hasMoreEvaluationData,
                    setHasMoreEvaluationData
                );
                break;
            case "Tools Efficiency":
                handleScroll = createLazyLoadHandler(
                    "toolMetric",
                    toolMetricsTableRef,
                    toolMetricsData,
                    setToolMetricsData,
                    page,
                    setPage,
                    limit,
                    selectedAgentNames.length > 0 ? selectedAgentNames.join(',') : null,
                    setIsLoadingMore,
                    hasMoreToolMetricsData,
                    setHasMoreToolMetricsData
                );
                break;
            case "Agents Efficiency":
                handleScroll = createLazyLoadHandler(
                    "agentMetric",
                    agentMetricsTableRef,
                    agentMetricsData,
                    setAgentMetricsData,
                    page,
                    setPage,
                    limit,
                    selectedAgentNames.length > 0 ? selectedAgentNames.join(',') : null,
                    setIsLoadingMore,
                    hasMoreAgentMetricsData,
                    setHasMoreAgentMetricsData
                );
                break;
            default:
                break;
        }
        
        if (handleScroll && currentTableRef.current) {
            currentTableRef.current.addEventListener('scroll', handleScroll);
            
            // Proper cleanup function
            return () => {
                if (currentTableRef.current) {
                    currentTableRef.current.removeEventListener('scroll', handleScroll);
                }
            };
        }
    }, [activeTab, page, selectedAgentNames, evaluationData, toolMetricsData, agentMetricsData, limit, hasMoreEvaluationData, hasMoreToolMetricsData, hasMoreAgentMetricsData]);
    
    // Helper to get the current active table ref
    const getCurrentTableRef = () => {
        switch(activeTab) {
            case "Evaluation Records":
                return evaluationTableRef;
            case "Tools Efficiency":
                return toolMetricsTableRef;
            case "Agents Efficiency":
                return agentMetricsTableRef;
            default:
                return null;
        }
    };

    // Reset page when switching tabs or filtering
    useEffect(() => {
        setPage(1);
    }, [activeTab, selectedAgentNames]);        const fetchEvaluationRecord = async () => {
        setLoading(true);
        try {
            // Initial load without any agent filter
            const response = await getEvaluationData(null, 1, limit);
            if (response && response.data && Array.isArray(response.data)) {
                setEvaluationData(response.data);
                setHasMoreEvaluationData(response.data.length === limit);
            } else if (response && Array.isArray(response)) {
                setEvaluationData(response);
                setHasMoreEvaluationData(response.length === limit);
            } else {
                addMessage("Invalid evaluation data response", "error");
                setHasMoreEvaluationData(false);
            }
        } catch (error) {
            addMessage("Failed to fetch evaluation data", "error");
            setHasMoreEvaluationData(false);
            console.error("Error fetching evaluation data:", error);
        } finally {
            setLoading(false);
        }
    }
           const handleAgentSelection = async (selectedAgents) => {
        // Immediately update the reference to prevent multiple calls
        // Store the current value for comparison
        const previousLength = prevSelectedAgentsLength.current;
        prevSelectedAgentsLength.current = selectedAgents.length;
        
        // Only proceed if there's an actual change in selection to prevent infinite loop
        if (previousLength === selectedAgents.length) {
            return;
        }
        
        setSelectedAgentNames(selectedAgents);
        setPage(1); // Reset page to 1 when selection changes
        
        // If all agents are unselected, reset to the initial API call based on activeTab
        if (selectedAgents.length === 0 && previousLength > 0) {
            setLoading(true);
            try {
                switch (activeTab) {
                    case "Evaluation Records":
                        const evalData = await getEvaluationData(null, 1, limit);
                        if (evalData && evalData.data && Array.isArray(evalData.data)) {
                            setEvaluationData(evalData.data);
                            setHasMoreEvaluationData(evalData.data.length === limit);
                        } else if (evalData && Array.isArray(evalData)) {
                            setEvaluationData(evalData);
                            setHasMoreEvaluationData(evalData.length === limit);
                        } else {
                            addMessage("Invalid evaluation data response", "error");
                            setHasMoreEvaluationData(false);
                        }
                        break;
                    case "Tools Efficiency":
                        const toolData = await getToolMetricsData(null, 1, limit);
                        if (toolData && toolData.data && Array.isArray(toolData.data)) {
                            setToolMetricsData(toolData.data);
                            setHasMoreToolMetricsData(toolData.data.length === limit);
                        } else if (toolData && Array.isArray(toolData)) {
                            setToolMetricsData(toolData);
                            setHasMoreToolMetricsData(toolData.length === limit);
                        } else {
                            addMessage("Invalid tool metrics data response", "error");
                            setHasMoreToolMetricsData(false);
                        }
                        break;
                    case "Agents Efficiency":
                        const agentData = await getAgentMetricsData(null, 1, limit);
                        if (agentData && agentData.data && Array.isArray(agentData.data)) {
                            setAgentMetricsData(agentData.data);
                            setHasMoreAgentMetricsData(agentData.data.length === limit);
                        } else if (agentData && Array.isArray(agentData)) {
                            setAgentMetricsData(agentData);
                            setHasMoreAgentMetricsData(agentData.length === limit);
                        } else {
                            addMessage("Invalid agent metrics data response", "error");
                            setHasMoreAgentMetricsData(false);
                        }
                        break;
                    default:
                        break;
                }
            } catch (error) {
                addMessage(`Failed to fetch ${activeTab.toLowerCase()} data`, "error");
                setHasMoreEvaluationData(false);
                setHasMoreToolMetricsData(false);
                setHasMoreAgentMetricsData(false);
                console.error(`Error fetching ${activeTab.toLowerCase()} data:`, error);
            } finally {
                setLoading(false);
            }
        }
    };

    const handleFilterByAgents = async () => {
        if (selectedAgentNames.length === 0) {
            addMessage("Please select at least one agent to filter", "warning");
            return;
        }

        setIsFiltering(true);
        setLoading(true);
        setPage(1); // Reset page to 1 when filtering

        try {
            const agentNamesString = selectedAgentNames.join(',');

            switch (activeTab) {
                case "Evaluation Records":
                    const evaluationData = await getEvaluationData(agentNamesString, 1, limit);
                    if (evaluationData && evaluationData.data && Array.isArray(evaluationData.data)) {
                        setEvaluationData(evaluationData.data);
                        setHasMoreEvaluationData(evaluationData.data.length === limit);
                    } else if (evaluationData && Array.isArray(evaluationData)) {
                        setEvaluationData(evaluationData);
                        setHasMoreEvaluationData(evaluationData.length === limit);
                    } else {
                        addMessage("Invalid evaluation data response", "error");
                        setHasMoreEvaluationData(false);
                    }
                    break;
                case "Tools Efficiency":
                    const toolData = await getToolMetricsData(agentNamesString, 1, limit);
                    if (toolData && toolData.data && Array.isArray(toolData.data)) {
                        setToolMetricsData(toolData.data);
                        setHasMoreToolMetricsData(toolData.data.length === limit);
                    } else if (toolData && Array.isArray(toolData)) {
                        setToolMetricsData(toolData);
                        setHasMoreToolMetricsData(toolData.length === limit);
                    } else {
                        addMessage("Invalid tool metrics data response", "error");
                        setHasMoreToolMetricsData(false);
                    }
                    break;
                case "Agents Efficiency":
                    const agentData = await getAgentMetricsData(agentNamesString, 1, limit);
                    if (agentData && agentData.data && Array.isArray(agentData.data)) {
                        setAgentMetricsData(agentData.data);
                        setHasMoreAgentMetricsData(agentData.data.length === limit);
                    } else if (agentData && Array.isArray(agentData)) {
                        setAgentMetricsData(agentData);
                        setHasMoreAgentMetricsData(agentData.length === limit);
                    } else {
                        addMessage("Invalid agent metrics data response", "error");
                        setHasMoreAgentMetricsData(false);
                    }
                    break;
                default:
                    break;
            }
        } catch (error) {
            addMessage(`Failed to fetch ${activeTab.toLowerCase()} data with filter`, "error");
            setHasMoreEvaluationData(false);
            setHasMoreToolMetricsData(false);
            setHasMoreAgentMetricsData(false);
            console.error(`Error fetching ${activeTab.toLowerCase()} data with filter:`, error);
        } finally {
            setLoading(false);
            setIsFiltering(false);
        }
    };

    const handleTabChange = async (tab) => {
        setActiveTab(tab);
        setLoading(true);
        setPage(1); // Reset page to 1 when changing tabs

        try {
            if (selectedAgentNames.length > 0) {
                // If we have selected agents, use them as filter
                const agentNamesString = selectedAgentNames.join(',');
                
                if (tab === "Tools Efficiency") {
                    const data = await getToolMetricsData(agentNamesString, 1, limit);
                    if (data && data.data && Array.isArray(data.data)) {
                        setToolMetricsData(data.data);
                        setHasMoreToolMetricsData(data.data.length === limit);
                    } else if (data && Array.isArray(data)) {
                        setToolMetricsData(data);
                        setHasMoreToolMetricsData(data.length === limit);
                    } else {
                        addMessage("Invalid tool metrics data response", "error");
                        setHasMoreToolMetricsData(false);
                    }
                } else if (tab === "Agents Efficiency") {
                    const data = await getAgentMetricsData(agentNamesString, 1, limit);
                    if (data && data.data && Array.isArray(data.data)) {
                        setAgentMetricsData(data.data);
                        setHasMoreAgentMetricsData(data.data.length === limit);
                    } else if (data && Array.isArray(data)) {
                        setAgentMetricsData(data);
                        setHasMoreAgentMetricsData(data.length === limit);
                    } else {
                        addMessage("Invalid agent metrics data response", "error");
                        setHasMoreAgentMetricsData(false);
                    }
                } else if (tab === "Evaluation Records" && evaluationData.length === 0) {
                    const data = await getEvaluationData(agentNamesString, 1, limit);
                    if (data && data.data && Array.isArray(data.data)) {
                        setEvaluationData(data.data);
                        setHasMoreEvaluationData(data.data.length === limit);
                    } else if (data && Array.isArray(data)) {
                        setEvaluationData(data);
                        setHasMoreEvaluationData(data.length === limit);
                    } else {
                        addMessage("Invalid evaluation data response", "error");
                        setHasMoreEvaluationData(false);
                    }
                }
            } else {
                // No selected agents, fetch all data
                if (tab === "Tools Efficiency" && toolMetricsData.length === 0) {
                    const data = await getToolMetricsData(null, 1, limit);
                    if (data && data.data && Array.isArray(data.data)) {
                        setToolMetricsData(data.data);
                        setHasMoreToolMetricsData(data.data.length === limit);
                    } else if (data && Array.isArray(data)) {
                        setToolMetricsData(data);
                        setHasMoreToolMetricsData(data.length === limit);
                    } else {
                        addMessage("Invalid tool metrics data response", "error");
                        setHasMoreToolMetricsData(false);
                    }
                } else if (tab === "Agents Efficiency" && agentMetricsData.length === 0) {
                    const data = await getAgentMetricsData(null, 1, limit);
                    if (data && data.data && Array.isArray(data.data)) {
                        setAgentMetricsData(data.data);
                        setHasMoreAgentMetricsData(data.data.length === limit);
                    } else if (data && Array.isArray(data)) {
                        setAgentMetricsData(data);
                        setHasMoreAgentMetricsData(data.length === limit);
                    } else {
                        addMessage("Invalid agent metrics data response", "error");
                        setHasMoreAgentMetricsData(false);
                    }
                } else if (tab === "Evaluation Records" && evaluationData.length === 0) {
                    const data = await getEvaluationData(null, 1, limit);
                    if (data && data.data && Array.isArray(data.data)) {
                        setEvaluationData(data.data);
                        setHasMoreEvaluationData(data.data.length === limit);
                    } else if (data && Array.isArray(data)) {
                        setEvaluationData(data);
                        setHasMoreEvaluationData(data.length === limit);
                    } else {
                        addMessage("Invalid evaluation data response", "error");
                        setHasMoreEvaluationData(false);
                    }
                }
            }
        } catch (error) {
            addMessage(`Failed to fetch ${tab.toLowerCase()} metrics data`, "error");
            setHasMoreEvaluationData(false);
            setHasMoreToolMetricsData(false);
            setHasMoreAgentMetricsData(false);
            console.error(`Error fetching ${tab.toLowerCase()} metrics data:`, error);
        } finally {
            setLoading(false);
        }
    };

    const handleViewSwitch = () => {
        setIsTableView((prev) => !prev);
    };

    const renderTabContent = () => {
        // We're now filtering through API calls, so we don't need client-side filtering
        switch (activeTab) {
            case "Evaluation Records":
                return (
                    <div className={styles.tabContent}>
                        {loading ? (
                            <Loader />) : evaluationData.length > 0 ? (
                                isTableView ? (
                                <div className={styles.tableContainer} ref={evaluationTableRef}>
                                    <table className={styles.evaluationTable}>
                                        <thead>
                                            <tr>
                                                <th>Session ID</th>
                                                <th>Query</th>
                                                <th>Response</th>
                                                <th>Model Used</th>
                                                <th>Agent Name</th>
                                                <th>Agent Type</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {evaluationData.map((item, index) => (
                                                <tr key={index}>
                                                    <td>{item.session_id}</td>
                                                    <td>{item.query}</td>
                                                    <td>
                                                        <div className={styles.responseCell}>
                                                            {item.response}
                                                        </div>
                                                    </td>
                                                    <td>{item.model_used}</td>
                                                    <td>{item.agent_name}</td>
                                                    <td>{item.agent_type}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                    {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                                </div>                                ) : (
                                // Simple accordion view for demonstration
                                <div className={styles.accordionContainer}>
                                    {evaluationData.map((item, index) => (
                                        <details key={index} className={styles.accordionItem}>
                                            <summary>
                                                <span>{item.query}</span>
                                                <span>{item.model_used}</span>
                                                <span>{item.agent_name}</span>
                                                <span>{item.agent_type}</span>
                                            </summary>
                                            <div className={styles.responseCell}>
                                                <strong>Response:</strong> {item.response}
                                            </div>
                                        </details>
                                    ))}
                                    {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                                </div>
                            )
                            ) : (
                            <div className={styles.noData}>
                                {evaluationData.length > 0
                                    ? "No matching evaluation data for selected agents"
                                    : "No evaluation data available"}
                            </div>
                        )}
                    </div>
                );            
                case "Tools Efficiency":
                return (
                    <div className={styles.tabContent}>
                        {loading ? (
                            <Loader />) : toolMetricsData.length > 0 ? (
                                isTableView ? (
                                <div className={styles.tableContainer} ref={toolMetricsTableRef}>
                                    <table className={styles.evaluationTable}>
                                        <thead>
                                            <tr>
                                                <th>ID</th>
                                                <th>Query</th>
                                                <th>Response</th>
                                                <th>Model</th>
                                                <th>Tool Selection Accuracy</th>
                                                <th>Tool Usage Efficiency</th>
                                                <th>Success Rate</th>
                                                <th>Efficiency Category</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {toolMetricsData.map((item, index) => (
                                                <tr key={index}>
                                                    <td>{item.id}</td>
                                                    <td>{item.user_query}</td>
                                                    <td>
                                                        <div className={styles.responseCell}>
                                                            {item.agent_response}
                                                        </div>
                                                    </td>
                                                    <td>{item.model_used}</td>
                                                    <td>{(item.tool_selection_accuracy * 100).toFixed(2)}%</td>
                                                    <td>{(item.tool_usage_efficiency * 100).toFixed(2)}%</td>
                                                    <td>{(item.tool_call_success_rate * 100).toFixed(2)}%</td>
                                                    <td>{item.tool_utilization_efficiency_category}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                    {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                                </div>
                                ) : (
                                // Tools Efficiency accordion view
                                <div className={styles.accordionContainer}>
                                    {toolMetricsData.map((item, index) => (
                                        <details key={index} className={styles.accordionItem}>
                                            <summary>
                                                <span>{item.user_query}</span>
                                                <span>{item.model_used}</span>
                                                <span>{(item.tool_selection_accuracy * 100).toFixed(1)}%</span>
                                                <span>{(item.tool_usage_efficiency * 100).toFixed(1)}%</span>
                                                <span>{(item.tool_call_precision * 100).toFixed(1)}%</span>
                                                <span>{(item.tool_call_success_rate * 100).toFixed(1)}%</span>
                                                <span>{(item.tool_utilization_efficiency * 100).toFixed(1)}%</span>
                                                <span>{item.tool_utilization_efficiency_category}</span>
                                                <span>{item.model_used_for_evaluation}</span>
                                            </summary>
                                            <div className={styles.responseCell}>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Agent Response:</strong><br />
                                                    {item.agent_response}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Tool Selection Accuracy Justification:</strong><br />
                                                    {item.tool_selection_accuracy_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Tool Usage Efficiency Justification:</strong><br />
                                                    {item.tool_usage_efficiency_justification}
                                                </div>
                                                <div>
                                                    <strong>Tool Call Precision Justification:</strong><br />
                                                    {item.tool_call_precision_justification}
                                                </div>
                                            </div>
                                        </details>
                                    ))}
                                    {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                                </div>
                            )
                            ) : (
                            <div className={styles.noData}>
                                {toolMetricsData.length > 0
                                    ? "No matching tool metrics data for selected agents"
                                    : "No tool metrics data available"}
                            </div>
                        )}
                    </div>
                );            case "Agents Efficiency":
                return (
                    <div className={styles.tabContent}>
                        {loading ? (
                            <Loader />) : agentMetricsData.length > 0 ? (
                                isTableView ? (
                                <div className={styles.tableContainer} ref={agentMetricsTableRef}>
                                    <table className={styles.evaluationTable}>
                                        <thead>
                                            <tr>
                                                <th>ID</th>
                                                <th>Query</th>
                                                <th>Response</th>
                                                <th>Model</th>
                                                <th>Task Decomposition</th>
                                                <th>Reasoning Relevancy</th>
                                                <th>Response Coherence</th>
                                                <th>Efficiency Category</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {agentMetricsData.map((item, index) => (
                                                <tr key={index}>
                                                    <td>{item.id}</td>
                                                    <td>{item.user_query}</td>
                                                    <td>
                                                        <div className={styles.responseCell}>
                                                            {item.response}
                                                        </div>
                                                    </td>
                                                    <td>{item.model_used}</td>
                                                    <td>{(item.task_decomposition_efficiency * 100).toFixed(2)}%</td>
                                                    <td>{(item.reasoning_relevancy * 100).toFixed(2)}%</td>
                                                    <td>{(item.response_coherence * 100).toFixed(2)}%</td>
                                                    <td>{item.efficiency_category}</td>
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                    {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                                </div>
                                ) : (
                                // Agents Efficiency accordion view
                                <div className={styles.accordionContainer}>
                                    {agentMetricsData.map((item, index) => (
                                        <details key={index} className={`${styles.accordionItem} ${styles.agentAccordionItem}`}>
                                            <summary className={styles.agentAccordionSummary}>
                                                <div className={styles.agentHeaderRow1}>
                                                    <span className={styles.agentQuery}>{item.user_query}</span>
                                                    <span className={styles.agentModel}>{item.model_used}</span>
                                                </div>
                                                <div className={styles.agentHeaderRow2}>
                                                    <span className={styles.agentMetric}>{(item.task_decomposition_efficiency * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.reasoning_relevancy * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.reasoning_coherence * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.agent_robustness * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.agent_consistency * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.answer_relevance * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.groundedness * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.response_fluency * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentMetric}>{(item.response_coherence * 100).toFixed(1)}%</span>
                                                    <span className={styles.agentCategory}>{item.efficiency_category}</span>
                                                    <span className={styles.agentEvalModel}>{item.model_used_for_evaluation}</span>
                                                </div>
                                            </summary>
                                            <div className={styles.responseCell}>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Task Decomposition Justification:</strong><br />
                                                    {item.task_decomposition_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Reasoning Relevancy Justification:</strong><br />
                                                    {item.reasoning_relevancy_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Reasoning Coherence Justification:</strong><br />
                                                    {item.reasoning_coherence_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Agent Robustness Justification:</strong><br />
                                                    {item.agent_robustness_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Agent Consistency Justification:</strong><br />
                                                    {item.agent_consistency_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Answer Relevance Justification:</strong><br />
                                                    {item.answer_relevance_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Groundedness Justification:</strong><br />
                                                    {item.groundedness_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Response Fluency Justification:</strong><br />
                                                    {item.response_fluency_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Response Coherence Justification:</strong><br />
                                                    {item.response_coherence_justification}
                                                </div>
                                                <div style={{marginBottom: '12px'}}>
                                                    <strong>Consistency Queries:</strong><br />
                                                    {item.consistency_queries}
                                                </div>
                                                <div>
                                                    <strong>Robustness Queries:</strong><br />
                                                    {item.robustness_queries}
                                                </div>
                                            </div>
                                        </details>
                                    ))}
                                    {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                                </div>
                            )
                            ) : (
                            <div className={styles.noData}>
                                {agentMetricsData.length > 0
                                    ? "No matching agent metrics data for selected agents"
                                    : "No agent metrics data available"}
                            </div>
                        )}
                    </div>
                );
            default:
                return <div className={styles.tabContent}>Evaluation content goes here</div>;
        }
    };    return (
        <>
            <div className={"evaluationResults"}>
                <div className={styles.tabsContainer}>                    <div className={styles.horizontalTabs}>
                        <div className={styles.filterAndTabs}>
                            {["Evaluation Records", "Tools Efficiency", "Agents Efficiency"].map((tab) => (
                            <div
                                key={tab}
                                className={`${styles.horizontalTab} ${activeTab === tab ? styles.activeTab : ''}`}
                                onClick={() => handleTabChange(tab)}
                            >
                                {tab}
                            </div>
                            ))}
                        </div>
                        <div className={styles.agentsFilterContainer}>
                            <p className={styles.filterLabel}>Filter by Agents:</p>
                            <div className={styles.filterControls}>
                                <AgentsMultiSelect onSelectionChange={handleAgentSelection} />
                                <button                                    className={styles.filterButton}
                                    onClick={handleFilterByAgents}
                                    disabled={loading || isFiltering || selectedAgentNames.length === 0}
                                >
                                    {isFiltering ? "Filtering..." : "Filter"}
                                </button>
                            </div>
                            <div className={styles.tableOrAccordionSwitch} onClick={handleViewSwitch}>
                                <span className={styles.tableOrAccordion}>
                                    <SVGIcons icon={isTableView ? "tableIcon" : "accordionIcon"} width={16} height={16} fill="#B8860B"/>
                                </span>
                            </div>
                        </div>
                    </div>
                    <div className={styles.tabContentContainer}>
                        {renderTabContent()}
                    </div>
                </div>
            </div>
        </>
    );
}

export default EvaluationScore;