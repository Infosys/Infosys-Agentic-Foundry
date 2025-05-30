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
} from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import { calculateDivs } from "../../util";
import { getAgentsByPageLimit } from "../../services/agentService";
import { getToolsByPageLimit } from "../../services/toolService";
import SearchInputToolsAgents from "../commonComponents/SearchInputTools";

const AgentOnboard = (props) => {
  const { onClose, tags, setNewAgentData,fetchAgents} = props;

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

  const { addMessage } = useMessage();
  const { fetchData, postData } = useFetch();

  const containerRef = useRef(null);
  const pageRef = useRef(1);
  const hasLoadedOnce = useRef(false);

  const fetchPaginatedData = async (pageNumber, divsCount) => {
    setLoading(true);
    try {
      if (selectedAgent === META_AGENT) {
        const response = await getAgentsByPageLimit({ page: pageNumber, limit: divsCount });
        const allDetails = response?.details || [];
        const filtered = allDetails.filter(
          (agent) =>
            agent.agentic_application_type === REACT_AGENT ||
            agent.agentic_application_type === MULTI_AGENT 
        );
        setAgents((prev) => [...prev, ...filtered]);
        setVisibleData((prev) => [...prev, ...filtered]);
        setTotalCount(response?.total_count || 0);
      } else {
        const response = await getToolsByPageLimit({ page: pageNumber, limit: divsCount });
        const toolsData = response?.details || [];
        setTools((prev) => [...prev, ...toolsData]);
        setVisibleData((prev) => [...prev, ...toolsData]);
        setTotalCount(response?.total_count || 0);
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

  const loadMoreData = useCallback(() => {
    if (loading || visibleData.length >= totalCount) return;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(containerRef, 149, 57, 26);
    setPage(nextPage);
    pageRef.current = nextPage;
    fetchPaginatedData(nextPage, divsCount);
  }, [loading, visibleData, totalCount]);

  const handleScroll = () => {
    const container = containerRef.current;
    if (
      container.scrollHeight - container.scrollTop <=
      container.clientHeight + 40
    ) {
      if (!searchTerm.trim()) {
        loadMoreData();
      }
    }
  };

  useEffect(() => {
    const container = containerRef.current;
    if (container) {
      container.addEventListener("scroll", handleScroll);
      return () => container.removeEventListener("scroll", handleScroll);
    }
  }, [visibleData, page, searchTerm]);

  const clearSearch = () => {
    setSearchTerm("");
    handleSearch("")
  };

  const handleSearch = async (searchValue) => {
    setSearchTerm(searchValue);
    if (searchValue.trim()) {
      try {
        setLoading(true);
        let data = [];
        if (selectedAgent === META_AGENT) {
          const res = await fetchData(`${APIs.GET_AGENTS_BY_SEARCH}/${searchValue}`);
          data = res?.filter(
            (a) =>
              a.agentic_application_type === REACT_AGENT ||
              a.agentic_application_type === MULTI_AGENT
          ) || [];
        } else {
          data = await fetchData(`${APIs.GET_TOOLS_BY_SEARCH}/${searchValue}`) || [];
        }
        setVisibleData(data);
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
    const payload = {
      ...value,
      tools_id:
        selectedAgent === META_AGENT
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
            <p>{`SELECT ${selectedAgent === META_AGENT ? "AGENT" : "TOOL"} TO ADD AGENT`}</p>
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
            {selectedAgent !== META_AGENT &&
              visibleData?.map((tool) => (
                <ToolCard
                  key={tool?.tool_id}
                  tool={tool}
                  tool_id={tool?.tool_id}
                  styles={styles}
                  setSelectedTool={setSelectedTool}
                />
              ))}
            {selectedAgent === META_AGENT &&
              visibleData?.map((agent) => (
                <ToolCard
                  key={agent?.agentic_application_id}
                  agent={agent}
                  agent_id={agent?.agentic_application_id}
                  styles={styles}
                  setSelectedAgents={setSelectedAgents}
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
            isMetaAgent={selectedAgent === META_AGENT}
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
