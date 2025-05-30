import React, { useState, useEffect } from "react";
import SVGIcons from "../../../Icons/SVGIcons";
import Toggle from "../../commonComponents/Toggle";
import { META_AGENT } from "../../../constant";
import ToolCard from "./ToolCard";
import Dropdown from "../../Dropdown/Dropdown";
import SearchInput from "../../commonComponents/SearchInput";
import style from "./AddTools.module.css";
import AddToolsFilterModal from "./AddToolsFilter";

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
    toolListContainerRef
  } = props;

  const [searchTerm, setSearchTerm] = useState("");
  const [filterModalOpen, setFilterModalOpen] = useState(false);

  useEffect(() => {
    if (agentData?.tags) {
      const defaultTags = agentData.tags.map((tag) => tag.tag_id);
      setSelectedTags(defaultTags);
    }
  }, [agentData]);

  const onChange = (e) => {
    setToggleSelected(e.target.checked);
  };

  const handleSearch = (searchValue) => {
    setSearchTerm(searchValue); // Update search term
  };

  const handleFilter = (selectedTags) => {
    setSelectedTags(selectedTags); // Update selected tags
  };

  const isMetaAgent = agentType === META_AGENT;

  const filteredData = (
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

  return (
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
        <div className={styles.searchBar}>
          <SearchInput
            inputProps={{
              placeholder: `Search ${isMetaAgent ? "Agents" : "Tools"}`,
              onKeyDown: (e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                }
              },
            }}
            handleSearch={handleSearch}
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
            {filteredData.length > 0 && (
              <span className={style.filterBadge}>{selectedTags.length}</span>
            )}
          </button>
        </div>
      </div>
      <div className={styles.toolsContainer} ref={toolListContainerRef}>
        {/* {(toggleSelected ? MAPPED_TOOLS : NEW_TOOLS).map((tool) => ( */}
        {filteredData.map((tool) => (
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
      <AddToolsFilterModal
        show={filterModalOpen}
        onClose={() => setFilterModalOpen(false)}
        tags={tags}
        handleFilter={handleFilter}
        selectedTags={selectedTags}
      />
    </div>
  );
};

export default AddTools;
