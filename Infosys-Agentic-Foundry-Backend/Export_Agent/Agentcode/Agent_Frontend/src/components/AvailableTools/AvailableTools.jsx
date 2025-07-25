import React, { useEffect, useState, useCallback, useRef } from "react";
import ToolOnBoarding from "./ToolOnBoarding.jsx";
import style from "../../css_modules/AvailableTools.module.css";
import ToolsCard from "./ToolsCard.jsx";
import { getToolsSearchByPageLimit } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import { APIs } from "../../constant";
import useAxios from "../../Hooks/useAxios.js";
import FilterModal from "../commonComponents/FilterModal.jsx";
import SubHeader from "../commonComponents/SubHeader.jsx";
import { calculateDivs } from "../../util.js";
import { debounce } from "lodash";

const AvailableTools = () => {

  const [toolList, setToolList] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isAddTool, setIsAddTool] = useState(true);
  const [editTool, setEditTool] = useState({});
  const [loading, setLoading] = useState(false);
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [filterModal, setFilterModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [totalToolsCount, setTotalToolsCount] = useState(0);
  const toolListContainerRef = useRef(null);
  const { fetchData } = useAxios();
  const pageRef = useRef(1); 
  const [loader, setLoaderState] = useState(false);
  const isLoadingRef = React.useRef(false);

  const handleSearch = async (searchValue,divsCount,pageNumber) => {
    setSearchTerm(searchValue || "");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    if (searchValue.trim()) {
      try {
        setLoading(true);
        // Use the new API endpoint for search
        const response = await getToolsSearchByPageLimit({
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
      setVisibleData(toolList); // Reset to the initial list of tools
    }
  };


  const getToolsData = async (pageNumber, divsCount) => {
    setLoading(true);
    try {
      // Use the new API endpoint for paginated tools
      const response = await getToolsSearchByPageLimit({ page: pageNumber, limit: divsCount, search: "" });
      const data = response || [];
      if (pageNumber === 1) {
        setToolList(data);
        setVisibleData(data); // Ensure initial load is rendered
      } else {
        setVisibleData((prev) => [...prev, ...data]);
      }
      setTotalToolsCount(data?.length || 0);
    } catch (error) {
      console.error("Error fetching tools:", error);
    } finally {
      setLoading(false);
    }
  };

   const clearSearch = () => {
      setSearchTerm("");
      setVisibleData([]);
      // Trigger fetchToolsData with no search term (reset to first page)
      const divsCount= calculateDivs(toolListContainerRef, 200, 141, 40)
      setPage(1);
      pageRef.current = 1;
      getToolsData(1, divsCount);
   }

 

  useEffect(() => {
    const container = toolListContainerRef?.current;
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
  }, [toolListContainerRef]);

  const handleScrollLoadMore = async () => {
      if (loader || isLoadingRef.current) return; // Prevent multiple calls
      isLoadingRef.current = true;
      const nextPage = pageRef.current + 1;
      const divsCount= calculateDivs(toolListContainerRef, 200, 141, 40)
        try {
          setLoaderState(true);
          setLoading && setLoading(true);
          let newData = [];
          if (searchTerm.trim()) {
              const res = await getToolsSearchByPageLimit({
                page: nextPage,
                limit: divsCount,
                search: searchTerm,
              });
            newData = res || [];
            if (selectedTags?.length > 0) {
              newData = newData.filter(
                (item) =>
                  item.tags &&
                  item.tags.some((tag) => selectedTags.includes(tag?.tag_name))
              );
            }
            setVisibleData((prev) => [...prev, ...newData]);
          } else {
            // Only call fetchToolsData if no searchTerm
            await getToolsData(nextPage, divsCount);
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
          tags={tags}
          fetchPaginatedTools={fetchPaginatedTools}
        />
      )}
      {loading && <Loader />}
      <div className={style.container}>
        <div className={style.subHeaderContainer}>
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
              {visibleData?.map((item,index) => (
                  <ToolsCard
                    tool={item}
                    setShowForm={setShowForm}
                    setIsAddTool={setIsAddTool}
                    isAddTool={isAddTool}
                    //key={item.id}
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
      </div>
    </>
  );
};

export default AvailableTools;