import React, { useEffect, useState, useCallback, useRef } from "react";
import ToolOnBoarding from "./ToolOnBoarding.jsx";
import style from "../../css_modules/AvailableTools.module.css";
import ToolsCard from "./ToolsCard.jsx";
import { getToolsByPageLimit } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import { APIs } from "../../constant";
import useAxios from "../../Hooks/useAxios.js";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal.jsx";
import { useNavigate } from "react-router-dom";
import FilterModal from "../commonComponents/FilterModal.jsx";
import SubHeader from "../commonComponents/SubHeader.jsx";
import { calculateDivs } from "../../util.js";
import { debounce } from "lodash";

const AvailableTools = () => {
  const userName = Cookies.get("userName");

  const [toolList, setToolList] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isAddTool, setIsAddTool] = useState(true);
  const [editTool, setEditTool] = useState({});
  const [loading, setLoading] = useState(false);
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [addModal, setAddModal] = useState(false);
  const [filterModal, setFilterModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [totalToolsCount, setTotalToolsCount] = useState(0);
  const toolListContainerRef = useRef(null);
  const { fetchData } = useAxios();
  const pageRef = useRef(1); 

  const handleSearch = async (searchValue) => {
    setSearchTerm(searchValue || ""); // Update the search term state

    if (searchValue.trim()) {
      try {
        setLoading(true); // Show loader while fetching data

        // Fetch data from the API based on the search term
        const response = await fetchData(`${APIs.GET_TOOLS_BY_SEARCH}/${searchValue}`);

        let dataToSearch = response

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
      setVisibleData(toolList); // Reset to the initial list of tools
    }
  };

  const clearSearch = () => {
    setSearchTerm(""); // Clear the search term
    setVisibleData(toolList); // Reset to the initial list of tools
  };

  const getToolsData = async (pageNumber, divsCount) => {
    setLoading(true);
    try {
      const response = await getToolsByPageLimit({ page: pageNumber, limit: divsCount }); // API call with params
      const { details, total_count } = response;

      if (pageNumber === 1) {
        setToolList(details); // Save the initial list of tools
      }

      setVisibleData((prev) => [...prev, ...details]);
      setTotalToolsCount(total_count);
    } catch (error) {
      console.error("Error fetching tools:", error);
    } finally {
      setLoading(false);
    }
  };

  const loadMoreData = useCallback(() => {
    if (loading || toolList.length >= totalToolsCount) return; // prevent overfetching
  
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    pageRef.current = nextPage; // immediately update ref
    setPage(nextPage);
    getToolsData(nextPage, divsCount);
  }, [toolList, totalToolsCount, loading]);

  useEffect(() => {
      const debouncedCheckAndLoad = debounce(() => {
        if (!searchTerm.trim() && selectedTags.length === 0) {
          const container = toolListContainerRef.current;
          if (
            container &&
            container.scrollHeight <= container.clientHeight &&
            toolList.length < totalToolsCount
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
    }, [toolList.length, totalToolsCount, searchTerm, selectedTags]);

  function handleScroll() {
    const container = toolListContainerRef.current;
    if (
      container.scrollHeight - container.scrollTop <=
      container.clientHeight + 140
    ) {
      if (!searchTerm.trim()) {
        loadMoreData();
      }
    }
  }

  useEffect(() => {
    const container = toolListContainerRef.current;
    container?.addEventListener("scroll", handleScroll);
    if (searchTerm.length > 0 || selectedTags.length > 0) {
      container.style.maxHeight = "100%";
      container.style.height = "auto";
    }
    return () => container.removeEventListener("scroll", handleScroll);
  }, [loadMoreData, searchTerm, selectedTags]);

  const handlePlusIconClick = () => {
    setShowForm(true);
    setIsAddTool(true);
  };

  const onSettingClick = () => {
    setFilterModal(true);
  };

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
  }, [showForm]);

  const hasLoadedOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedOnce.current) return; // prevent duplicate initial load
    hasLoadedOnce.current = true;

    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    pageRef.current = 1;
    setPage(1);
    getToolsData(1, divsCount);
  }, []);

  const navigate = useNavigate();

  const handleLoginButton = (e) => {
    e.preventDefault();
    Cookies.remove("userName");
    Cookies.remove("session_id");
    Cookies.remove("csrf-token");
    Cookies.remove("email");
    Cookies.remove("role");
    navigate("/login");
  };

  const handleRefresh = () => {
      setPage(1);
      pageRef.current = 1;
      clearSearch();
      setSelectedTags([]);
      setVisibleData([]);
      const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
      getToolsData(1, divsCount);
    };
  const handleFilter = (selectedTags) => {
    setSelectedTags(selectedTags);

    if (selectedTags?.length > 0) {
      const filteredData = toolList.filter(
        (item) =>
          item.tags &&
          item.tags.some((tag) => selectedTags.includes(tag.tag_name))
      );
      setVisibleData(filteredData);
    } else {
      setVisibleData(toolList); // Reset to the full list of tools
    }
  };

  const fetchPaginatedTools = async (pageNumber = 1) => {
    setVisibleData([]);
    setPage(pageNumber);
    pageRef.current = pageNumber;
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    await getToolsData(pageNumber, divsCount);
  };
  

  return (
    <>
      <DeleteModal show={addModal} onClose={() => setAddModal(false)}>
        <p>
          You are not authorized to add a tool. Please login with registered
          email.
        </p>
        <button onClick={(e) => handleLoginButton(e)}>Login</button>
      </DeleteModal>

      <FilterModal
        show={filterModal}
        onClose={() => setFilterModal(false)}
        tags={tags}
        handleFilter={handleFilter}
        selectedTags={selectedTags}
      />

      {showForm && (
        <ToolOnBoarding
          setShowForm={setShowForm}
          isAddTool={isAddTool}
          editTool={editTool}
          setIsAddTool={setIsAddTool}
          setToolList={setToolList}
          tags={tags}
          setVisibleData={setVisibleData}
          fetchPaginatedTools={fetchPaginatedTools}
        />
      )}
      {loading && <Loader />}
      <div className={style.container}>
        <div className={style.subHeaderContainer}>
          <SubHeader
            heading={"LIST OF TOOLS"}
            onSearch={handleSearch}
            onSettingClick={onSettingClick}
            onPlusClick={handlePlusIconClick}
            handleRefresh={handleRefresh}
            selectedTags={selectedTags}
            clearSearch={clearSearch}
          />
        </div>

        {/* Display searched tool text if searchTerm exists and results are found */}
        {searchTerm.trim() && visibleData.length > 0 && (
          <div className={style.searchedToolText}>
            <p>Tools Found: {searchTerm}</p>
          </div>
        )}

        {/* Display filtered tools text if filters are applied */}
        {selectedTags.length > 0 && visibleData.length > 0 && (
          <div className={style.filteredToolText}>
            <p>Tools Found: {selectedTags.join(", ")}</p>
          </div>
        )}

        {/* Display "No Tools Found" if no results are found after filtering */}
        {selectedTags.length > 0 && visibleData.length === 0 && (
          <div className={style.searchedToolText}>
            <p>No Tools Found: {selectedTags.join(", ")}</p>
          </div>
        )}

        {/* Display "No Tools Found" if no results are found after searching */}
        {searchTerm.trim() && visibleData.length === 0 && (
          <div className={style.filteredToolText}>
            <p>No Tools Found: {searchTerm}</p>
          </div>
        )}

        <div className={style.visibleToolsContainer} ref={toolListContainerRef}>
          {visibleData?.length > 0 && (
            <div className={style.toolsList}>
              {visibleData?.map((item) => (
                  <ToolsCard
                    tool={item}
                    setShowForm={setShowForm}
                    setIsAddTool={setIsAddTool}
                    isAddTool={isAddTool}
                    key={item.id}
                    style={style}
                    setEditTool={setEditTool}
                    setToolList={setToolList}
                    loading={loading}
                    setLoading={setLoading}
                    setVisibleData={setVisibleData}
                    fetchPaginatedTools={fetchPaginatedTools}
                  />
                ))}
            </div>
          )}
        </div>
      </div>
    </>
  );
};

export default AvailableTools;