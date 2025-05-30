import React, { useEffect, useState, useCallback, useRef } from "react";
import styles from "../../css_modules/ListOfAgents.module.css";
import AgentCard from "./AgentCard";
import { APIs, REACT_AGENT } from "../../constant";
import SubHeader from "../commonComponents/SubHeader";
import AgentOnboard from "../AgentOnboard";
import UpdateAgent from "./UpdateAgent.jsx";
import useAxios from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";
import FilterModal from "../commonComponents/FilterModal.jsx";
import { calculateDivs } from "../../util";
import { getAgentsByPageLimit } from "../../services/agentService.js";
import { debounce } from "lodash";

const ListOfAgents = () => {
  const [plusBtnClicked, setPlusBtnClicked] = useState(false);
  const [editAgentData, setEditAgentData] = useState(null);
  const [agentsListData, setAgentsListData] = useState([]);
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [searchTerm, setSearchTerm] = useState("");
  const [initialAgentsList, setInitialAgentsList] = useState([]);
  const [filterModal, setFilterModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const visibleAgentsContainerRef = useRef(null);
  const [totalAgentCount, setTotalAgentCount] = useState(0);
  const [loading, setLoading] = useState(false);
  const { addMessage, setShowPopup } = useMessage();
  const handleAddMessage = (message, type) => {
    addMessage(message, type);
  };

  const { fetchData, deleteData } = useAxios();
  const pageRef = useRef(1);
  const getTags = async () => {
    try {
      const data = await fetchData(APIs.GET_TAGS);
      setTags(data);
    } catch (e) {
      console.error(e);
    }
  };

  useEffect(() => {
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
      const response = await getAgentsByPageLimit({
        page: pageNumber,
        limit: divsCount,
      });
      const { details, total_count } = response;

      if (pageNumber === 1) {
        setInitialAgentsList(details); // Save the initial list of agents
      }

      setAgentsListData((prev) => [...prev, ...details]);
      setVisibleData((prev) => [...prev, ...details]);
      setTotalAgentCount(total_count);
    } catch (error) {
      console.error("Error fetching tools:", error);
    } finally {
      setLoading(false);
    }
  };

  const fetchAgents = async () => {
    try {
      if (hasLoadedOnce.current) return; // prevent duplicate initial load
      hasLoadedOnce.current = true;

      const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);

      pageRef.current = 1;
      setPage(1);

      getAgentsData(1, divsCount);
    } catch (e) {
      const errorMsg = e?.response?.data?.message || e?.message;
      handleAddMessage(errorMsg, "error");
      console.error("Fetch Agents Error:", errorMsg);
    }
  };

  const deleteAgent = async (id, email) => {
    try {
      await deleteData(APIs.DELETE_AGENT + id, {
        user_email_id: email,
        is_admin: false,
      });
      handleAddMessage("AGENT HAS BEEN DELETED SUCCESSFULLY !", "success");
      return true;
    } catch (error) {
      const errorMsg = error?.response?.data?.message || error?.message;
      handleAddMessage(errorMsg, "error");
      console.error("Delete Agent Error:", errorMsg);
      return false;
    }
  };


  const onSearch = async (searchValue) => {
    setSearchTerm(searchValue || ""); // Update the search term state
  
    if (searchValue.trim()) {
      try {
        setLoading(true); // Show loader while fetching data
  
        // Fetch data from the API based on the search term
        const response = await fetchData(`${APIs.GET_AGENTS_BY_SEARCH}/${searchValue}`);
        let dataToSearch = response;
  
        // Filter by selected tags if applicable
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
      setVisibleData(initialAgentsList);
    }
  };
  
  const clearSearch = () => {
    setSearchTerm("");
    setVisibleData(initialAgentsList);
  };

  const hasLoadedOnce = useRef(false);

  const loadMoreData = useCallback(() => {
    if (loading || agentsListData.length >= totalAgentCount) return; // prevent overfetching

    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    pageRef.current = nextPage;
    setPage(nextPage);
    getAgentsData(nextPage, divsCount);
  }, [page, agentsListData, selectedTags, loading]);

  useEffect(() => {
    const debouncedCheckAndLoad = debounce(() => {
      if (!searchTerm.trim() && selectedTags.length === 0) {
        const container = visibleAgentsContainerRef.current;
        if (
          container &&
          container.scrollHeight <= container.clientHeight &&
          agentsListData.length < totalAgentCount
        ) {
          loadMoreData();
        }
      }
    }, 300);

    const handleResize = () => {
      debouncedCheckAndLoad();
    };
  
    window.addEventListener('resize', handleResize);
    debouncedCheckAndLoad();
    return () => {
      window.removeEventListener('resize', handleResize);
      debouncedCheckAndLoad.cancel && debouncedCheckAndLoad.cancel();
    };
  }, [agentsListData.length, totalAgentCount, searchTerm, selectedTags]);

  function handleScroll() {
    const container = visibleAgentsContainerRef.current;
    if (
      container.scrollHeight - container.scrollTop <=
      container.clientHeight + 40
    ) {
      if (!searchTerm.trim()) {
        loadMoreData();
      }
    }
  }

  useEffect(() => {
    fetchAgents();
  }, []);

  const handleRefresh = () => {
    setPage(1);
    pageRef.current = 1;
    clearSearch();
    setSelectedTags([]);
    setVisibleData([]);
    const divsCount = calculateDivs(visibleAgentsContainerRef, 200, 128, 40);
    getAgentsData(1, divsCount);
  };

  useEffect(() => {
    // Add scroll event listener to the scrollable div
    const container = visibleAgentsContainerRef.current;
    container.addEventListener("scroll", handleScroll);
    if (searchTerm.length > 0 || selectedTags.length > 0) {
      container.style.maxHeight = "100%";
      container.style.height = "auto";
    }
    return () => container.removeEventListener("scroll", handleScroll);
  }, [agentsListData, page, searchTerm, selectedTags]);

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
      const filteredData = agentsListData.filter(
        (item) =>
          item.tags &&
          item.tags.some((tag) => selectedTags.includes(tag.tag_name))
      );
      setVisibleData(filteredData);
    } else {
      setVisibleData(initialAgentsList);
    }
  };

  return (
    <div className={styles.container}>
      {loading && <Loader />}
      <div className={styles.subHeaderContainer}>
        <SubHeader
          onSearch={onSearch}
          onSettingClick={onSettingClick}
          onPlusClick={onPlusClick}
          selectedTags={selectedTags}
          heading={"LIST OF AGENTS"}
          handleRefresh={handleRefresh}
          searchValue={searchTerm}
          clearSearch={clearSearch}
        />
      </div>

        {/* Display searched tool text if searchTerm exists and results are found */}
        {searchTerm.trim() && visibleData.length > 0 && (
          <div className={styles.searchedToolText}>
            <p>Tools Found: {searchTerm}</p>
          </div>
        )}

        {/* Display filtered tools text if filters are applied */}
        {selectedTags.length > 0 && visibleData.length > 0 && (
          <div className={styles.filteredToolText}>
            <p>Tools Found: {selectedTags.join(", ")}</p>
          </div>
        )}

        {/* Display "No Tools Found" if no results are found after filtering */}
        {selectedTags.length > 0 && visibleData.length === 0 && (
          <div className={styles.searchedToolText}>
            <p>No Tools Found: {selectedTags.join(", ")}</p>
          </div>
        )}

        {/* Display "No Tools Found" if no results are found after searching */}
        {searchTerm.trim() && visibleData.length === 0 && (
          <div className={styles.filteredToolText}>
            <p>No Tools Found: {searchTerm}</p>
          </div>
        )}

      <div
        className={styles.visibleAgentsContainer}
        ref={visibleAgentsContainerRef}
      >
        <div className={styles.agentsList}>
        {visibleData?.map((data) => (
          <AgentCard
            key={data?.id}
            styles={styles}
            data={data}
            onAgentEdit={onAgentEdit}
            deleteAgent={deleteAgent}
            fetchAgents={fetchAgents}
          />
        ))}
        </div>
      </div>

      {/* )} */}
      {plusBtnClicked && (
        <div className={styles.agentOnboardContainer}>
          <AgentOnboard
            onClose={onOnboardClose}
            tags={tags}
            fetchAgents={fetchAgents}
            setNewAgentData={setEditAgentData}
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
