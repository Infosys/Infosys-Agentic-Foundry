import React, { useState, useEffect } from "react";
import SVGIcons from "../../../Icons/SVGIcons";
import Toggle from "../../commonComponents/Toggle";
import { META_AGENT, MULTI_AGENT, PLANNER_META_AGENT, REACT_AGENT,REACT_CRITIC_AGENT,PLANNER_EXECUTOR_AGENT } from "../../../constant";
import ToolCard from "./ToolCard";
import SearchInput from "../../commonComponents/SearchInputTools";
import style from "./AddTools.module.css";
import AddToolsFilterModal from "./AddToolsFilter";
import { calculateDivs } from "../../../util";
import {getAgentsSearchByPageLimit,getToolsSearchByPageLimit } from "../../../services/toolService";
import { debounce } from "lodash";
import Loader from "../../commonComponents/Loader";

const AddTools = (props) => {
  const {
    styles,
    addOrRemoveTool,
    selectedTools,
    remainingTools,
    addedToolsId,
    setAddedToolsId,
    removedToolsId,
    setremovedToolsId,
    selectedAgents,
    remainingAgents,
    agentType,
    setAddedAgentsId,
    addedAgentsId,
    removedAgentsId,
    setRemovedAgentsId,
    tags,
    setSelectedTags,
    setToggleSelected,
    toggleSelected,
    selectedTags,
    agentData,
    tagsList,
    setShowForm,
    setEditTool,
    toolListContainerRef,
    fetchToolsData,
    setVisibleData,
    setLoader,
    pageRef,
    setPage,
    visibleData
  } = props;

  const [searchTerm, setSearchTerm] = useState("");
  const [filterModalOpen, setFilterModalOpen] = useState(false);
  const [loader, setLoaderState] = useState(false);
  const isLoadingRef = React.useRef(false);

  useEffect(() => {
    if (agentData?.tags) {
      const defaultTags = agentData.tags.map((tag) => tag.tag_id);
      setSelectedTags(defaultTags);
    }
  }, [agentData]);

  const onChange = (e) => {
    setToggleSelected(e.target.checked);
    setSearchTerm("");
    setVisibleData([]);
    setPage(1);
    pageRef.current = 1;
  };
 
  useEffect(() => {
    if (toggleSelected) return; // Don't attach scroll for mapped list
    const container = toolListContainerRef?.current;
    if (!container) return;
    const debouncedHandleScroll = debounce(() => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 10 &&
        !loader && !isLoadingRef.current // Prevent if already loading
      ) {
        handleScrollLoadMore();
      }
    }, 200); // 200ms debounce
    container.addEventListener('scroll', debouncedHandleScroll);
    return () => container.removeEventListener('scroll', debouncedHandleScroll);
  }, [toolListContainerRef, toggleSelected, loader]);
 
  const handleSearch = async (searchValue, divsCount, pageNumber) => {
    setSearchTerm(searchValue);
    setPage(1);
    pageRef.current = 1;
    if (toggleSelected) {
      setVisibleData([]);
      return;
    }
    if (searchValue?.trim()) {
      setVisibleData([]);
      try {
        setLoaderState(true);
        setLoader && setLoader(true);
        let data = [];
        if ((agentType === META_AGENT || agentType === PLANNER_META_AGENT)) {
          const res = await getAgentsSearchByPageLimit({
            page: pageNumber,
            limit: divsCount,
            search: searchValue,
          });
          data = res?.filter(
            (a) =>
              (a.agentic_application_type === REACT_AGENT ||
                a.agentic_application_type === MULTI_AGENT || 
                a.agentic_application_type === REACT_CRITIC_AGENT ||
                a.agentic_application_type === PLANNER_EXECUTOR_AGENT) &&
              !selectedAgents.some(
                (mapped) => mapped.agentic_application_id === a.agentic_application_id
              )
          ) || [];
        } else {
          const res = await getToolsSearchByPageLimit({
            page: pageNumber,
            limit: divsCount,
            search: searchValue,
          });
          data = res.filter(
            (tool) => !selectedTools.some((mapped) => mapped.tool_id === tool.tool_id)
          );
        }
        setVisibleData(data);
      } catch (err) {
        console.error(err);
        setVisibleData([]);
      } finally {
        setLoaderState(false);
        setLoader && setLoader(false);
      }
    } else {
      const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
      setVisibleData([]);
      fetchToolsData(1, divsCount);
    }
  };


  const clearSearch = () => {
    setSearchTerm("");
    setVisibleData([]);
    // Trigger fetchToolsData with no search term (reset to first page)
    const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
    setPage(1);
    pageRef.current = 1;
    fetchToolsData(1, divsCount);
  };

  const handleFilter = (selectedTags) => {
    setSelectedTags(selectedTags); // Update selected tags
  };

  const isMetaAgent = (agentType === META_AGENT || agentType===PLANNER_META_AGENT);

  const displayData = searchTerm.trim() ? (visibleData || []) : (
    toggleSelected
      ? isMetaAgent
        ? selectedAgents
        : selectedTools
      : isMetaAgent
      ? remainingAgents
      : remainingTools
  ) ?.filter((item) => {
    return isMetaAgent
      ? item.agentic_application_name
          ?.toLowerCase()
          .includes(searchTerm?.toLowerCase())
      : item.tool_name?.toLowerCase()?.includes(searchTerm?.toLowerCase())
  }) || [];
 
  const handleScrollLoadMore = async () => {
    if (loader || isLoadingRef.current) return; // Prevent multiple calls
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(toolListContainerRef, 231, 70, 26);
    if (!toggleSelected) {
      try {
        setLoaderState(true);
        setLoader && setLoader(true);
        let newData = [];
        if (searchTerm?.trim()) {
          // Only call search API if searchTerm is present
          if (agentType === META_AGENT || agentType === PLANNER_META_AGENT) {
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
                  a.agentic_application_type === PLANNER_EXECUTOR_AGENT) &&
                !selectedAgents.some(
                  (mapped) => mapped.agentic_application_id === a.agentic_application_id
                )
            );
          } else {
            const res = await getToolsSearchByPageLimit({
              page: nextPage,
              limit: divsCount,
              search: searchTerm,
            });
            newData = (res || []).filter(
              (tool) => !selectedTools.some((mapped) => mapped.tool_id === tool.tool_id)
            );
          }
          setVisibleData((prev) => [...prev, ...newData]);
        } else {
          // Only call fetchToolsData if no searchTerm
          await fetchToolsData(nextPage, divsCount);
        }
        setPage(nextPage);
        pageRef.current = nextPage;
      } catch (err) {
        console.error(err);
      } finally {
        setLoaderState(false);
        setLoader && setLoader(false);
        isLoadingRef.current = false;
      }
    } else {
      isLoadingRef.current = false;
    }
  };
 
  return (
    <>
    {props?.recycleBin ?
      <>
      <div className={styles.addToolContainer}>
          <div className={`${displayData?.length >0 ?styles.toolsContainer:""} ${props?.recycleBin ? styles.disabledButton: ""}`} style={{ maxHeight: 'none', overflow: 'visible' }} >
            {displayData.map((tool) => (
          <ToolCard
            key={tool.id || tool.tool_id || tool.agentic_application_id}
            tool={tool}
            styles={styles}
            isMappedTool={toggleSelected}
            addOrRemoveTool={addOrRemoveTool}
            addedToolsId={addedToolsId}
            addedAgentsId={addedAgentsId}
            setAddedToolsId={setAddedToolsId}
            setAddedAgentsId={setAddedAgentsId}
            removedToolsId={removedToolsId}
            removedAgentsId={removedAgentsId}
            setremovedToolsId={setremovedToolsId}
            setRemovedAgentsId={setRemovedAgentsId}
            agentType={agentType}
            tagsList={tagsList}
            setShowForm={setShowForm}
            setEditTool={setEditTool}
          />
        ))}
          </div>
          </div>

      </>:<>
       <div className={styles.addToolContainer}>
      <div className={styles.addTools} data-selected={toggleSelected}>
        <div className={style.topSection}>
          <p className={styles.addNewTool}>
            <SVGIcons icon="fa-plus" width={12} height={12} fill="#007AC0" />
            {isMetaAgent ? "ADD NEW AGENT" : "ADD NEW TOOL"}
          </p>
          <Toggle onChange={onChange} value={toggleSelected} />
          <p className={styles.removeTool}>
            <SVGIcons icon="fa-xmark" fill="#a1a1a1" width={12} height={16} />{" "}
            {isMetaAgent ? "REMOVE MAPPED AGENT" : "REMOVE MAPPED TOOL"}
          </p>
        </div>
        {/* Search bar */}
        {!toggleSelected && (
          <>
            <div className={styles.searchBar}>
              <SearchInput
                key={toggleSelected}
                inputProps={{
                  placeholder: `Search ${isMetaAgent ? "Agents" : "Tools"}`,
                }}
                handleSearch={(value) => handleSearch(value, calculateDivs(toolListContainerRef, 231, 70, 26), 1)}
                clearSearch={clearSearch}
              />
            </div>
            <div className={style.filterContainer}>
              <button
                className={style.filterButton}
                onClick={(e) => {
                  e.preventDefault();
                  setFilterModalOpen(true);
                }}
              >
                <SVGIcons
                  icon="fa-filter"
                  fill="#007AC0"
                  width={16}
                  height={16}
                  style={{ marginRight: "5px" }}
                />
                Tags
                {displayData.length > 0 && (
                  <span className={style.filterBadge}>{selectedTags.length}</span>
                )}
              </button>
            </div>
          </>
        )}
      </div>
      {searchTerm.trim() && !loader && visibleData.length === 0 ? (
        <div className={styles.noResultsFound}>
          <p>No results found.</p>
        </div>
      ) : (
      <div className={styles.toolsContainer} ref={toolListContainerRef}>
        {displayData.map((tool) => (
          <ToolCard
            key={tool.id || tool.tool_id || tool.agentic_application_id}
            tool={tool}
            styles={styles}
            isMappedTool={toggleSelected}
            addOrRemoveTool={addOrRemoveTool}
            addedToolsId={addedToolsId}
            addedAgentsId={addedAgentsId}
            setAddedToolsId={setAddedToolsId}
            setAddedAgentsId={setAddedAgentsId}
            removedToolsId={removedToolsId}
            removedAgentsId={removedAgentsId}
            setremovedToolsId={setremovedToolsId}
            setRemovedAgentsId={setRemovedAgentsId}
            agentType={agentType}
            tagsList={tagsList}
            setShowForm={setShowForm}
            setEditTool={setEditTool}
          />
        ))}
      </div>
      )}
      {!toggleSelected && (
        <AddToolsFilterModal
          show={filterModalOpen}
          onClose={() => setFilterModalOpen(false)}
          tags={tags}
          handleFilter={handleFilter}
          selectedTags={selectedTags}
        />
      )}
    </div>
      
      </>}
      </>
   
  );
};

export default AddTools;

