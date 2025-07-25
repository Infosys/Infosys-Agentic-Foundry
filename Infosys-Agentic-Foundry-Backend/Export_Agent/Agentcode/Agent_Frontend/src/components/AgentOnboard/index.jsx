import React, { useEffect, useState, useCallback, useRef } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "../../css_modules/AgentOnboard.module.css";
import { APIs } from "../../constant";
import ToolCard from "./ToolCard";
import AgentForm from "./AgentForm";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";
import DropDown from "../commonComponents/DropDowns/DropDown";
import {
  agentTypes,
  MULTI_AGENT,
  REACT_AGENT,
  META_AGENT,
  PLANNER_META_AGENT,
  REACT_CRITIC_AGENT,
  PLANNER_EXECUTOR_AGENT
} from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import { calculateDivs } from "../../util";
import { getToolsSearchByPageLimit,getAgentsSearchByPageLimit } from "../../services/toolService";
import SearchInputToolsAgents from "../commonComponents/SearchInputTools";
import { debounce } from "lodash"; 

const AgentOnboard = (props) => {
  const { onClose, tags, setNewAgentData,fetchAgents,agentsListData} = props;

  const [tools, setTools] = useState([]);
  const [agents, setAgents] = useState([]);
  const [selectedTool, setSelectedTool] = useState([]);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState("react_agent");
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState("");
  const [loading, setLoading] = useState(false);
  const [totalCount, setTotalCount] = useState(0);
  const [loader, setLoaderState] = useState(false);
    const isLoadingRef = React.useRef(false);

  const { addMessage } = useMessage();
  const { postData } = useFetch();

  const containerRef = useRef(null);
  const pageRef = useRef(1);
  const hasLoadedOnce = useRef(false);

  const fetchPaginatedData = async (pageNumber, divsCount) => {
    setLoading(true);
    try {
      if (selectedAgent === META_AGENT || selectedAgent ===  PLANNER_META_AGENT) {
        const response = await getAgentsSearchByPageLimit({ page: pageNumber, limit: divsCount, search: searchTerm });
        const allDetails = response || [];
        const filtered = allDetails.filter(
          (agent) =>
            agent.agentic_application_type === REACT_AGENT ||
            agent.agentic_application_type === MULTI_AGENT ||
            agent.agentic_application_type === REACT_CRITIC_AGENT ||
            agent.agentic_application_type === PLANNER_EXECUTOR_AGENT
        );
        setAgents((prev) => pageNumber === 1 ? filtered : [...prev, ...filtered]);
        setVisibleData((prev) => pageNumber === 1 ? filtered : [...prev, ...filtered]);
        setTotalCount(response?.length || 0);
      } else {
        const response = await getToolsSearchByPageLimit({ page: pageNumber, limit: divsCount, search: searchTerm });
        const toolsData = response || [];
        setTools((prev) => pageNumber === 1 ? toolsData : [...prev, ...toolsData]);
        setVisibleData((prev) => pageNumber === 1 ? toolsData : [...prev, ...toolsData]);
        setTotalCount(response?.length || 0);
      }
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!hasLoadedOnce.current) {
      hasLoadedOnce.current = true;
      const divsCount = calculateDivs(containerRef, 149, 57, 26);
      setPage(1);
      pageRef.current = 1;
      setVisibleData([]);
      setAgents([]);
      setTools([]);
      fetchPaginatedData(1, divsCount);
    }
  }, [selectedAgent]);


  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    // Extract the check logic into a separate function
    const checkAndLoadMore = () => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 40 &&
        !loading && !isLoadingRef.current // Prevent if already loading
      ) {
        handleScrollLoadMore();
      }
    };

    const debouncedCheckAndLoad = debounce(checkAndLoadMore, 200); // 200ms debounce

    const handleResize = () => {
      debouncedCheckAndLoad();
    };

    window.addEventListener('resize', handleResize);
    container.addEventListener('scroll', debouncedCheckAndLoad);

    return () => {
      window.removeEventListener('resize', handleResize);
      debouncedCheckAndLoad.cancel && debouncedCheckAndLoad.cancel();
      container.removeEventListener('scroll', debouncedCheckAndLoad);
    };
  }, [ visibleData.length, totalCount, searchTerm]);

   const handleScrollLoadMore = async () => {
      if (loader || isLoadingRef.current) return; // Prevent multiple calls
      isLoadingRef.current = true;
      const nextPage = pageRef.current + 1;
      const divsCount = calculateDivs(containerRef, 149, 57, 26);
      
        try {
          setLoaderState(true);
          setLoading && setLoading(true);
          let newData = [];
          if (searchTerm.trim()) {
            // Only call search API if searchTerm is present
            if (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) {
              const res = await getAgentsSearchByPageLimit({
                page: nextPage,
                limit: divsCount,
                search: searchTerm,
              });
              newData = (res || []).filter(
                (a) =>
                  (a.agentic_application_type === REACT_AGENT ||
                    a.agentic_application_type === MULTI_AGENT || 
                    a.agentic_application_type === REACT_CRITIC_AGENT ||
                    a.agentic_application_type === PLANNER_EXECUTOR_AGENT)
              );
            } else {
              const res = await getToolsSearchByPageLimit({
                page: nextPage,
                limit: divsCount,
                search: searchTerm,
              });
              newData = (res || [])
            }
            setVisibleData((prev) => [...prev, ...newData]);
          } else {
            // Only call fetchToolsData if no searchTerm
            await fetchPaginatedData(nextPage, divsCount);
          }
          setPage(nextPage);
          pageRef.current = nextPage;
        } catch (err) {
          console.error(err);
        } finally {
          setLoaderState(false);
          setLoading && setLoading(false);
          isLoadingRef.current = false;
        }
    };


  const clearSearch = () => {
     setSearchTerm("");
     setVisibleData([]);
     
     const divsCount = calculateDivs(containerRef, 149, 57, 26);
     setPage(1);
     pageRef.current = 1;
     fetchPaginatedData(1, divsCount);
  };

  const handleSearch = async (searchValue) => {
    setSearchTerm(searchValue);
    setVisibleData([]);
    setPage(1);
    pageRef.current = 1;
    if (searchValue.trim()) {
      try {
        setLoading(true);
        let data = [];
        const divsCount = calculateDivs(containerRef, 149, 57, 26);
        if (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT) {
          const response = await getAgentsSearchByPageLimit({
            page: 1,
            limit: divsCount,
            search: searchValue,
          });
          data = response || [];
          data = data.filter(
            (a) =>
              a.agentic_application_type === REACT_AGENT ||
              a.agentic_application_type === MULTI_AGENT ||
              a.agentic_application_type === REACT_CRITIC_AGENT ||
              a.agentic_application_type === PLANNER_EXECUTOR_AGENT
          );
        } else {
          const response = await getToolsSearchByPageLimit({
            page: 1,
            limit: divsCount,
            search: searchValue,
          });
          data = response || [];
        }
        setVisibleData(data);
        setTotalCount(data.length);
      } catch (err) {
        console.error(err);
        setVisibleData([]);
      } finally {
        setLoading(false);
      }
    } else {
      const divsCount = calculateDivs(containerRef, 149, 57, 26);
      setVisibleData([]);
      setPage(1);
      pageRef.current = 1;
      fetchPaginatedData(1, divsCount);
    }
  };



  const submitForm = async (value, callBack) => {
    setLoading(true);
    const payload = {
      ...value,
      tools_id:
        (selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT)
          ? selectedAgents?.map((agent) => agent?.agentic_application_id)
          : selectedTool?.map((tool) => tool?.tool_id),
    };

    try {
      let url = "";
      switch (selectedAgent) {
        case REACT_AGENT:
          url = APIs.ONBOARD_AGENT;
          break;
        case MULTI_AGENT:
          url = APIs.ONBOARD_MULTI_AGENT;
          break;
        case META_AGENT:
          url = APIs.ONBOARD_META_AGENT;
          break;
           case PLANNER_META_AGENT:
          url = APIs.ONBOARD_PLANNER_META_AGENT;
          break;
        case REACT_CRITIC_AGENT:
          url = APIs.ONBOARD_REACT_CRITIC_AGENT;
          break;
        case PLANNER_EXECUTOR_AGENT:
          url = APIs.ONBOARD_PLANNER_EXECUTOR_AGENT
          break;
        default:
          break;
      }      
      const response = await postData(url, payload);
      if (response?.result?.is_created) {
        setNewAgentData(response.result);
        addMessage("Agent has been added successfully!", "success");
        setSelectedTool([]);
        setSelectedAgents([]);
        await fetchAgents();
        callBack(response);
      } else {
        addMessage(response?.result?.message || "Unknown error", "error");
      }
    } catch (e) {
      console.error(e);
    }
    finally{
      setLoading(false);
    }
  };

  const handleClose = () => {
    onClose();
  };


  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h6>ONBOARD AGENT</h6>
        <button onClick={handleClose}>
          <SVGIcons icon="close-icon" color="#7F7F7F" width={28} height={28} />
        </button>
      </div>
      <div className={styles.dashboardContainer}>
        <div className={styles.agentToolsContainer} ref={containerRef}>
          <div className={styles.subHeader}>
            <p>{`SELECT ${(selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT)? "AGENT" : "TOOL"} TO ADD AGENT`}</p>
            <SearchInputToolsAgents
              inputProps={{ placeholder: "SEARCH" }}
              handleSearch={handleSearch}
              clearSearch={clearSearch}
            />
          </div>
          <div className={styles.selectContainer}>
            <label htmlFor="model_name">Agent Type</label>
            <DropDown
              options={agentTypes}
              value={selectedAgent}
              onChange={(e) => {
                hasLoadedOnce.current = false;
                setSelectedAgent(e?.target?.value);
              }}
            />
          </div>
          <div className={styles.toolsCards}>
            {((selectedAgent !== META_AGENT )&& (selectedAgent !== PLANNER_META_AGENT))&&
            
              visibleData?.map((tool) => (
                
                <ToolCard
                  key={tool?.tool_id}
                  tool={tool}
                  tool_id={tool?.tool_id}
                  styles={styles}
                  setSelectedTool={setSelectedTool}
                  selectedTool={selectedTool}
                  selectedAgents={selectedAgents}
                />
              ))}
            {(selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT)   &&
              visibleData?.map((agent) => (
                <ToolCard
                  key={agent?.agentic_application_id}
                  agent={agent}
                  agent_id={agent?.agentic_application_id}
                  styles={styles}
                  setSelectedAgents={setSelectedAgents}
                  selectedTool={selectedTool}
                  selectedAgents={selectedAgents}
                />
              ))}
          </div>
        </div>
        <div className={styles.agentDetailContainer}>
          <AgentForm
            styles={styles}
            selectedTool={selectedTool}
            selectedAgents={selectedAgents}
            handleClose={handleClose}
            submitForm={submitForm}
            isMetaAgent={(selectedAgent === META_AGENT || selectedAgent === PLANNER_META_AGENT)}
            selectedAgent={selectedAgent}
            loading={loading}
            tags={tags}
            setSelectedAgents={setSelectedAgents}
            setSelectedTool={setSelectedTool}
          />
        </div>
      </div>
      {loading && <Loader />}
    </div>
  );
};

export default AgentOnboard;
