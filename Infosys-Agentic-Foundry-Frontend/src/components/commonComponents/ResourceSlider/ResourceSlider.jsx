import React, { useState, useEffect, useRef, useMemo } from "react";
import ReactDOM from "react-dom";
import styles from "./ResourceSlider.module.css";
import SVGIcons from "../../../Icons/SVGIcons";
import { debounce } from "../../../utils/apiErrorHandler";
import { useErrorHandler } from "../../../Hooks/useErrorHandler";
import { useToolsAgentsService } from "../../../services/toolService";
import { useMcpServerService } from "../../../services/serverService";
import { useKnowledgeBaseService } from "../../../services/knowledgeBaseService";
import { META_AGENT, PLANNER_META_AGENT, HYBRID_AGENT, agentTypesDropdown } from "../../../constant";
import ToolDetailModal from "../../ToolDetailModal/ToolDetailModal";
import UnifiedFilterDropdown from "../UnifiedFilterDropdown";
import IAFButton from "../../../iafComponents/GlobalComponents/Buttons/Button";
import { sanitizeInput } from "../../../utils/sanitization";
import TextField from "../../../iafComponents/GlobalComponents/TextField/TextField";
import { usePermissions } from "../../../context/PermissionsContext";

/**
 * ResourceSlider - Reusable component for selecting tools/servers
 * @param {Object} props
 * @param {boolean} props.isOpen - Whether the slider is visible
 * @param {function} props.onClose - Callback when slider closes
 * @param {Array} props.selectedResources - Currently selected resources
 * @param {function} props.onSaveSelection - Callback with selected resources
 * @param {function} props.onClearAll - Callback to clear all selections
 * @param {string} props.initialTab - Initial tab ("tools" or "servers" or "agents")
 * @param {string} props.agentType - Type of agent (e.g., META_AGENT, PLANNER_META_AGENT)
 */
const ResourceSlider = ({ isOpen, onClose, selectedResources = [], onSaveSelection, onClearAll, initialTab = "tools", agentType = "" }) => {
  // Check if this is a meta agent (requires agents instead of tools/servers)
  const isMetaAgent = agentType === META_AGENT || agentType === PLANNER_META_AGENT;

  // For meta agents, default to "agents" tab; otherwise use the provided initialTab
  const [resourceTab, setResourceTab] = useState(isMetaAgent ? "agents" : initialTab);
  const [searchResourceQuery, setSearchResourceQuery] = useState("");
  const [allResources, setAllResources] = useState([]);
  const [filteredResources, setFilteredResources] = useState([]);
  const [internalSelectedResources, setInternalSelectedResources] = useState(selectedResources);
  const [loadingResources, setLoadingResources] = useState(false);
  const [resourcesPage, setResourcesPage] = useState(1);
  const [resourcesHasMore, setResourcesHasMore] = useState(true);
  const resourcesContainerRef = useRef(null);

  // Preview modal state
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [previewResource, setPreviewResource] = useState(null);

  // Expanded state for when editing a resource (shows AddServer/UpdateTool form)
  const [isSliderExpanded, setIsSliderExpanded] = useState(false);

  // Collapsed state for shrinking slider to show only toggle button
  const [isSliderCollapsed, setIsSliderCollapsed] = useState(false);

  // Filter state for UnifiedFilterDropdown
  const [selectedTypes, setSelectedTypes] = useState([]);

  const { handleError } = useErrorHandler();
  const { getToolsAndValidatorsPaginated, getAgentsSearchByPageLimit, calculateDivs } = useToolsAgentsService();
  const { getServersSearchByPageLimit } = useMcpServerService();
  const { getKnowledgeBasesSearchByPageLimit } = useKnowledgeBaseService();
  const { hasPermission } = usePermissions();

  // Permission checks for resource tabs
  const canViewTools = hasPermission("read_access.tools", true);
  const canViewServers = hasPermission("read_access.tools", true); // Servers use same permission as tools
  const canViewKnowledgeBases = hasPermission("knowledgebase_access", true);
  const canViewAgents = hasPermission("read_access.agents", true);

  // Determine the first visible tab (fallback when default tab is not accessible)
  const getFirstVisibleTab = () => {
    if (canViewTools) return "tools";
    if (canViewServers) return "servers";
    if (canViewKnowledgeBases) return "knowledgebases";
    return null;
  };

  // Check if at least one tab is visible
  const hasVisibleTabs = canViewTools || canViewServers || canViewKnowledgeBases;

  // Reset collapse state and internal selections when slider opens
  useEffect(() => {
    if (isOpen) {
      setIsSliderCollapsed(false);
      setInternalSelectedResources(selectedResources);
    }
  }, [isOpen]);

  // Ensure resourceTab is set to "agents" when agentType changes to meta agent
  useEffect(() => {
    if (isMetaAgent) {
      setResourceTab("agents");
    }
  }, [isMetaAgent, agentType]);

  // Ensure resourceTab switches to a visible tab when permissions restrict access
  useEffect(() => {
    // Skip for meta agents (they only have agents tab)
    if (isMetaAgent) return;

    // Check if current tab is accessible
    const isCurrentTabAccessible =
      (resourceTab === "tools" && canViewTools) ||
      (resourceTab === "servers" && canViewServers) ||
      (resourceTab === "knowledgebases" && canViewKnowledgeBases);

    // If current tab is not accessible, switch to first visible tab
    if (!isCurrentTabAccessible && hasVisibleTabs) {
      const firstVisibleTab = getFirstVisibleTab();
      if (firstVisibleTab) {
        setResourceTab(firstVisibleTab);
      }
    }
  }, [isMetaAgent, resourceTab, canViewTools, canViewServers, canViewKnowledgeBases, hasVisibleTabs]);

  /**
   * Get type filter options based on current resource tab
   * - For agents tab: returns agent type options (meta, planner, react, etc.)
   * - For servers tab: returns server type options (remote, external, local)
   * - For tools tab: returns tool type options (tool, validator)
   */
  const getTypeOptions = () => {
    if (isMetaAgent || resourceTab === "agents") {
      return agentTypesDropdown.filter((type) => type.value !== "" && type.value !== META_AGENT && type.value !== PLANNER_META_AGENT && type.value !== HYBRID_AGENT);
    }
    if (resourceTab === "servers") {
      return [
        { value: "external", label: "External" },
        { value: "local", label: "Local" },
        { value: "remote", label: "Remote" },
      ];
    }
    if (resourceTab === "knowledgebases") {
      // Knowledge bases don't have type filters currently
      return [];
    }
    // Tools tab
    return [
      { value: "tool", label: "Tools" },
      { value: "validator", label: "Validator" },
    ];
  };

  /**
   * Handle filter apply - triggers API call with filter values
   */
  const handleFilterApply = (appliedTypes) => {
    setResourcesPage(1);
    setResourcesHasMore(true);
    fetchResourcesPage(resourceTab, 1, false, searchResourceQuery.trim(), appliedTypes);
  };

  /**
   * Handle filter clear - resets filters and fetches default list
   */
  const handleFilterClear = () => {
    setSelectedTypes([]);
    setResourcesPage(1);
    setResourcesHasMore(true);
    fetchResourcesPage(resourceTab, 1, false, searchResourceQuery.trim(), []);
  };

  // Sync internal state with external selected resources
  useEffect(() => {
    setInternalSelectedResources(selectedResources);
  }, [selectedResources]);

  // Paginated fetch for resources (tools, servers, or agents)
  const fetchResourcesPage = async (type, page = 1, append = false, search = "", filterTypes = []) => {
    setLoadingResources(true);
    try {
      const limit = calculateDivs(resourcesContainerRef, 231, 70, 26);
      let response;

      // For meta agents, always use agents API regardless of type parameter
      // This ensures search and filter always call the correct endpoint
      const effectiveType = isMetaAgent ? "agents" : type;

      if (effectiveType === "agents") {
        // Agents API expects agentic_application_type parameter
        // If multiple types selected, join them (API may need to handle comma-separated or multiple params)
        const agentTypeFilter = filterTypes.length > 0 ? filterTypes.join(",") : undefined;
        response = await getAgentsSearchByPageLimit({
          page,
          limit,
          search,
          agentic_application_type: agentTypeFilter,
        });
      } else if (effectiveType === "knowledgebases") {
        // Knowledge bases API
        response = await getKnowledgeBasesSearchByPageLimit({
          page,
          limit,
          search,
        });
      } else if (effectiveType === "tools") {
        // Use show_tools / show_validators API params (same as tools list page)
        let show_tools = undefined;
        let show_validators = undefined;
        if (filterTypes.length > 0) {
          const hasTools = filterTypes.includes("tool");
          const hasValidators = filterTypes.includes("validator");
          if (hasTools && !hasValidators) {
            show_tools = true;
            show_validators = false;
          } else if (!hasTools && hasValidators) {
            show_tools = false;
            show_validators = true;
          }
          // If both selected, leave undefined to show all
        }
        response = await getToolsAndValidatorsPaginated({
          page,
          limit,
          search,
          show_tools,
          show_validators,
        });
      } else {
        // Servers API expects types param (same as servers list page)
        const serverTypes = filterTypes.length > 0 ? filterTypes : undefined;
        response = await getServersSearchByPageLimit({
          page,
          limit,
          search,
          types: serverTypes,
        });
      }

      const items = response?.details || [];

      if (append) {
        setAllResources((prev) => (Array.isArray(prev) ? [...prev, ...items] : items));
        setFilteredResources((prev) => (Array.isArray(prev) ? [...prev, ...items] : items));
      } else {
        setAllResources(items);
        setFilteredResources(items);
      }

      if (!items || items.length < limit) {
        setResourcesHasMore(false);
      } else {
        setResourcesHasMore(true);
      }
    } catch (err) {
      handleError(err, { customMessage: `Failed to load ${type}` });
      if (!append) {
        setAllResources([]);
        setFilteredResources([]);
      }
      setResourcesHasMore(false);
    } finally {
      setLoadingResources(false);
    }
  };

  // Load resources when slider opens or tab changes
  useEffect(() => {
    if (isOpen) {
      setResourcesPage(1);
      setResourcesHasMore(true);
      setSearchResourceQuery(""); // Reset search when tab changes
      setSelectedTypes([]); // Reset filters when tab changes
      // Clear previous tab's data before fetching new tab's data
      setAllResources([]);
      setFilteredResources([]);
      fetchResourcesPage(resourceTab, 1, false, "", []);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, resourceTab]);

  // Trigger search - reusable for Enter key and search icon click
  const triggerSearch = () => {
    const trimmedValue = searchResourceQuery.trim();
    setResourcesPage(1);
    setResourcesHasMore(true);
    fetchResourcesPage(resourceTab, 1, false, trimmedValue, selectedTypes);
  };

  // Handle search on Enter key press - triggers API call
  const handleSearchKeyDown = (e) => {
    if (e.key === "Enter") {
      triggerSearch();
    }
  };

  // Handle clear search - resets to initial state
  const handleClearSearch = () => {
    setSearchResourceQuery("");
    setResourcesPage(1);
    setResourcesHasMore(true);
    fetchResourcesPage(resourceTab, 1, false, "", selectedTypes);
  };

  // Attach debounced scroll listener for loading more resources
  useEffect(() => {
    const container = resourcesContainerRef?.current;
    if (!container) return;

    const debouncedHandleScroll = debounce(() => {
      const { scrollTop, scrollHeight, clientHeight } = container;
      if (scrollTop + clientHeight >= scrollHeight - 20 && !loadingResources && resourcesHasMore) {
        fetchResourcesPage(resourceTab, resourcesPage + 1, true, searchResourceQuery.trim(), selectedTypes);
        setResourcesPage((prev) => prev + 1);
      }
    }, 200);

    container.addEventListener("scroll", debouncedHandleScroll);
    return () => container.removeEventListener("scroll", debouncedHandleScroll);
  }, [resourceTab, loadingResources, resourcesHasMore, resourcesPage, searchResourceQuery]);

  // Toggle resource selection
  const toggleResourceSelection = (resource) => {
    // Auto-expand slider when selecting a resource
    if (isSliderCollapsed) {
      setIsSliderCollapsed(false);
    }

    const resourceId = resource.tool_id || resource.agentic_application_id || resource.id;
    const resourceName = resource.tool_name || resource.agentic_application_name || resource.name;

    const isSelected = internalSelectedResources.some((r) => {
      const selectedId = r.tool_id || r.agentic_application_id || r.id;
      const selectedName = r.tool_name || r.agentic_application_name || r.name;
      return String(selectedId) === String(resourceId) || (selectedName && resourceName && selectedName === resourceName);
    });

    if (isSelected) {
      setInternalSelectedResources(internalSelectedResources.filter((r) => {
        const selectedId = r.tool_id || r.agentic_application_id || r.id;
        const selectedName = r.tool_name || r.agentic_application_name || r.name;
        return !(String(selectedId) === String(resourceId) || (selectedName && resourceName && selectedName === resourceName));
      }));
    } else {
      // Add type property based on current tab to enable proper grouping in ResourceAccordion
      const resourceWithType = { ...resource, type: resourceTab };
      setInternalSelectedResources([...internalSelectedResources, resourceWithType]);
    }
  };

  // Check if resource is selected - compare by ID or name for reliable matching
  const isResourceSelected = (resource) => {
    const resourceId = resource.tool_id || resource.agentic_application_id || resource.id;
    const resourceName = resource.tool_name || resource.agentic_application_name || resource.name;

    return internalSelectedResources.some((r) => {
      const selectedId = r.tool_id || r.agentic_application_id || r.id;
      const selectedName = r.tool_name || r.agentic_application_name || r.name;

      // Compare by ID (convert to string for type-safe comparison) or by name
      return String(selectedId) === String(resourceId) || (selectedName && resourceName && selectedName === resourceName);
    });
  };

  // Memoized sorted resources - selected items appear at top
  const sortedResources = useMemo(() => {
    // Create a Set of selected IDs and names for faster lookup
    const selectedIds = new Set();
    const selectedNames = new Set();

    // Filter internalSelectedResources to only include items matching the current tab
    const currentTabResources = internalSelectedResources.filter((r) => {
      // If resource has a type, check if it matches current tab
      if (r.type) {
        return r.type === resourceTab;
      }
      // Fallback: for tools tab, check for tool_id; for servers, check for mcp_config; for agents, check for agentic_application_id
      if (resourceTab === "tools") {
        return r.tool_id && !r.mcp_config;
      } else if (resourceTab === "servers") {
        return r.mcp_config;
      } else if (resourceTab === "agents") {
        return r.agentic_application_id;
      }
      return true;
    });

    currentTabResources.forEach((r) => {
      const id = r.tool_id || r.agentic_application_id || r.id;
      const name = r.tool_name || r.agentic_application_name || r.name;
      if (id) selectedIds.add(String(id));
      if (name) selectedNames.add(name);
    });

    // Check if a resource is in the selected set
    const checkSelected = (resource) => {
      const resourceId = resource.tool_id || resource.agentic_application_id || resource.id;
      const resourceName = resource.tool_name || resource.agentic_application_name || resource.name;
      return selectedIds.has(String(resourceId)) || (resourceName && selectedNames.has(resourceName));
    };

    // Only prepend missing selected resources when there's NO search query AND NO filter applied
    // When searching or filtering, only show filtered results (with selected ones sorted to top)
    const hasSearchQuery = searchResourceQuery.trim().length > 0;
    const hasFilterApplied = selectedTypes.length > 0;

    if (hasSearchQuery || hasFilterApplied) {
      // When searching or filtering, just sort filtered results - selected items first
      return [...filteredResources].sort((a, b) => {
        const aSelected = checkSelected(a);
        const bSelected = checkSelected(b);
        if (aSelected && !bSelected) return -1;
        if (!aSelected && bSelected) return 1;
        return 0;
      });
    }

    // No search query - prepend missing selected items (only for current tab)
    // Find selected resources that are NOT in filteredResources
    const filteredIds = new Set();
    const filteredNames = new Set();
    filteredResources.forEach((r) => {
      const id = r.tool_id || r.agentic_application_id || r.id;
      const name = r.tool_name || r.agentic_application_name || r.name;
      if (id) filteredIds.add(String(id));
      if (name) filteredNames.add(name);
    });

    // Get selected resources that need to be prepended (not already in filtered list, and matching current tab)
    const missingSelected = currentTabResources.filter((r) => {
      const id = r.tool_id || r.agentic_application_id || r.id;
      const name = r.tool_name || r.agentic_application_name || r.name;
      const inFiltered = filteredIds.has(String(id)) || (name && filteredNames.has(name));
      return !inFiltered;
    });

    // Combine: missing selected first, then sort remaining by selection status
    const sortedFiltered = [...filteredResources].sort((a, b) => {
      const aSelected = checkSelected(a);
      const bSelected = checkSelected(b);
      if (aSelected && !bSelected) return -1;
      if (!aSelected && bSelected) return 1;
      return 0;
    });

    return [...missingSelected, ...sortedFiltered];
  }, [filteredResources, internalSelectedResources, searchResourceQuery, selectedTypes, resourceTab]);

  // Handle tab change - expand slider when switching tabs
  const handleTabChange = (tab) => {
    if (isSliderCollapsed) {
      setIsSliderCollapsed(false);
    }
    setResourceTab(tab);
  };

  // Handle save selection
  const handleSaveSelection = () => {
    if (onSaveSelection) {
      onSaveSelection(internalSelectedResources);
    }
    onClose();
  };

  // Handle clear all - only clears internal state, parent is updated on save
  const handleClearAll = () => {
    setInternalSelectedResources([]);
  };

  // Handle preview button click - opens ToolDetailModal
  const handlePreview = (e, resource) => {
    e.stopPropagation();
    setPreviewResource(resource);
    setPreviewModalOpen(true);
  };

  // Helper to get code preview for servers (based on actual API response structure)
  const getServerCodePreview = (server) => {
    if (!server) return "";

    // For FILE/LOCAL servers, code is in mcp_config.args[1]
    const mcpType = (server?.mcp_type || "").toLowerCase();

    // Only return code for "file" type servers (LOCAL)
    if (mcpType === "file") {
      const codeContent = server?.mcp_config?.args?.[1];
      if (typeof codeContent === "string" && codeContent.trim().length > 0) {
        return codeContent;
      }
    }

    return "# No code available for this server.";
  };

  // Helper to get module name for EXTERNAL servers
  const getServerModuleName = (server) => {
    if (!server) return "";
    const mcpType = (server?.mcp_type || "").toLowerCase();

    // For MODULE/EXTERNAL servers, module name is in mcp_config.args[1]
    if (mcpType === "module") {
      return server?.mcp_config?.args?.[1] || "";
    }
    return "";
  };

  // Helper to get endpoint for REMOTE servers
  const getServerEndpoint = (server) => {
    if (!server) return "";
    const mcpType = (server?.mcp_type || "").toLowerCase();

    // For URL/REMOTE servers, endpoint is in mcp_config.url
    if (mcpType === "url") {
      return server?.mcp_config?.url || "";
    }
    return "";
  };

  // Check if the preview resource is mapped (already selected)
  const isPreviewResourceMapped = (resource) => {
    if (!resource) return false;
    const resourceId = resource.tool_id || resource.agentic_application_id || resource.id;
    return internalSelectedResources.some((r) => (r.tool_id || r.agentic_application_id || r.id) === resourceId);
  };

  if (!isOpen) return null;

  return ReactDOM.createPortal(
    <>
      {/* Backdrop overlay - blocks content behind slider - only show when expanded */}
      {!isSliderCollapsed && isOpen && <div className={`${styles.sliderBackdrop} ${styles.visible}`} onClick={onClose} aria-hidden="true" />}
      <div className={`${styles.sliderOverlay} ${isSliderExpanded ? styles.sliderOverlayExpanded : ""} ${isSliderCollapsed ? styles.collapsed : ""}`}>
        <div className={styles.sliderContainer}>
          {/* Slider Toggle Button - Collapse/Expand */}
          <button
            className={`${styles.sliderToggle} ${isSliderCollapsed ? styles.toggleCollapsed : ""}`}
            onClick={() => setIsSliderCollapsed((prev) => !prev)}
            aria-label={isSliderCollapsed ? "Expand resources" : "Collapse resources"}>
            <SVGIcons icon="chevronRight" width={16} height={16} />
          </button>

          {/* Slider Header */}
          <div className={styles.sliderHeader}>
            <div>
              <h2 className={styles.sliderTitle}>Add Resources</h2>
              {/* <p className={styles.sliderSubtitle}>{resourceTab === "tools" ? "Tools" : "Servers"}</p> */}
            </div>
            {/* <button className="closeBtn" onClick={onClose} aria-label="Close">
              <SVGIcons icon="x" width={16} height={16} color="var(--text-primary)" />
            </button> */}
            <button className="closeBtn" aria-label="Close modal" onClick={onClose}>
              ×
            </button>
          </div>

          {/* Tab Selector - Show Agents tab for meta agents, Tools/Servers/KnowledgeBases for others */}
          <div className={styles.tabContainer}>
            {isMetaAgent ? (
              /* Meta Agent: Show only Agents tab if user has permission */
              canViewAgents ? (
                <button className={`${styles.tab} ${styles.tabActive}`} disabled>
                  <SVGIcons icon="agent" width={16} height={16} />
                  <span className={styles.tabLabel}>Agents</span>
                </button>
              ) : (
                <span className={styles.noPermissionText}>No resources available</span>
              )
            ) : hasVisibleTabs ? (
              /* Other Agents: Show Tools, Servers, and Knowledge Bases tabs based on permissions */
              <>
                {canViewTools && (
                  <button className={`${styles.tab} ${resourceTab === "tools" ? styles.tabActive : ""}`} onClick={() => handleTabChange("tools")}>
                    <SVGIcons icon="wrench" width={16} height={16} />
                    <span className={styles.tabLabel}>Tools</span>
                  </button>
                )}
                {canViewServers && (
                  <button className={`${styles.tab} ${resourceTab === "servers" ? styles.tabActive : ""}`} onClick={() => handleTabChange("servers")}>
                    <SVGIcons icon="server" width={16} height={16} />
                    <span className={styles.tabLabel}>Servers</span>
                  </button>
                )}
                {canViewKnowledgeBases && (
                  <button className={`${styles.tab} ${resourceTab === "knowledgebases" ? styles.tabActive : ""}`} onClick={() => handleTabChange("knowledgebases")}>
                    <SVGIcons icon="knowledge-base" width={16} height={16} />
                    <span className={styles.tabLabel}>Knowledge Bases</span>
                  </button>
                )}
              </>
            ) : (
              <span className={styles.noPermissionText}>No resources available</span>
            )}
          </div>

          {/* Search and Filter */}
          <div className={styles.searchContainer}>
            <div className={styles.searchFilterRow}>
              <div className={styles.searchInputWrapper}>
                <TextField
                  placeholder={`Search ${isMetaAgent ? "agents" : resourceTab}...`}
                  value={searchResourceQuery}
                  onChange={(e) => {
                    const newValue = sanitizeInput(e.target.value, "text");
                    setSearchResourceQuery(newValue);
                    // When user clears input manually, trigger fresh fetch
                    if (newValue === "") {
                      handleClearSearch();
                    }
                  }}
                  onKeyDown={handleSearchKeyDown}
                  onClear={handleClearSearch}
                  showClearButton={true}
                  showSearchButton={true}
                  onSearch={triggerSearch}
                />
              </div>
              {resourceTab !== "knowledgebases" && (
                <UnifiedFilterDropdown
                  typeOptions={getTypeOptions()}
                  selectedTypes={selectedTypes}
                  onTypeChange={(newTypes) => setSelectedTypes(newTypes)}
                  industryOptions={[]}
                  selectedIndustries={[]}
                  onIndustryChange={() => { }}
                  createdByOptions={[]}
                  selectedCreatedBy="All"
                  onCreatedByChange={() => { }}
                  contextType={isMetaAgent ? "Agents" : resourceTab === "tools" ? "Tools" : resourceTab === "servers" ? "Servers" : "Knowledge Bases"}
                  onApply={(appliedTypes) => handleFilterApply(appliedTypes)}
                  onClear={handleFilterClear}
                />
              )}
            </div>
          </div>

          {/* Scrollable Resources List */}
          <div className={styles.resourcesListContainer} ref={resourcesContainerRef}>
            <div className={styles.resourcesGrid}>
              {/* Use memoized sorted resources: selected items first */}
              {sortedResources.map((resource) => {
                const resourceId = resource.tool_id || resource.agentic_application_id || resource.id;
                const isSelected = isResourceSelected(resource);

                return (
                  <div key={resourceId} className={`${styles.resourceItem} ${isSelected ? styles.resourceItemSelected : ""}`} onClick={() => toggleResourceSelection(resource)}>
                    <button
                      type="button"
                      className={styles.checkbox}
                      role="checkbox"
                      aria-checked={isSelected}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleResourceSelection(resource);
                      }}>
                      {isSelected && (
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          width="16"
                          height="16"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="3"
                          strokeLinecap="round"
                          strokeLinejoin="round">
                          <polyline points="20 6 9 17 4 12"></polyline>
                        </svg>
                      )}
                    </button>
                    {/* <span className={styles.resourceIcon}>
                    <SVGIcons icon={isMetaAgent ? "agent" : resourceTab === "tools" ? "wrench" : "server"} width={16} height={16} />
                  </span> */}
                    <span className={styles.resourceItemName}>{resource.tool_name || resource.agentic_application_name || resource.name}</span>
                    {resourceTab !== "knowledgebases" && (
                      <button type="button" className={styles.previewButton} aria-label="Preview resource" onClick={(e) => handlePreview(e, resource)}>
                        <SVGIcons icon="eye" width={16} height={16} />
                      </button>
                    )}
                  </div>
                );
              })}
              {loadingResources && <div className={styles.loadingState}>Loading more...</div>}
            </div>
            {!loadingResources && filteredResources.length === 0 && <div className={styles.emptyResourcesState}>No resources found</div>}
          </div>

          {/* Slider Footer */}
          <div className={styles.sliderFooter}>
            <div className={styles.selectedCount}>{internalSelectedResources.length} resources selected</div>
            <div className={styles.sliderFooterButtons}>
              <IAFButton type="primary" onClick={handleSaveSelection}>
                Save Selection
              </IAFButton>
              <IAFButton type="secondary" onClick={handleClearAll}>
                Clear All
              </IAFButton>
            </div>
          </div>
        </div>

        {/* Tool/Server/Agent Detail Modal - Uses ToolDetailModal like ToolCard.jsx */}
        <ToolDetailModal
          isOpen={previewModalOpen}
          onClose={() => {
            setPreviewModalOpen(false);
            setPreviewResource(null);
          }}
          description={
            isMetaAgent
              ? previewResource?.agentic_application_description || previewResource?.tool_description || previewResource?.description
              : previewResource?.tool_description || previewResource?.description
          }
          endpoint={(() => {
            // Endpoint only for REMOTE/URL servers (mcp_type: "url")
            if (resourceTab === "servers") {
              const mcpType = (previewResource?.mcp_type || "").toLowerCase();
              if (mcpType === "url") {
                return getServerEndpoint(previewResource);
              }
            }
            return undefined;
          })()}
          codeSnippet={(() => {
            // Code snippet for tools OR LOCAL/FILE servers only (mcp_type: "file")
            if (previewResource?.code_snippet) return previewResource.code_snippet;
            if (resourceTab === "servers") {
              const mcpType = (previewResource?.mcp_type || "").toLowerCase();
              if (mcpType === "file") {
                return getServerCodePreview(previewResource);
              }
            }
            return undefined;
          })()}
          moduleName={(() => {
            // Module name for EXTERNAL/MODULE servers only (mcp_type: "module")
            if (resourceTab === "servers") {
              const mcpType = (previewResource?.mcp_type || "").toLowerCase();
              if (mcpType === "module") {
                return getServerModuleName(previewResource);
              }
            }
            return undefined;
          })()}
          agenticApplicationWorkflowDescription={
            previewResource?.agentic_application_workflow_description ||
            previewResource?.workflow_description ||
            previewResource?.agenticApplicationWorkflowDescription ||
            previewResource?.server_workflow_description
          }
          systemPrompt={previewResource?.system_prompt || previewResource?.systemPrompt || previewResource?.server_system_prompt}
          isMappedTool={isPreviewResourceMapped(previewResource)}
          tool={previewResource}
          agentType={isMetaAgent ? agentType : undefined}
          resourceTab={resourceTab}
          hideModifyButton={
            // Hide modify for remote/external servers (mcp_type: "url" or "module") and for agents
            isMetaAgent || (resourceTab === "servers" && (previewResource?.mcp_type || "").toLowerCase() === "url")
          }
          useToolCardDescriptionStyle={true}
          onExpandSlider={(expanded) => setIsSliderExpanded(expanded)}
        />
      </div>
    </>,
    document.body
  );
};

export default ResourceSlider;
