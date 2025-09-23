import React, { useEffect, useState, useCallback, useRef } from "react";
import styles from "../../css_modules/ListOfAgents.module.css";
import AgentCard from "./AgentCard";
import { APIs, REACT_AGENT, agentTypesDropdown } from "../../constant";
import SubHeader from "../commonComponents/SubHeader";
import AgentOnboard from "../AgentOnboard";
import UpdateAgent from "./UpdateAgent.jsx";
import useAxios from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import FilterModal from "../commonComponents/FilterModal.jsx";
import { calculateDivs } from "../../util";
import { getAgentsSearchByPageLimit, exportAgents } from "../../services/toolService.js";
import { debounce } from "lodash";
import Cookies from "js-cookie";
const ListOfAgents = () => {
  const [plusBtnClicked, setPlusBtnClicked] = useState(false);
  const [editAgentData, setEditAgentData] = useState("");
  const [agentsListData, setAgentsListData] = useState([]);
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState("");
  const [agentsList, setAgentsList] = useState([]);
  const [filterModal, setFilterModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [selectedAgentType, setSelectedAgentType] = useState("");
  const selectedAgentTypeRef = useRef("");
  const [selectedAgentIds, setSelectedAgentIds] = useState([]);
  const visibleAgentsContainerRef = useRef(null);
  const [totalAgentCount, setTotalAgentCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const { addMessage, setShowPopup } = useMessage();
  const isLoadingRef = React.useRef(false);
  const [loader, setLoaderState] = useState(false);
  const handleAddMessage = (message, type) => {
    addMessage(message, type);
  };

  const { fetchData, deleteData } = useAxios();
  const pageRef = useRef(1);
  const getTags = async () => {
    try {
      const data = await fetchData(APIs.GET_TAGS);
      setTags(data);
    } catch {
      console.error("Tags not fetched");
    }
  };
  // Use a ref to ensure tags are fetched only once
  const hasLoadedTagsOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedTagsOnce.current) return;
    hasLoadedTagsOnce.current = true;
    getTags();
  }, [plusBtnClicked, editAgentData]);

  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loading]);

  const getAgentsData = async (pageNumber, divsCount) => {
    setLoading(true);
    try {
      const response = await getAgentsSearchByPageLimit({ page: pageNumber, limit: divsCount, search: "" });
      const data = response || [];

      if (pageNumber === 1) {
        setAgentsList(data); // Save the initial list of agents
        setVisibleData(data); // Ensure initial load is rendered
      }else{
       setVisibleData((prev) => [...prev, ...data]);
      }
     
      setTotalAgentCount(data?.length || 0);
    } catch {
      console.error("Error fetching tools");
    } finally {
      setLoading(false);
    }
  };
 
  const fetchAgents = async () => {
    try {
      const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
 
      pageRef.current = 1;
      setPage(1);
 
      getAgentsData(1, divsCount);
    } catch (e) {
      const errorMsg = e?.response?.data?.message || e?.message;
      handleAddMessage(errorMsg, "error");
      console.error("Fetch Agents Error");
    }
  };
 
  const deleteAgent = async (id, email, isAdmin = false) => {
    try {
      await deleteData(APIs.DELETE_AGENT + id, {
        user_email_id: email,
        is_admin: isAdmin,
      });
      handleAddMessage("AGENT HAS BEEN DELETED SUCCESSFULLY !", "success");
      return true;
    } catch (error) {
      const errorMsg = error?.response?.data?.message || error?.message;
      handleAddMessage(errorMsg, "error");
      console.error("Delete Agent Error");
      return false;
    }
  };
 
 
  const handleSearch = async (searchValue,divsCount,pageNumber) => {
      setSearchTerm(searchValue || "");
      setPage(1);
      pageRef.current = 1;
      setVisibleData([]);
      if (searchValue.trim()) {
        try {
          setLoading(true);
          // Use the new API endpoint for search
          const response = await getAgentsSearchByPageLimit({
            page: pageNumber,
            limit: divsCount,
            search: searchValue,
          });
          let dataToSearch = response || [];
          if (selectedTags?.length > 0) {
            dataToSearch = dataToSearch.filter(
              (item) =>
                item.tags &&
                item.tags.some((tag) => selectedTags.includes(tag?.tag_name))
            );
          }
 
          // Update visibleData with the filtered data
          setVisibleData(dataToSearch);
        } catch (error) {
          console.error("Error fetching search results:", error);
          setVisibleData([]); // Clear visibleData on error
        } finally {
          setLoading(false); // Hide loader
        }
      } else {
        // If search term is empty, reset to default data
        setVisibleData(agentsList); // Reset to the initial list of tools
      }
    };
 
   const clearSearch = () => {
        setSearchTerm("");
        setVisibleData([]);
        const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
        setPage(1);
        pageRef.current = 1;
        getAgentsData(1, divsCount);
     }
 
  const hasLoadedOnce = useRef(false);
 
  useEffect(() => {
    const container = visibleAgentsContainerRef?.current;
    if (!container) return;
 
    // Extract the check logic into a separate function
    const checkAndLoadMore = () => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 10 &&
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
  }, [visibleAgentsContainerRef]);
 
const handleScrollLoadMore = async () => {
      if (loader || isLoadingRef.current) return; // Prevent multiple calls
      isLoadingRef.current = true;
      const nextPage = pageRef.current + 1;
      const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
      try {
        setLoaderState(true);
        setLoading && setLoading(true);
        let newData = [];
        if (searchTerm.trim()) {
          const res = await getAgentsSearchByPageLimit({
            page: nextPage,
            limit: divsCount,
            search: searchTerm,
          });
          newData = res || [];
        } else if (selectedAgentTypeRef.current) {
          const res = await getAgentsSearchByPageLimit({
            page: nextPage,
            limit: divsCount,
            agent_type: selectedAgentTypeRef.current,
          });
          newData = res || [];
        } else {
          const res = await getAgentsSearchByPageLimit({
            page: nextPage,
            limit: divsCount,
          });
          newData = res || [];
        }
        if (selectedTags?.length > 0) {
          newData = newData.filter(
            (item) =>
              item.tags &&
              item.tags.some((tag) => selectedTags.includes(tag?.tag_name))
          );
        }
        setVisibleData((prev) => [...prev, ...newData]);
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
 
  useEffect(() => {
    if (hasLoadedOnce.current) return; // prevent duplicate initial load
      hasLoadedOnce.current = true;
    fetchAgents();
  }, []);
 
  const handleRefresh = () => {
    clearSearch();
    setSelectedTags([]);
    setSelectedAgentType("");
    selectedAgentTypeRef.current = "";
  };
 
  const onSettingClick = () => {
    setFilterModal(true);
  };
 
  const onPlusClick = () => {
    setPlusBtnClicked(true);
  };
 
  const onOnboardClose = () => {
    setPlusBtnClicked(false);
  };
 
  const onAgentEdit = (data) => {
    setEditAgentData(data);
    setPlusBtnClicked(false);
  };
 
  const handleUpdateAgentClose = () => {
    setPlusBtnClicked(false);
    setEditAgentData(null);
  };
 
  const handleFilter = (selectedTags) => {
    setSelectedTags(selectedTags);
 
    if (selectedTags?.length > 0) {
      const filteredData = agentsList.filter(
        (item) =>
          item.tags &&
          item.tags.some((tag) => selectedTags.includes(tag.tag_name))
      );
      setVisibleData(filteredData);
    } else {
      setVisibleData(agentsList);
    }
  };
 
  const handleAgentTypeChange = async (e) => {
    const type = e.target.value;
    setSelectedAgentType(type);
    selectedAgentTypeRef.current = type;
    setSearchTerm("");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    setLoading(true);
    try {
      const response = await getAgentsSearchByPageLimit({
        page: 1,
        limit: divsCount,
        agent_type: type,
      });
      setVisibleData(response || []);
    } catch (error) {
      setVisibleData([]);
    } finally {
      setLoading(false);
    }
  };
  const handleAgentSelect = (agentId, checked) => {
    setSelectedAgentIds((prev) =>
      checked ? [...prev, agentId] : prev.filter((id) => id !== agentId)
    );
  };
 
  const handleExportSelected = async () => {
    if (selectedAgentIds.length === 0) return;
    setExportLoading(true);
    try {
      const userEmail = Cookies.get("email");
      const blob = await exportAgents(selectedAgentIds, userEmail);
      if (!blob) throw new Error('Failed to export agents');
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = 'agents_export.zip';
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      handleAddMessage("Agents exported successfully", "success");
      setSelectedAgentIds([]); // Clear selection after successful export
    } catch (err) {
      let errorMsg = err?.response?.data?.detail || err?.response?.data?.message || err?.message || 'Export failed!';
      handleAddMessage(errorMsg, "error");
    } finally {
      setExportLoading(false);
    }
  };
 
  return (
    <div className={styles.container}>
      {(loading || exportLoading) && <Loader />}
      <div className={styles.subHeaderContainer}>
        <SubHeader
          onSearch={(value) => handleSearch(value, calculateDivs(visibleAgentsContainerRef, 200, 128, 40), 1)}
          onSettingClick={onSettingClick}
          onPlusClick={onPlusClick}
          selectedTags={selectedTags}
          heading={"LIST OF AGENTS"}
          handleRefresh={handleRefresh}
          searchValue={searchTerm}
          clearSearch={clearSearch}
          showAgentTypeDropdown={true}
          agentTypes={agentTypesDropdown}
          selectedAgentType={selectedAgentType}
          handleAgentTypeChange={handleAgentTypeChange}
        />
        <button
          className={styles.exportSelectedBtn}
          onClick={handleExportSelected}
          disabled={selectedAgentIds.length === 0}
        >
          Export
        </button>
      </div>
 
        {/* Display searched tool text if searchTerm exists and results are found */}
        {searchTerm.trim() && visibleData.length > 0 && (
          <div className={styles.searchedToolText}>
            <p>Agents Found: {searchTerm}</p>
          </div>
        )}
 
        {/* Display filtered tools text if filters are applied */}
        {selectedTags.length > 0 && visibleData.length > 0 && (
          <div className={styles.filteredToolText}>
            <p>Agents Found: {selectedTags.join(", ")}</p>
          </div>
        )}
 
        {/* Display "No Agents Found" if no results are found after filtering */}
        {selectedTags.length > 0 && visibleData.length === 0 && (
          <div className={styles.searchedToolText}>
            <p>No Agents Found: {selectedTags.join(", ")}</p>
          </div>
        )}
 
        {/* Display "No Agents Found" if no results are found after searching */}
        {searchTerm.trim() && visibleData.length === 0 && (
          <div className={styles.filteredToolText}>
            <p>No Agents Found: {searchTerm}</p>
          </div>
        )}

        {/* Display "No Agents found" if no results are found after selecting agent type */}
        {selectedAgentType && !searchTerm.trim() && selectedTags.length === 0 && visibleData.length === 0 && (
          <div className={styles.filteredToolText}>
            <p>No Agents found</p>
          </div>
        )}
 
      <div
        className={styles.visibleAgentsContainer}
        ref={visibleAgentsContainerRef}
      >
        <div className={styles.agentsList}>
        {visibleData?.map((data) => (
          <AgentCard
            key={data?.agentic_application_id}
            styles={styles}
            data={data}
            onAgentEdit={onAgentEdit}
            deleteAgent={deleteAgent}
            fetchAgents={fetchAgents}
            isSelected={selectedAgentIds.includes(data.agentic_application_id)}
            onSelect={handleAgentSelect}
          />
        ))}
        </div>
      </div>
 
      {plusBtnClicked && (
        <div className={styles.agentOnboardContainer}>
          <AgentOnboard
            onClose={onOnboardClose}
            tags={tags}
            fetchAgents={fetchAgents}
            setNewAgentData={setEditAgentData}
            agentsListData={agentsListData?.filter(
              (agent) => agent?.agentic_application_type === REACT_AGENT
            )}
          />
        </div>
      )}
      {editAgentData && (
        <div className={styles.updateAgentContainer}>
          <UpdateAgent
            onClose={handleUpdateAgentClose}
            agentData={editAgentData}
            tags={tags}
            agentsListData={agentsListData?.filter(
              (agent) => agent?.agentic_application_type === REACT_AGENT
            )}
            fetchAgents={fetchAgents}
            searchTerm={searchTerm}
          />
        </div>
      )}
 
      <FilterModal
        show={filterModal}
        onClose={() => setFilterModal(false)}
        tags={tags}
        handleFilter={handleFilter}
        selectedTags={selectedTags}
      />
    </div>
  );
};
 
export default ListOfAgents;