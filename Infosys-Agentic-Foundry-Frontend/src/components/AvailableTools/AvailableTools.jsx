import React, { useEffect, useState, useCallback, useRef } from "react";
import ToolOnBoarding from "./ToolOnBoarding.jsx";
import style from "../../css_modules/AvailableTools.module.css";
import ToolsCard from "./ToolsCard.jsx";
import AvailableServers from "./AvailableServers.jsx";
import { useToolsAgentsService } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios.js";
import FilterModal from "../commonComponents/FilterModal.jsx";
import SubHeader from "../commonComponents/SubHeader.jsx";
import { debounce } from "lodash";
import { useActiveNavClick } from "../../events/navigationEvents";

const AvailableTools = () => {
  const [toolList, setToolList] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isAddTool, setIsAddTool] = useState(true);
  const [editTool, setEditTool] = useState({});
  const [loading, setLoading] = useState(false);
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [activeTab, setActiveTab] = useState("tools");
  const [filterModal, setFilterModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [totalToolsCount, setTotalToolsCount] = useState(0);
  const [hasMore, setHasMore] = useState(true); // track if more pages are available
  const toolListContainerRef = useRef(null);
  const { fetchData } = useFetch();
  const pageRef = useRef(1);
  const [loader, setLoaderState] = useState(false);
  const isLoadingRef = React.useRef(false);
  const { getToolsSearchByPageLimit, calculateDivs } = useToolsAgentsService();

  // Normalize API responses to always return a clean array of tool objects
  const sanitizeToolsResponse = (response) => {
    if (!response) return [];
    // If backend sometimes returns an object instead of array
    if (!Array.isArray(response)) return [];
    // If array contains a single message object with no tool fields, treat as empty
    if (response.length === 1 && response[0] && typeof response[0] === "object" && "message" in response[0] && !("tool_id" in response[0])) {
      return [];
    }
    return response.filter((item) => item && typeof item === "object" && ("tool_id" in item || "tool_name" in item));
  };

  const handleSearch = async (searchValue, divsCount, pageNumber, tagsToUse = null) => {
    setSearchTerm(searchValue || "");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    if (searchValue.trim()) {
      try {
        setLoading(true);
        // Use the new API endpoint for search with tag filtering
        // Use provided tagsToUse or fall back to selectedTags state
        const tagsForSearch = tagsToUse !== null ? tagsToUse : selectedTags;
        const response = await getToolsSearchByPageLimit({
          page: pageNumber,
          limit: divsCount,
          search: searchValue,
          tags: tagsForSearch?.length > 0 ? tagsForSearch : undefined,
        });
        let dataToSearch = sanitizeToolsResponse(response.details);

        // Setting the total count
        setTotalToolsCount(response.total_count || 0);

        // Update visibleData with the API filtered data (no client-side filtering needed)
        setVisibleData(dataToSearch);
        // If returned less than requested, no more pages
        setHasMore(dataToSearch.length >= divsCount);
      } catch (error) {
        console.error("Error fetching search results:", error);
        setVisibleData([]); // Clear visibleData on error
        setHasMore(false);
      } finally {
        setLoading(false); // Hide loader
      }
    } else {
      // If search term is empty, reset to default data
      setVisibleData(toolList); // Reset to the initial list of tools
      setHasMore(true);
    }
  };

  const getToolsData = async (pageNumber, divsCount) => {
    return getToolsDataWithTags(pageNumber, divsCount, selectedTags);
  };

  const getToolsDataWithTags = async (pageNumber, divsCount, tagsToUse) => {
    setLoading(true);
    try {
      // Use the new API endpoint for paginated tools with tag filtering
      const response = await getToolsSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: "",
        tags: tagsToUse?.length > 0 ? tagsToUse : undefined,
      });
      const data = sanitizeToolsResponse(response.details);
      if (pageNumber === 1) {
        setToolList(data);
        setVisibleData(data); // Ensure initial load is rendered
      } else {
        if (data.length > 0) {
          setVisibleData((prev) => (Array.isArray(prev) ? [...prev, ...data] : [...data]));
        }
      }
      // Use total_count from response if available, otherwise use current data length
      setTotalToolsCount(response.total_count || data?.length || 0);
      // If fewer items than requested were returned, we've reached the end
      if (data.length < divsCount) {
        setHasMore(false);
      } else if (pageNumber === 1) {
        // Reset hasMore on fresh load only when page is full
        setHasMore(true);
      }
      return data; // return fetched data for caller decisions
    } catch (error) {
      console.error("Error fetching tools:", error);
      if (pageNumber === 1) {
        setToolList([]);
        setVisibleData([]);
      }
      setHasMore(false);
      return [];
    } finally {
      setLoading(false);
    }
  };

  const clearSearch = () => {
    setSearchTerm("");
    setSelectedTags([]); // Clear tags when clearing search
    setVisibleData([]);
    setHasMore(true);
    // Trigger fetchToolsData with no search term and no tags (reset to first page)
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    setPage(1);
    pageRef.current = 1;
    // Call getToolsData with explicitly empty tags
    getToolsDataWithTags(1, divsCount, []);
  };

  useEffect(() => {
    const container = toolListContainerRef?.current;
    if (!container) return;

    // Extract the check logic into a separate function
    const checkAndLoadMore = () => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 10 &&
        !loading &&
        !isLoadingRef.current &&
        hasMore // Prevent if no more pages
      ) {
        handleScrollLoadMore();
      }
    };

    const debouncedCheckAndLoad = debounce(checkAndLoadMore, 200); // 200ms debounce

    const handleResize = () => {
      debouncedCheckAndLoad();
    };

    window.addEventListener("resize", handleResize);
    container.addEventListener("scroll", debouncedCheckAndLoad);

    return () => {
      window.removeEventListener("resize", handleResize);
      debouncedCheckAndLoad.cancel && debouncedCheckAndLoad.cancel();
      container.removeEventListener("scroll", debouncedCheckAndLoad);
    };
  }, [toolListContainerRef, hasMore, loading]);

  const handleScrollLoadMore = async () => {
    if (loader || isLoadingRef.current || !hasMore) return; // Prevent multiple calls or if no more data
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    try {
      setLoaderState(true);
      setLoading && setLoading(true);
      let newData = [];
      if (searchTerm.trim()) {
        const res = await getToolsSearchByPageLimit({
          page: nextPage,
          limit: divsCount,
          search: searchTerm,
          tags: selectedTags?.length > 0 ? selectedTags : undefined,
        });
        newData = sanitizeToolsResponse(res.details);
        if (newData.length > 0) {
          setVisibleData((prev) => (Array.isArray(prev) ? [...prev, ...newData] : [...newData]));
          // Only increment page if we actually appended data
          setPage(nextPage);
          pageRef.current = nextPage;
        }
        if (newData.length < divsCount) setHasMore(false);
      } else {
        // Only call fetchToolsData if no searchTerm; capture returned data
        const appended = await getToolsData(nextPage, divsCount);
        if (appended.length > 0) {
          setPage(nextPage);
          pageRef.current = nextPage;
        }
      }
    } catch (err) {
      console.error(err);
      setHasMore(false);
    } finally {
      setLoaderState(false);
      setLoading && setLoading(false);
      isLoadingRef.current = false;
    }
  };

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

  // Use a ref to ensure tags are fetched only once
  const hasLoadedTagsOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedTagsOnce.current) return;
    hasLoadedTagsOnce.current = true;
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

  const handleRefresh = () => {
    setPage(1);
    pageRef.current = 1;
    setSearchTerm("");
    setSelectedTags([]);
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    // Call getToolsData with explicitly empty tags
    getToolsDataWithTags(1, divsCount, []);
  };
  const handleFilter = async (selectedTagsParam) => {
    setSelectedTags(selectedTagsParam);
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    // Close modal if tags are cleared
    if (!selectedTagsParam || selectedTagsParam.length === 0) {
      setFilterModal(false);
    }

    // Trigger new API call with selected tags - pass selectedTagsParam directly
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    if (searchTerm.trim()) {
      // If there's a search term, use handleSearch with current search and new tags
      await handleSearch(searchTerm, divsCount, 1, selectedTagsParam);
    } else {
      // If no search term, fetch data with tag filter - pass selectedTagsParam directly
      await getToolsDataWithTags(1, divsCount, selectedTagsParam);
    }
  };

  const fetchPaginatedTools = async (pageNumber = 1) => {
    setVisibleData([]);
    setPage(pageNumber);
    pageRef.current = pageNumber;
    setHasMore(true);
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    await getToolsData(pageNumber, divsCount);
  };

  useActiveNavClick(["/", "/tools"], () => {
    setShowForm((open) => (open ? false : open));
  });

  return (
    <>
      <FilterModal
        show={filterModal}
        onClose={() => setFilterModal(false)}
        tags={tags}
        handleFilter={handleFilter}
        selectedTags={selectedTags}
        showfilterHeader={"Filter tools by Tags"}
      />
      {showForm && (
        <ToolOnBoarding
          setShowForm={setShowForm}
          isAddTool={isAddTool}
          editTool={editTool}
          setIsAddTool={setIsAddTool}
          tags={tags}
          fetchPaginatedTools={fetchPaginatedTools}
          hideServerTab={true}
          contextType="tools"
        />
      )}
      {loading && <Loader />}
      <div className={style.container}>
        <div style={{ display: "flex", justifyContent: "flex-start", marginBottom: 12, flexDirection: "column", alignItems: "baseline", gap: "4px" }}>
          <div style={{ display: "flex", gap: 0 }}>
            <button onClick={() => setActiveTab("tools")} className={`iafTabsBtn ${activeTab === "tools" ? " active" : ""}`}>
              TOOLS
            </button>
            <button onClick={() => setActiveTab("servers")} className={`iafTabsBtn ${activeTab === "servers" ? " active" : ""}`}>
              SERVERS
            </button>
          </div>
          {/* SubHeader sits on its own row below the tabs (only when tools tab is active) */}
          {activeTab === "tools" && (
            <div style={{ marginBottom: "-2px", width: "98%" }} className={style.subHeaderContainer}>
              <SubHeader
                heading={"LIST OF TOOLS"}
                onSearch={(value) => handleSearch(value, calculateDivs(toolListContainerRef, 200, 141, 40), 1)}
                onSettingClick={onSettingClick}
                onPlusClick={handlePlusIconClick}
                handleRefresh={handleRefresh}
                selectedTags={selectedTags}
                clearSearch={clearSearch}
              />
            </div>
          )}
          {activeTab === "servers" ? (
            <AvailableServers />
          ) : (
            <>
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
              {/* Display "No Tools Found" messages when search or filters applied but no results */}
              {searchTerm.trim() && visibleData.length === 0 && (
                <div className={style.filteredToolText}>
                  <p>No Tools Found: {searchTerm}</p>
                </div>
              )}
              {selectedTags.length > 0 && visibleData.length === 0 && (
                <div className={style.searchedToolText}>
                  <p>No Tools Found: {selectedTags.join(", ")}</p>
                </div>
              )}
              {/* Display total count summary */}
              {visibleData.length > 0 && (
                <div className={style.summaryLine}>
                  <strong>{visibleData.length}</strong> tools (of {totalToolsCount} total)
                </div>
              )}
              <div className={style.visibleToolsContainer} ref={toolListContainerRef}>
                {visibleData?.length > 0 && (
                  <div className={style.toolsList}>
                    {visibleData?.map((item, index) => (
                      <ToolsCard
                        tool={item}
                        setShowForm={setShowForm}
                        setIsAddTool={setIsAddTool}
                        isAddTool={isAddTool}
                        key={`tools-card-${index}`}
                        style={style}
                        setEditTool={setEditTool}
                        loading={loading}
                        fetchPaginatedTools={fetchPaginatedTools}
                      />
                    ))}
                  </div>
                )}
              </div>
            </>
          )}
        </div>
      </div>
    </>
  );
};

export default AvailableTools;
