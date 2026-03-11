import React, { useState, useEffect, useRef } from "react";
import { useEndpointsService } from "../EvaluateService.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext.js";
import styles from "./EvaluationScore.module.css";
import SVGIcons from "../../Icons/SVGIcons.js";

// Expandable text component for truncating long content with "See more..." toggle
const ExpandableText = ({ label, text, maxLength = 150 }) => {
  const [isExpanded, setIsExpanded] = useState(false);

  if (!text) return null;

  const shouldTruncate = text.length > maxLength;
  const displayText = shouldTruncate && !isExpanded ? text.slice(0, maxLength) + "..." : text;

  return (
    <p className={styles.recordCardText}>
      {label && <strong>{label}:</strong>}{" "}
      <span className={isExpanded ? styles.expandedText : ""}>
        {displayText}
      </span>
      {shouldTruncate && (
        <button
          type="button"
          className={styles.seeMoreBtn}
          onClick={(e) => {
            e.stopPropagation();
            setIsExpanded(!isExpanded);
          }}
        >
          {isExpanded ? "See less" : "See more..."}
        </button>
      )}
    </p>
  );
};

const EvaluationScore = ({ activeMetricsSubTab, selectedAgentNames: propsSelectedAgentNames = [], selectedAgentTypes: propsSelectedAgentTypes = [], filterTrigger = 0 }) => {
  const [evaluationData, setEvaluationData] = useState([]);
  const [toolMetricsData, setToolMetricsData] = useState([]);
  const [agentMetricsData, setAgentMetricsData] = useState([]);
  // Use local state if prop is not provided, otherwise use prop
  const selectedAgentNames = propsSelectedAgentNames;
  const selectedAgentTypes = propsSelectedAgentTypes;
  const [loading, setLoading] = useState(false);
  const [isTableView, setIsTableView] = useState(false);
  const { getEvaluationData, getToolMetricsData, getAgentMetricsData, createLazyLoadHandler } = useEndpointsService();
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
  const prevFilterTriggerRef = useRef(filterTrigger);

  // Map activeMetricsSubTab prop to internal activeTab state for consistency
  const activeTab =
    activeMetricsSubTab === "evaluationRecords"
      ? "Evaluation Records"
      : activeMetricsSubTab === "toolsEfficiency"
        ? "Tools Efficiency"
        : activeMetricsSubTab === "agentsEfficiency"
          ? "Agents Efficiency"
          : "Evaluation Records";

  // Track previous filter to detect changes
  const prevFilterRef = useRef(JSON.stringify(selectedAgentNames));

  // Initial data fetch on mount
  useEffect(() => {
    if (hasInitialized.current) return;
    hasInitialized.current = true;
    fetchEvaluationRecord();
  }, []);

  // Trigger filter when filterTrigger prop changes (from parent SubHeader)
  useEffect(() => {
    if (prevFilterTriggerRef.current !== filterTrigger && hasInitialized.current) {
      prevFilterTriggerRef.current = filterTrigger;
      handleFilterByAgents();
    }
  }, [filterTrigger]);

  // Setup scroll event listeners for lazy loading
  useEffect(() => {
    const currentTableRef = getCurrentTableRef();

    if (!currentTableRef?.current) {
      return;
    }

    let handleScroll;

    switch (activeTab) {
      case "Evaluation Records":
        handleScroll = createLazyLoadHandler(
          "evaluation",
          evaluationTableRef,
          evaluationData,
          setEvaluationData,
          page,
          setPage,
          limit,
          selectedAgentNames.length > 0 ? selectedAgentNames.join(",") : null,
          setIsLoadingMore,
          hasMoreEvaluationData,
          setHasMoreEvaluationData,
          selectedAgentTypes.length > 0 ? selectedAgentTypes.join(",") : null
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
          selectedAgentNames.length > 0 ? selectedAgentNames.join(",") : null,
          setIsLoadingMore,
          hasMoreToolMetricsData,
          setHasMoreToolMetricsData,
          selectedAgentTypes.length > 0 ? selectedAgentTypes.join(",") : null
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
          selectedAgentNames.length > 0 ? selectedAgentNames.join(",") : null,
          setIsLoadingMore,
          hasMoreAgentMetricsData,
          setHasMoreAgentMetricsData,
          selectedAgentTypes.length > 0 ? selectedAgentTypes.join(",") : null
        );
        break;
      default:
        break;
    }

    if (handleScroll && currentTableRef.current) {
      currentTableRef.current.addEventListener("scroll", handleScroll);

      // Proper cleanup function
      return () => {
        if (currentTableRef.current) {
          currentTableRef.current.removeEventListener("scroll", handleScroll);
        }
      };
    }
  }, [
    activeTab,
    page,
    selectedAgentNames,
    selectedAgentTypes,
    evaluationData,
    toolMetricsData,
    agentMetricsData,
    limit,
    hasMoreEvaluationData,
    hasMoreToolMetricsData,
    hasMoreAgentMetricsData,
    isTableView,
  ]);

  // Auto-load more data if content doesn't fill the container
  useEffect(() => {
    const checkAndLoadMore = async () => {
      const currentTableRef = getCurrentTableRef();
      if (!currentTableRef?.current) return;

      const container = currentTableRef.current;
      const { scrollHeight, clientHeight } = container;

      // If content doesn't exceed container height and we have more data, load more
      const needsMoreContent = scrollHeight <= clientHeight;

      if (needsMoreContent && !isLoadingMore && !loading) {
        let shouldLoadMore = false;

        switch (activeTab) {
          case "Evaluation Records":
            shouldLoadMore = hasMoreEvaluationData && evaluationData.length > 0;
            break;
          case "Tools Efficiency":
            shouldLoadMore = hasMoreToolMetricsData && toolMetricsData.length > 0;
            break;
          case "Agents Efficiency":
            shouldLoadMore = hasMoreAgentMetricsData && agentMetricsData.length > 0;
            break;
          default:
            break;
        }

        if (shouldLoadMore) {
          setIsLoadingMore(true);
          try {
            const nextPage = page + 1;
            const agentNamesString = selectedAgentNames.length > 0 ? selectedAgentNames.join(",") : null;
            const agentTypesString = selectedAgentTypes.length > 0 ? selectedAgentTypes.join(",") : null;
            let response;

            switch (activeTab) {
              case "Evaluation Records":
                response = await getEvaluationData(agentNamesString, nextPage, limit, agentTypesString);
                if (response && Array.isArray(response) && response.length > 0) {
                  setEvaluationData((prevData) => [...prevData, ...response]);
                  setPage(nextPage);
                  if (response.length < limit) {
                    setHasMoreEvaluationData(false);
                  }
                } else {
                  setHasMoreEvaluationData(false);
                }
                break;
              case "Tools Efficiency":
                response = await getToolMetricsData(agentNamesString, nextPage, limit, agentTypesString);
                if (response && Array.isArray(response) && response.length > 0) {
                  setToolMetricsData((prevData) => [...prevData, ...response]);
                  setPage(nextPage);
                  if (response.length < limit) {
                    setHasMoreToolMetricsData(false);
                  }
                } else {
                  setHasMoreToolMetricsData(false);
                }
                break;
              case "Agents Efficiency":
                response = await getAgentMetricsData(agentNamesString, nextPage, limit, agentTypesString);
                if (response && Array.isArray(response) && response.length > 0) {
                  setAgentMetricsData((prevData) => [...prevData, ...response]);
                  setPage(nextPage);
                  if (response.length < limit) {
                    setHasMoreAgentMetricsData(false);
                  }
                } else {
                  setHasMoreAgentMetricsData(false);
                }
                break;
              default:
                break;
            }
          } catch (error) {
            console.error("Error auto-loading more data:", error);
          } finally {
            setIsLoadingMore(false);
          }
        }
      }
    };

    // Small delay to ensure DOM has updated
    const timeoutId = setTimeout(checkAndLoadMore, 100);
    return () => clearTimeout(timeoutId);
  }, [
    evaluationData,
    toolMetricsData,
    agentMetricsData,
    activeTab,
    isTableView,
    hasMoreEvaluationData,
    hasMoreToolMetricsData,
    hasMoreAgentMetricsData,
    isLoadingMore,
    loading,
    page,
    selectedAgentNames,
    selectedAgentTypes,
    limit,
    getEvaluationData,
    getToolMetricsData,
    getAgentMetricsData,
  ]);

  // Helper to get the current active table ref
  const getCurrentTableRef = () => {
    switch (activeTab) {
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
  }, [activeMetricsSubTab, selectedAgentNames]);

  // Load data when the active sub-tab changes
  useEffect(() => {
    if (hasInitialized.current) {
      handleTabChange(activeTab);
    }
  }, [activeMetricsSubTab]);

  // Fetch data for the current active tab without any filter
  const fetchDataForCurrentTab = async () => {
    setLoading(true);
    setPage(1);

    try {
      switch (activeTab) {
        case "Evaluation Records":
          const evalResponse = await getEvaluationData(null, 1, limit);
          if (evalResponse && Array.isArray(evalResponse) && evalResponse.length > 0) {
            setEvaluationData(evalResponse);
            setHasMoreEvaluationData(evalResponse.length === limit);
          } else {
            setEvaluationData([]);
            addMessage("No evaluation data found", "error");
            setHasMoreEvaluationData(false);
          }
          break;
        case "Tools Efficiency":
          const toolResponse = await getToolMetricsData(null, 1, limit);
          if (toolResponse && Array.isArray(toolResponse) && toolResponse.length > 0) {
            setToolMetricsData(toolResponse);
            setHasMoreToolMetricsData(toolResponse.length === limit);
          } else {
            setToolMetricsData([]);
            addMessage("No tool metrics data found", "error");
            setHasMoreToolMetricsData(false);
          }
          break;
        case "Agents Efficiency":
          const agentResponse = await getAgentMetricsData(null, 1, limit);
          if (agentResponse && Array.isArray(agentResponse) && agentResponse.length > 0) {
            setAgentMetricsData(agentResponse);
            setHasMoreAgentMetricsData(agentResponse.length === limit);
          } else {
            setAgentMetricsData([]);
            addMessage("No agent metrics data found", "error");
            setHasMoreAgentMetricsData(false);
          }
          break;
        default:
          break;
      }
    } catch (error) {
      addMessage(`Failed to fetch ${activeTab.toLowerCase()} data`, "error");
      console.error(`Error fetching ${activeTab.toLowerCase()} data:`, error);
    } finally {
      setLoading(false);
    }
  };

  const fetchEvaluationRecord = async () => {
    setLoading(true);
    try {
      // Initial load without any agent filter
      const response = await getEvaluationData(null, 1, limit);
      if (response && Array.isArray(response) && response.length > 0) {
        setEvaluationData(response);
        setHasMoreEvaluationData(response.length === limit);
      } else {
        setEvaluationData([]);
        addMessage("No evaluation data found", "error");
        setHasMoreEvaluationData(false);
      }
    } catch (error) {
      addMessage("Failed to fetch evaluation data", "error");
      setHasMoreEvaluationData(false);
      console.error("Error fetching evaluation data:", error);
    } finally {
      setLoading(false);
    }
  };

  const handleFilterByAgents = async () => {
    // When all filters are cleared, fetch unfiltered data for the current tab
    if (selectedAgentNames.length === 0 && selectedAgentTypes.length === 0) {
      fetchDataForCurrentTab();
      return;
    }

    setLoading(true);
    setPage(1); // Reset page to 1 when filtering

    try {
      // const agentNamesString = selectedAgentNames.join(",");
      // Pass null if no agents selected to fetch all data
      const agentNamesString = selectedAgentNames.length > 0 ? selectedAgentNames.join(",") : null;
      const agentTypesString = selectedAgentTypes.length > 0 ? selectedAgentTypes.join(",") : null;

      switch (activeTab) {
        case "Evaluation Records":
          const evaluationData = await getEvaluationData(agentNamesString, 1, limit, agentTypesString);
          if (evaluationData && Array.isArray(evaluationData) && evaluationData.length > 0) {
            setEvaluationData(evaluationData);
            setHasMoreEvaluationData(evaluationData.length === limit);
          } else {
            setEvaluationData([]);
            addMessage("No evaluation data found", "error");
            setHasMoreEvaluationData(false);
          }
          break;
        case "Tools Efficiency":
          const toolData = await getToolMetricsData(agentNamesString, 1, limit, agentTypesString);
          if (toolData && Array.isArray(toolData) && toolData.length > 0) {
            setToolMetricsData(toolData);
            setHasMoreToolMetricsData(toolData.length === limit);
          } else {
            setToolMetricsData([]);
            addMessage("No tool metrics data found", "error");
            setHasMoreToolMetricsData(false);
          }
          break;
        case "Agents Efficiency":
          const agentData = await getAgentMetricsData(agentNamesString, 1, limit, agentTypesString);
          if (agentData && Array.isArray(agentData) && agentData.length > 0) {
            setAgentMetricsData(agentData);
            setHasMoreAgentMetricsData(agentData.length === limit);
          } else {
            setAgentMetricsData([]);
            addMessage("No agent metrics data found", "error");
            setHasMoreAgentMetricsData(false);
          }
          break;
        default:
          break;
      }
    } catch (error) {
      addMessage(`Failed to fetch ${activeTab.toLowerCase()} data with filter`, "error");
      setEvaluationData([]);
      setToolMetricsData([]);
      setAgentMetricsData([]);
      setHasMoreEvaluationData(false);
      setHasMoreToolMetricsData(false);
      setHasMoreAgentMetricsData(false);
      console.error(`Error fetching ${activeTab.toLowerCase()} data with filter:`, error);
    } finally {
      setLoading(false);
    }
  };

  const handleTabChange = async (tab) => {
    setLoading(true);
    setPage(1); // Reset page to 1 when changing tabs

    try {
      const agentNamesString = selectedAgentNames.length > 0 ? selectedAgentNames.join(",") : null;
      const agentTypesString = selectedAgentTypes.length > 0 ? selectedAgentTypes.join(",") : null;

      if (selectedAgentNames.length > 0 || selectedAgentTypes.length > 0) {
        // If we have selected agents or types, use them as filter
        if (tab === "Tools Efficiency") {
          const data = await getToolMetricsData(agentNamesString, 1, limit, agentTypesString);
          if (data && Array.isArray(data) && data.length > 0) {
            setToolMetricsData(data);
            setHasMoreToolMetricsData(data.length === limit);
          } else {
            setToolMetricsData([]);
            addMessage("No tool metrics data found", "error");
            setHasMoreToolMetricsData(false);
          }
        } else if (tab === "Agents Efficiency") {
          const data = await getAgentMetricsData(agentNamesString, 1, limit, agentTypesString);
          if (data && Array.isArray(data) && data.length > 0) {
            setAgentMetricsData(data);
            setHasMoreAgentMetricsData(data.length === limit);
          } else {
            setAgentMetricsData([]);
            addMessage("No agent metrics data found", "error");
            setHasMoreAgentMetricsData(false);
          }
        } else if (tab === "Evaluation Records") {
          const data = await getEvaluationData(agentNamesString, 1, limit, agentTypesString);
          if (data && Array.isArray(data) && data.length > 0) {
            setEvaluationData(data);
            setHasMoreEvaluationData(data.length === limit);
          } else {
            setEvaluationData([]);
            addMessage("No evaluation data found", "error");
            setHasMoreEvaluationData(false);
          }
        }
      } else {
        // No selected agents or types, fetch all data
        if (tab === "Tools Efficiency" && toolMetricsData.length === 0) {
          const data = await getToolMetricsData(null, 1, limit, null);
          if (data && Array.isArray(data) && data.length > 0) {
            setToolMetricsData(data);
            setHasMoreToolMetricsData(data.length === limit);
          } else {
            setToolMetricsData([]);
            addMessage("No tool metrics data found", "error");
            setHasMoreToolMetricsData(false);
          }
        } else if (tab === "Agents Efficiency" && agentMetricsData.length === 0) {
          const data = await getAgentMetricsData(null, 1, limit, null);
          if (data && Array.isArray(data) && data.length > 0) {
            setAgentMetricsData(data);
            setHasMoreAgentMetricsData(data.length === limit);
          } else {
            setAgentMetricsData([]);
            addMessage("No agent metrics data found", "error");
            setHasMoreAgentMetricsData(false);
          }
        } else if (tab === "Evaluation Records" && evaluationData.length === 0) {
          const data = await getEvaluationData(null, 1, limit, null);
          if (data && Array.isArray(data) && data.length > 0) {
            setEvaluationData(data);
            setHasMoreEvaluationData(data.length === limit);
          } else {
            setEvaluationData([]);
            addMessage("No evaluation data found", "error");
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

  const renderTabContent = () => {
    // We're now filtering through API calls, so we don't need client-side filtering
    switch (activeTab) {
      case "Evaluation Records":
        return (
          <div className={styles.tabContent}>
            {loading ? (
              <Loader />
            ) : evaluationData.length > 0 ? (
              isTableView ? (
                <div className={styles.tableContainer}>
                  <div className={styles.tableWrapper} ref={evaluationTableRef}>
                    <table className={styles.evaluationTable}>
                      <thead>
                        <tr>
                          <th>Id</th>
                          <th>Agent Name</th>
                          <th>Agent Type</th>
                          <th>Model Used</th>
                          <th>Status</th>
                          <th>Query</th>
                          <th>Response</th>
                        </tr>
                      </thead>
                      <tbody>
                        {evaluationData.map((item, index) => (
                          <tr key={index}>
                            <td>{item.id}</td>
                            <td>{item.agent_name}</td>
                            <td>{item.agent_type}</td>
                            <td>{item.model_used}</td>
                            <td>{item.evaluation_status}</td>
                            <td>
                              <ExpandableText label="" text={item.query} maxLength={80} />
                            </td>
                            <td>
                              <ExpandableText label="" text={item.response} maxLength={80} />
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                </div>
              ) : (
                // New card-based list view for Evaluation Records
                <div className={styles.recordsList} ref={evaluationTableRef}>
                  {evaluationData.map((item, index) => (
                    <div key={index} className={styles.recordCard}>
                      <div className={styles.recordCardHeader}>
                        <div className={styles.recordCardInfo}>
                          <h3 className={styles.recordCardTitle} title={item.agent_name}>
                            {item.agent_name}
                          </h3>
                          <p className={styles.recordCardAgentType}>{item.agent_type}</p>
                        </div>
                        <div className={styles.recordCardStatus}>{item.evaluation_status}</div>
                      </div>
                      <div className={styles.recordCardBody}>
                        <ExpandableText label="Query" text={item.query} maxLength={120} />
                        <ExpandableText label="Response" text={item.response} maxLength={120} />
                      </div>
                    </div>
                  ))}
                  {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                </div>
              )
            ) : (
              <div className={styles.noData}>{evaluationData.length > 0 ? "No matching evaluation data for selected agents" : "No evaluation data available"}</div>
            )}
          </div>
        );
      case "Tools Efficiency":
        return (
          <div className={styles.tabContent}>
            {loading ? (
              <Loader />
            ) : toolMetricsData.length > 0 ? (
              isTableView ? (
                <div className={styles.tableContainer}>
                  <div className={styles.tableWrapper} ref={toolMetricsTableRef}>
                    <table className={styles.evaluationTable}>
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th>Evaluation Id</th>
                          <th>Query</th>
                          <th>Tool Selection Accuracy</th>
                          <th>Tool Usage Efficiency</th>
                          <th>Tool Call Precision</th>
                          <th>Success Rate</th>
                          <th>Tool Utilization Efficiency</th>
                          <th>Efficiency Category</th>
                          <th>Model Used for Evaluation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {toolMetricsData.map((item, index) => (
                          <tr key={index}>
                            <td>{item.id}</td>
                            <td>{item.evaluation_id}</td>
                            <td>
                              <ExpandableText label="" text={item.user_query} maxLength={80} />
                            </td>
                            <td>{item.tool_selection_accuracy}</td>
                            <td>{item.tool_usage_efficiency}</td>
                            <td>{item.tool_call_precision}</td>
                            <td>{item.tool_call_success_rate}</td>
                            <td>{item.tool_utilization_efficiency}</td>
                            <td>{item.tool_utilization_efficiency_category}</td>
                            <td>{item.model_used_for_evaluation}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                </div>
              ) : (
                // Tools Efficiency card view - same style as Evaluation Records
                <div className={styles.recordsList} ref={toolMetricsTableRef}>
                  {toolMetricsData.map((item, index) => (
                    <div key={index} className={styles.recordCard}>
                      <div className={styles.recordCardHeader}>
                        <div className={styles.recordCardInfo}>
                          <h3 className={styles.recordCardTitle} title={item.user_query}>
                            {item.user_query?.length > 60 ? item.user_query.slice(0, 60) + "..." : item.user_query}
                          </h3>
                          <p className={styles.recordCardAgentType}>{item.model_used}</p>
                        </div>
                        <div className={styles.recordCardStatus}>{item.tool_utilization_efficiency_category}</div>
                      </div>
                      <div className={styles.recordCardBody}>
                        <div className={styles.recordCardMetrics}>
                          <p className={styles.recordCardText}>
                            <strong>Tool Selection Accuracy:</strong> {(item.tool_selection_accuracy * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Tool Usage Efficiency:</strong> {(item.tool_usage_efficiency * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Tool Call Precision:</strong> {(item.tool_call_precision * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Success Rate:</strong> {(item.tool_call_success_rate * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Utilization Efficiency:</strong> {(item.tool_utilization_efficiency * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Evaluation Model:</strong> {item.model_used_for_evaluation}
                          </p>
                        </div>
                        <ExpandableText label="User Query" text={item.user_query} maxLength={120} />
                        <ExpandableText label="Agent Response" text={item.agent_response} maxLength={120} />
                      </div>
                    </div>
                  ))}
                  {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                </div>
              )
            ) : (
              <div className={styles.noData}>{toolMetricsData.length > 0 ? "No matching tool metrics data for selected agents" : "No tool metrics data available"}</div>
            )}
          </div>
        );
      case "Agents Efficiency":
        return (
          <div className={styles.tabContent}>
            {loading ? (
              <Loader />
            ) : agentMetricsData.length > 0 ? (
              isTableView ? (
                <div className={styles.tableContainer}>
                  <div className={styles.tableWrapper} ref={agentMetricsTableRef}>
                    <table className={styles.evaluationTable}>
                      <thead>
                        <tr>
                          <th>ID</th>
                          <th> Evaluation Id</th>
                          <th>Query</th>
                          <th>Task Decomposition</th>
                          <th>Reasoning Relevancy</th>
                          <th>Reasoning Coherence</th>
                          <th>Answer Relevance</th>
                          <th>Groundedness</th>
                          <th>Response Fluency</th>
                          <th>Response Coherence</th>
                          <th>Communication Efficiency</th>
                          <th>Efficiency Category</th>
                          <th>Model Used for Evaluation</th>
                        </tr>
                      </thead>
                      <tbody>
                        {agentMetricsData.map((item, index) => (
                          <tr key={index}>
                            <td>{item.id}</td>
                            <td>{item.evaluation_id}</td>
                            <td>
                              <ExpandableText label="" text={item.user_query} maxLength={80} />
                            </td>
                            <td>{item.task_decomposition_efficiency}</td>
                            <td>{item.reasoning_relevancy}</td>
                            <td>{item.reasoning_coherence}</td>
                            <td>{item.answer_relevance}</td>
                            <td>{item.groundedness}</td>
                            <td>{item.response_fluency}</td>
                            <td>{item.response_coherence}</td>
                            <td>{item.communication_efficiency_score || "--"}</td>
                            <td>{item.efficiency_category}</td>
                            <td>{item.model_used_for_evaluation}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                  {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                </div>
              ) : (
                // Agents Efficiency card view - same style as Evaluation Records
                <div className={styles.recordsList} ref={agentMetricsTableRef}>
                  {agentMetricsData.map((item, index) => (
                    <div key={index} className={styles.recordCard}>
                      <div className={styles.recordCardHeader}>
                        <div className={styles.recordCardInfo}>
                          <h3 className={styles.recordCardTitle} title={item.user_query}>
                            {item.user_query?.length > 60 ? item.user_query.slice(0, 60) + "..." : item.user_query}
                          </h3>
                          <p className={styles.recordCardAgentType}>{item.model_used}</p>
                        </div>
                        <div className={styles.recordCardStatus}>{item.efficiency_category}</div>
                      </div>
                      <div className={styles.recordCardBody}>
                        <div className={styles.recordCardMetrics}>
                          <p className={styles.recordCardText}>
                            <strong>Task Decomposition:</strong> {(item.task_decomposition_efficiency * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Reasoning Relevancy:</strong> {(item.reasoning_relevancy * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Reasoning Coherence:</strong> {(item.reasoning_coherence * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Answer Relevance:</strong> {(item.answer_relevance * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Groundedness:</strong> {(item.groundedness * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Response Fluency:</strong> {(item.response_fluency * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Response Coherence:</strong> {(item.response_coherence * 100).toFixed(1)}%
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Communication Efficiency:</strong> {item.communication_efficiency_score || "--"}
                          </p>
                          <p className={styles.recordCardText}>
                            <strong>Evaluation Model:</strong> {item.model_used_for_evaluation}
                          </p>
                        </div>
                        <ExpandableText label="User Query" text={item.user_query} maxLength={120} />
                      </div>
                    </div>
                  ))}
                  {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
                </div>
              )
            ) : (
              <div className={styles.noData}>{agentMetricsData.length > 0 ? "No matching agent metrics data for selected agents" : "No agent metrics data available"}</div>
            )}
          </div>
        );
      default:
        return <div className={styles.tabContent}>Evaluation content goes here</div>;
    }
  };
  return (
    <div className={`container ${styles.metricsContainer}`}>
      <div className={styles.tabsContainer}>
        {/* Main content container with card design */}
        <div className={styles.recordsContainer}>
          {/* Header with title and view toggle buttons */}
          <div className={styles.recordsHeader}>
            <h2 className={styles.recordsTitle}>{activeTab}</h2>
            <div className={styles.viewToggleGroup}>
              <button
                className={`${styles.viewToggleBtn} ${!isTableView ? styles.active : ""}`}
                onClick={() => setIsTableView(false)}
                aria-label="List view"
                title="List view"
              >
                <SVGIcons icon="accordionIcon" width={20} height={20} />
              </button>
              <button
                className={`${styles.viewToggleBtn} ${isTableView ? styles.active : ""}`}
                onClick={() => setIsTableView(true)}
                aria-label="Table view"
                title="Table view"
              >
                <SVGIcons icon="tableIcon" width={20} height={20} />
              </button>
            </div>
          </div>

          {/* Tab content */}
          <div className={styles.tabContentContainer}>{renderTabContent()}</div>
        </div>
      </div>
    </div>
  );
};

export default EvaluationScore;