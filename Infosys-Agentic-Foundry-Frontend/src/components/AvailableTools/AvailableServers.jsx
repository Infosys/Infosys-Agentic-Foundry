import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import SubHeader from "../commonComponents/SubHeader.jsx";
import styles from "../../css_modules/AvailableServers.module.css";
import { useMcpServerService } from "../../services/serverService";
import { usePermissions } from "../../context/PermissionsContext";
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";
import Cookies from "js-cookie";
import AddServer from "../AgentOnboard/AddServer.jsx";
import FilterModal from "../commonComponents/FilterModal.jsx";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import { useToolsAgentsService } from "../../services/toolService.js";
import { debounce } from "lodash";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import EmptyState from "../commonComponents/EmptyState.jsx";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import { useActiveNavClick } from "../../events/navigationEvents";
import { Modal } from "../commonComponents/Modal";

export default function AvailableServers(props) {
  const { getLiveToolDetails, deleteServer, getServersSearchByPageLimit } = useMcpServerService();
  const { calculateDivs } = useToolsAgentsService();
  // State for live tool details
  const [liveToolDetails, setLiveToolDetails] = useState([]);
  const [loadingTools, setLoadingTools] = useState(false);
  const [loading, setLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  // Handle + icon click internally to show AddServer modal
  const handlePlusClick = () => {
    setShowAddServerModal(true);
  };
  const [searchTerm, setSearchTerm] = useState("");
  const [servers, setServers] = useState([]);
  const [visibleData, setVisibleData] = useState([]);
  const [totalServersCount, setTotalServersCount] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const [selected, setSelected] = useState(null);
  const [open, setOpen] = useState(false);
  const [filterModal, setFilterModal] = useState(false);
  const [selectedFilterTags, setSelectedFilterTags] = useState([]);
  const [selectedServerTypes, setSelectedServerTypes] = useState([]);
  const [showAddServerModal, setShowAddServerModal] = useState(false);
  const [editServerData, setEditServerData] = useState(null);
  const pageRef = useRef(1);
  const serverListContainerRef = useRef(null);
  const isLoadingRef = useRef(false);
  const [tags, setTags] = useState([]);
  const { fetchData } = useFetch();
  const hasLoadedTagsOnce = useRef(false);

  // Copy and Zoom popup state
  const [copiedStates, setCopiedStates] = useState({});
  const [zoomPopup, setZoomPopup] = useState({ open: false, title: "", content: "" });

  // Created By dropdown state
  const [createdBy, setCreatedBy] = useState("All");
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");

  const { handleError } = useErrorHandler();

  // Permission checks for CRUD operations on servers (using tools permissions)
  const { hasPermission, loading: permissionsLoading } = usePermissions();
  const canReadServers = typeof hasPermission === "function" ? hasPermission("read_access.tools") : false;
  const canAddServers = typeof hasPermission === "function" ? hasPermission("add_access.tools") : false;
  const canUpdateServers = typeof hasPermission === "function" ? hasPermission("update_access.tools") : false;
  const canDeleteServers = typeof hasPermission === "function" ? hasPermission("delete_access.tools") : false;

  const getTags = useCallback(async () => {
    try {
      const data = await fetchData(APIs.GET_TAGS);
      setTags(data);
    } catch (e) {
      handleError(e, { context: "AvailableServers.getTags" });
    }
  }, [fetchData, handleError]);

  useEffect(() => {
    if (hasLoadedTagsOnce.current) return;
    hasLoadedTagsOnce.current = true;
    getTags();
  }, [getTags]);

  // Normalize API responses to always return a clean array of server objects
  const sanitizeServersResponse = (response) => {
    if (!response) return [];
    // If backend sometimes returns an object instead of array
    if (!Array.isArray(response)) return [];
    // If array contains a single message object with no server fields, treat as empty
    if (response.length === 1 && response[0] && typeof response[0] === "object" && "message" in response[0] && !("tool_id" in response[0])) {
      return [];
    }
    return response.filter((item) => item && typeof item === "object" && ("tool_id" in item || "tool_name" in item));
  };

  const mapServerData = useCallback((server) => {
    const raw = server || {};
    const hasCode = Boolean(raw?.mcp_config?.args?.[1] || raw?.mcp_file?.code_content || raw?.code_content || raw?.code || raw?.script);
    const hasUrl = Boolean(raw?.mcp_config?.url || raw?.mcp_url || raw?.endpoint || raw?.mcp_config?.mcp_url || raw?.mcp_config?.endpoint);

    let type;
    if (raw.mcp_type === "module") {
      type = "External";
    } else if (hasCode) {
      type = "Local";
    } else if (hasUrl) {
      type = "Remote";
    } else {
      // Title case the fallback value
      const rawType = String(raw.mcp_type || raw.type || "");
      type = rawType ? rawType.charAt(0).toUpperCase() + rawType.slice(1).toLowerCase() : "Unknown";
    }

    const endpoint = raw.mcp_url || (raw.mcp_config && (raw.mcp_config.url || raw.mcp_config.mcp_url || raw.mcp_config.endpoint)) || raw.endpoint || "";

    return {
      id: raw.tool_id || raw.id,
      name: raw.tool_name || raw.name,
      status: raw.status || "approved",
      type,
      team_id: raw.team_id || "Public",
      description: raw.tool_description || raw.description,
      tags: Array.isArray(raw.tag_ids)
        ? raw.tag_ids.map((t) => (typeof t === "object" ? t.tag_name || t.tag : t))
        : Array.isArray(raw.tags)
          ? raw.tags.map((t) => (typeof t === "object" ? t.tag_name || t.tag : t))
          : [],
      endpoint: endpoint || "",
      tools: raw.tools || [],
      created_by: raw.created_by || raw.user_email_id || raw.createdBy || raw.created_by_email || raw.creator_email || "",
      raw: raw,
    };
  }, []);

  const handleSearch = async (searchValue, divsCount, pageNumber, tagsToUse = null, typesToUse = null, createdByToUse = null) => {
    setSearchTerm(searchValue || "");
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    setLoading(true);

    try {
      // Use provided params or fall back to state
      const tagsForSearch = tagsToUse !== null ? tagsToUse : selectedFilterTags;
      const typesForSearch = typesToUse !== null ? typesToUse : selectedServerTypes;
      // Use createdByToUse if provided, otherwise fall back to state
      const createdByValue = createdByToUse !== null ? createdByToUse : createdBy;
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : undefined;
      const response = await getServersSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: searchValue ? searchValue : "",
        tags: tagsForSearch?.length > 0 ? tagsForSearch : undefined,
        types: typesForSearch?.length > 0 ? typesForSearch : undefined,
        created_by: createdByEmail,
      });

      // Setting the total count from API response
      setTotalServersCount(response.total_count || 0);

      const dataToSearch = sanitizeServersResponse(response.details || response);
      const mappedData = dataToSearch.map(mapServerData);

      setVisibleData(mappedData);
      setHasMore(dataToSearch.length >= divsCount);
    } catch (error) {
      handleError(error, { context: "AvailableServers.handleSearch" });
      setVisibleData([]); // Clear visibleData on error
      setHasMore(false);
    } finally {
      setLoading(false); // Hide loader
    }
  };
  const getServersData = useCallback(
    async (pageNumber, divsCount) => {
      return getServersDataWithTags(pageNumber, divsCount, selectedFilterTags, selectedServerTypes);
    },
    [getServersSearchByPageLimit, mapServerData, selectedFilterTags, selectedServerTypes]
  );
  const clearSearch = () => {
    setSearchTerm("");
    setSelectedFilterTags([]);
    setSelectedServerTypes([]);
    setCreatedBy("All");
    setVisibleData([]);
    setHasMore(true);
    pageRef.current = 1;
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
    // Call getServersDataWithTags with explicitly empty tags and types (matches handleRefreshClick)
    getServersDataWithTags(1, divsCount, [], []);
  };

  const visible = useMemo(() => {
    if (searchTerm.trim()) {
      return visibleData;
    }
    return visibleData;
  }, [searchTerm, visibleData]);

  useEffect(() => {
    const handler = () => {
      try {
        setShowAddServerModal(false);
        setEditServerData(null);
      } catch (e) { }
    };
    window.addEventListener("AddServer:CloseRequested", handler);
    return () => window.removeEventListener("AddServer:CloseRequested", handler);
  }, []);
  // Refresh only when AddServer signals success (AddServer dispatches AddServer:RefreshRequested)
  useEffect(() => {
    const refreshHandler = () => {
      try {
        const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
        pageRef.current = 1;
        getServersData(1, divsCount);
      } catch (e) {
        // swallow
      }
    };
    window.addEventListener("AddServer:RefreshRequested", refreshHandler);
    return () => window.removeEventListener("AddServer:RefreshRequested", refreshHandler);
  }, [calculateDivs, getServersData]);
  const handleScrollLoadMore = useCallback(async () => {
    if (loading || isLoadingRef.current || !hasMore) return; // Prevent multiple calls or if no more data
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
    if (!divsCount || typeof divsCount !== "number" || !Number.isFinite(divsCount)) {
      // Defensive: release the lock and skip this cycle; will be recalculated on next scroll/resize
      isLoadingRef.current = false;
      return;
    }

    try {
      setIsLoadingMore(true);
      let newData = [];

      if (searchTerm.trim()) {
        // Load more search results
        const response = await getServersSearchByPageLimit({
          page: nextPage,
          limit: divsCount,
          search: searchTerm,
          tags: selectedFilterTags?.length > 0 ? selectedFilterTags : undefined,
          types: selectedServerTypes?.length > 0 ? selectedServerTypes : undefined,
        });

        // Update total count if provided in response (though it should be the same)
        if (response.total_count !== undefined) {
          setTotalServersCount(response.total_count);
        }

        const initialData = sanitizeServersResponse(response.details || response);
        newData = initialData.map(mapServerData);
      } else {
        // Load more regular data
        // Pass created_by email when "Me" filter is selected
        const createdByEmail = createdBy === "Me" ? loggedInUserEmail : undefined;
        const response = await getServersSearchByPageLimit({
          page: nextPage,
          limit: divsCount,
          search: "",
          tags: selectedFilterTags?.length > 0 ? selectedFilterTags : undefined,
          types: selectedServerTypes?.length > 0 ? selectedServerTypes : undefined,
          created_by: createdByEmail,
        });

        // Update total count if provided in response (though it should be the same)
        if (response.total_count !== undefined) {
          setTotalServersCount(response.total_count);
        }

        const data = sanitizeServersResponse(response.details || response);
        newData = data.map(mapServerData);
        // Only update servers state for non-search scenarios
        setServers((prev) => {
          const updated = [...prev, ...newData];
          return updated;
        });
      }

      if (newData.length > 0) {
        setVisibleData((prev) => {
          const updated = [...(Array.isArray(prev) ? prev : []), ...newData];
          if (updated.length >= totalServersCount) setHasMore(false);
          return updated;
        });
        pageRef.current = nextPage;
        // If we got less than expected, we might be at the end
        if (newData.length < divsCount) {
          setHasMore(false);
        }
      } else {
        setHasMore(false);
      }
    } catch (error) {
      handleError(error, { context: "AvailableServers.loadMore" });
      setHasMore(false);
    } finally {
      setIsLoadingMore(false);
      isLoadingRef.current = false;
    }
  }, [loading, hasMore, searchTerm, selectedFilterTags, getServersSearchByPageLimit, mapServerData, calculateDivs, totalServersCount]);
  useEffect(() => {
    const container = serverListContainerRef?.current;
    if (!container) return;

    // Function to check if we need to load more data on scroll
    const checkAndLoadMore = () => {
      const scrollTop = container.scrollTop;
      const scrollHeight = container.scrollHeight;
      const clientHeight = container.clientHeight;

      // Check if user has scrolled near the bottom (within 50px for better detection)
      if (scrollTop + clientHeight >= scrollHeight - 50 && !loading && !isLoadingMore && !isLoadingRef.current && hasMore) {
        handleScrollLoadMore();
      }
    };

    const debouncedCheckAndLoad = debounce(checkAndLoadMore, 100); // 100ms debounce

    container.addEventListener("scroll", debouncedCheckAndLoad);

    // Also check on resize and when container changes
    const handleResize = () => {
      setTimeout(() => {
        checkAndLoadMore(); // Check immediately after resize
      }, 100);
    };

    // Initial check when container is ready
    const initialCheck = () => {
      setTimeout(() => {
        checkAndLoadMore();
      }, 100);
    };

    window.addEventListener("resize", handleResize);

    // Do an initial check
    initialCheck();
    return () => {
      window.removeEventListener("resize", handleResize);
      if (debouncedCheckAndLoad.cancel) debouncedCheckAndLoad.cancel();
      container.removeEventListener("scroll", debouncedCheckAndLoad);
    };
  }, [hasMore, loading, isLoadingMore, handleScrollLoadMore]);

  const fetchServers = useCallback(() => {
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
    pageRef.current = 1;
    getServersData(1, divsCount);
  }, [getServersData, calculateDivs]);
  const hasLoadedOnce = useRef(false);
  useEffect(() => {
    if (hasLoadedOnce.current) return; // prevent duplicate initial load
    hasLoadedOnce.current = true;
    fetchServers();
  }, [fetchServers]);

  // Check if we need to load more data after initial render
  useEffect(() => {
    const container = serverListContainerRef?.current;
    if (!container || !visible.length || loading || isLoadingRef.current) return;

    // Check multiple times to ensure container is fully rendered
    const checkAndLoadIfNeeded = () => {
      const scrollHeight = container.scrollHeight;
      const clientHeight = container.clientHeight;

      // If container doesn't have enough content to scroll, load more
      if (scrollHeight <= clientHeight + 50 && hasMore && !isLoadingRef.current) {
        handleScrollLoadMore();
      }
    };

    // Check immediately
    checkAndLoadIfNeeded();

    // Check again after a delay to ensure DOM is fully rendered
    const timeout1 = setTimeout(checkAndLoadIfNeeded, 200);
    const timeout2 = setTimeout(checkAndLoadIfNeeded, 500);
    const timeout3 = setTimeout(checkAndLoadIfNeeded, 1000); // Final check

    return () => {
      clearTimeout(timeout1);
      clearTimeout(timeout2);
      clearTimeout(timeout3);
    };
  }, [visible.length, hasMore, loading, handleScrollLoadMore]);

  useEffect(() => {
    // NOTE: This effect previously depended on getLiveToolDetails (likely unstable identity),
    // causing it to fire on every re-render (e.g. when an error toast shows/closes),
    // which re-triggered the API call -> infinite loop of errors.
    // We now only fetch when: (1) modal just opened for a server OR (2) selected server id changes.
    // We remember the last fetched id while the modal remains open to prevent duplicate calls.

    // Refs to track fetch session
    const fetchState = (AvailableServers.__liveToolsFetchState ||= { lastId: null, open: false });

    if (!open || !selected?.id) {
      // If modal closed, reset state & clear details
      if (!open) {
        fetchState.lastId = null;
        fetchState.open = false;
      }
      setLiveToolDetails([]);
      setLoadingTools(false);
      return;
    }

    // Prevent duplicate fetch for same id while modal is still open
    if (fetchState.open && fetchState.lastId === selected.id) {
      return;
    }

    fetchState.lastId = selected.id;
    fetchState.open = true;
    setLoadingTools(true);

    let isCancelled = false;
    getLiveToolDetails(selected.id)
      .then((data) => {
        if (isCancelled) return;
        setLiveToolDetails(Array.isArray(data) ? data : []);
      })
      .catch(() => {
        if (isCancelled) return;
        // Keep details empty; DO NOT reset fetchState so we don't spam retries until user changes selection or closes/reopens
        setLiveToolDetails([]);
      })
      .finally(() => {
        if (isCancelled) return;
        setLoadingTools(false);
      });

    return () => {
      isCancelled = true;
    };
    // Intentionally exclude getLiveToolDetails from deps to avoid re-fetch loops due to unstable function reference.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, selected?.id]);

  // handleDeleteClick is called when user confirms delete in the Card component's delete confirmation UI
  const handleDeleteClick = async (name, item) => {
    const server = item || {};
    const serverId = server.id || server.tool_id || (server.raw && (server.raw.id || server.raw.tool_id));

    if (!serverId) {
      addMessage("Cannot delete: Server ID not found", "error");
      return;
    }

    // Call the delete API directly since Card.jsx already shows confirmation
    const role = Cookies.get("role") || "";
    const loggedInUserEmail = (Cookies.get("email") || "").trim();
    const isAdmin = (role || "").toLowerCase() === "admin";
    const data = { user_email_id: loggedInUserEmail, is_admin: isAdmin };

    try {
      const response = await deleteServer(data, serverId);
      if (response?.is_delete) {
        // Refresh the server list after delete
        const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
        getServersData(1, divsCount);
        addMessage(response?.message || "Server deleted successfully", "success");
        setShowPopup(true);
      } else {
        let errorMessage = "Failed to delete server. Please try again.";
        if (response?.message) {
          errorMessage = response.message;
        } else if (response?.detail) {
          errorMessage = response.detail;
        }
        addMessage(errorMessage, "error");
      }
    } catch (err) {
      let errorMessage = "Failed deleting server";
      if (err?.response?.data?.detail) {
        errorMessage = err.response.data.detail;
      } else if (err?.response?.data?.message) {
        errorMessage = err.response.data.message;
      } else if (err?.message) {
        errorMessage = err.message;
      }
      addMessage(errorMessage, "error");
    }
  };

  const { addMessage, setShowPopup } = useMessage();

  const handleRefreshClick = async () => {
    try {
      setSearchTerm("");
      setSelectedFilterTags([]);
      setSelectedServerTypes([]);
      setCreatedBy("All"); // Reset created by filter
      setServers([]);
      setVisibleData([]);
      setHasMore(true);
      pageRef.current = 1;
      const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
      // Call getServersDataWithTags with explicitly empty tags to match tools implementation
      await getServersDataWithTags(1, divsCount, [], []);
    } catch (e) {
      // swallow
    }
  };

  const handleFilterApply = async (selectedTagsParam, typesParam = null, createdByParam = null) => {
    setSelectedFilterTags(selectedTagsParam || []);
    // If types parameter is provided, use it; otherwise use current state
    const typesToUse = typesParam !== null ? typesParam : selectedServerTypes;
    if (typesParam !== null) {
      setSelectedServerTypes(typesParam);
    }
    // If createdBy parameter is provided, update state
    const createdByToUse = createdByParam !== null ? createdByParam : createdBy;
    if (createdByParam !== null) {
      setCreatedBy(createdByParam);
    }
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    // Trigger new API call with selected tags - pass all parameters directly
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
    if (searchTerm.trim()) {
      // If there's a search term, use handleSearch with current search and filters
      await handleSearch(searchTerm, divsCount, 1, selectedTagsParam, typesToUse, createdByToUse);
    } else {
      // No search term, fetch data with all filters
      await getServersDataWithTags(1, divsCount, selectedTagsParam, typesToUse, createdByToUse);
    }
  };

  const getServersDataWithTags = async (pageNumber, divsCount, tagsToUse, typesToUse, createdByToUse = null) => {
    if (isLoadingRef.current) return []; // Prevent multiple simultaneous calls
    isLoadingRef.current = true;
    setLoading(true);
    try {
      // Use createdByToUse if provided, otherwise fall back to state
      const createdByValue = createdByToUse !== null ? createdByToUse : createdBy;
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : undefined;
      // Use the new API endpoint for paginated servers with tag filtering
      const response = await getServersSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: searchTerm,
        tags: tagsToUse?.length > 0 ? tagsToUse : undefined,
        types: typesToUse?.length > 0 ? typesToUse : undefined,
        created_by: createdByEmail,
      });

      const dataToSearch = sanitizeServersResponse(response.details || response);
      // if ((tags || []).length > 0) {
      //   dataToSearch = dataToSearch.filter((item) => {
      //     const typeFilters = (tags || []).filter((t) => t === "LOCAL" || t === "REMOTE");
      //     const tagFilters = (tags || []).filter((t) => t !== "LOCAL" && t !== "REMOTE");
      //     const mapped = mapServerData(item);
      //     const typeMatch = typeFilters.length === 0 || typeFilters.includes(String(mapped.type).toUpperCase());
      //     const tagMatch = tagFilters.length === 0 || (Array.isArray(mapped.tags) && mapped.tags.some((tag) => tagFilters.includes(tag)));
      //     return typeMatch && tagMatch;
      //   });
      // }
      const mappedData = dataToSearch.map(mapServerData);

      if (pageNumber === 1) {
        // Initial load - replace all data
        setServers(mappedData);
        setVisibleData(mappedData);
      } else {
        // Pagination - append data
        if (mappedData.length > 0) {
          setServers((prev) => {
            const updated = [...prev, ...mappedData];
            return updated;
          });
          setVisibleData((prev) => {
            const currentData = Array.isArray(prev) ? prev : [];
            const updated = [...currentData, ...mappedData];
            return updated;
          });
        }
      }

      // Use total_count from response if available, otherwise use current data length
      setTotalServersCount(response.total_count || mappedData?.length || 0);

      // If fewer items than requested were returned, we've reached the end
      if (mappedData.length < divsCount) {
        setHasMore(false);
      } else if (pageNumber === 1) {
        // Reset hasMore on fresh load only when page is full
        setHasMore(true);
      }

      return mappedData; // return fetched data for caller decisions
    } catch (error) {
      console.error("Error fetching servers:", error);
      if (pageNumber === 1) {
        setServers([]);
        setVisibleData([]);
      }
      setHasMore(false);
      return [];
    } finally {
      setLoading(false);
      isLoadingRef.current = false;
    }
  };

  const handleTypeFilter = async (e) => {
    const types = e.target.value; // array for multi-select
    setSelectedServerTypes(types);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
    if (searchTerm.trim()) {
      await handleSearch(searchTerm, divsCount, 1, selectedFilterTags, types, createdBy);
    } else {
      await getServersDataWithTags(1, divsCount, selectedFilterTags, types, createdBy);
    }
  };

  // Handler for Created By dropdown - only updates state
  // API call is triggered by handleFilterApply via onTagsChange/onApply
  const handleCreatedByChange = (value) => {
    setCreatedBy(value);
  };

  useActiveNavClick("/servers", () => {
    setShowAddServerModal(false);
    setEditServerData(null);
  });

  return (
    <>
      {/* AddServer modal for add/edit */}
      {showAddServerModal &&
        (editServerData ? (
          <AddServer
            editMode={true}
            serverData={editServerData}
            readOnly={canReadServers && !canUpdateServers}
            setRefreshPaginated={async () => {
              try {
                const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
                pageRef.current = 1;
                // Preserve search term: if search is active, use handleSearch to maintain filtered results
                if (searchTerm.trim()) {
                  await handleSearch(searchTerm, divsCount, 1, selectedFilterTags, selectedServerTypes, createdBy);
                } else {
                  await getServersData(1, divsCount);
                }
              } catch (e) {
                console.error("[AvailableServers] Refresh paginated failed:", e);
              }
            }}
            onClose={() => {
              setShowAddServerModal(false);
              setEditServerData(null);
            }}
          />
        ) : (
          <AddServer
            editMode={false}
            serverData={null}
            setRefreshPaginated={async () => {
              try {
                const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
                pageRef.current = 1;
                // Preserve search term: if search is active, use handleSearch to maintain filtered results
                if (searchTerm.trim()) {
                  await handleSearch(searchTerm, divsCount, 1, selectedFilterTags, selectedServerTypes, createdBy);
                } else {
                  await getServersData(1, divsCount);
                }
              } catch (e) {
                console.error("[AvailableServers] Refresh paginated failed:", e);
              }
            }}
            onClose={() => {
              setShowAddServerModal(false);
              setEditServerData(null);
            }}
          />
        ))}

      {loading && <Loader />}

      <div className={"pageContainer"}>
        <SubHeader
          heading={"Servers"}
          activeTab={"servers"}
          onSearch={(value) => handleSearch(value, calculateDivs(serverListContainerRef, 200, 140, 16), 1, selectedFilterTags, selectedServerTypes)}
          searchValue={searchTerm}
          clearSearch={clearSearch}
          handleRefresh={handleRefreshClick}
          onPlusClick={canAddServers ? handlePlusClick : undefined}
          showPlusButton={canAddServers}
          selectedTags={selectedFilterTags}
          reverseButtons={true}
          showTagsDropdown={true}
          availableTags={tags.map((tag) => tag.tag_name || tag)}
          selectedTagsForDropdown={selectedFilterTags}
          onTagsChange={handleFilterApply}
          selectedAgentType={selectedServerTypes}
          showCreatedByDropdown={true}
          createdBy={createdBy}
          onCreatedByChange={handleCreatedByChange}
          handleTypeFilter={handleTypeFilter}
        />

        {/* Conditional summary line only when we have visible data */}
        <SummaryLine visibleCount={visible.length} totalCount={totalServersCount} />
        <div className="listWrapper" ref={serverListContainerRef} aria-label="Servers list scrollable container">
          {visible?.length > 0 && (
            <DisplayCard1
              data={visible}
              // Card click - if read access, open modal (readOnly if no update access); if no read access, not clickable
              onCardClick={(canReadServers || canUpdateServers) ? (name, item) => {
                setEditServerData(item.raw && Object.keys(item.raw).length ? item.raw : item);
                setShowAddServerModal(true);
              } : undefined}
              // Dotted button = view
              onButtonClick={(name, item) => {
                setSelected(item);
                setOpen(true);
              }}
              onDeleteClick={canDeleteServers ? (name, item) => handleDeleteClick(name, item) : undefined}
              onEditClick={canUpdateServers ? (item) => {
                setEditServerData(item.raw && Object.keys(item.raw).length ? item.raw : item);
                setShowAddServerModal(true);
              } : undefined}
              onCreateClick={canAddServers ? handlePlusClick : undefined}
              showDeleteButton={canDeleteServers}
              showButton={true}
              showCreateCard={false}
              buttonIcon={<SVGIcons icon="eye" width={16} height={16} />}
              enableComplexDelete={false}
              // loading={loading}
              // className={styles.serverGrid}
              cardNameKey="name"
              cardDescriptionKey="description"
              cardOwnerKey="created_by"
              cardCategoryKey="type"
              emptyMessage="No servers found"
              contextType="server"
              cardDisabled={!canReadServers && !canUpdateServers}
            />
          )}
          {/* Display EmptyState when filters are active but no results */}
          {(searchTerm.trim() || selectedFilterTags.length > 0 || selectedServerTypes.length > 0 || (createdBy && createdBy !== "All")) && visible.length === 0 && !loading && (
            <EmptyState
              filters={[
                ...selectedFilterTags,
                ...selectedServerTypes.map((type) => type.charAt(0).toUpperCase() + type.slice(1).toLowerCase()),
                ...(createdBy === "Me" ? ["Created By: Me"] : []),
                ...(searchTerm.trim() ? [`Search: ${searchTerm}`] : []),
              ]}
              onClearFilters={clearSearch}
              onCreateClick={canAddServers ? handlePlusClick : undefined}
              createButtonLabel={canAddServers ? "New Server" : undefined}
              showCreateButton={canAddServers}
            />
          )}
          {/* Display EmptyState when no data exists from backend (no filters applied) */}
          {!searchTerm.trim() && selectedFilterTags.length === 0 && selectedServerTypes.length === 0 && createdBy === "All" && visible.length === 0 && !loading && (
            <EmptyState
              message="No servers found"
              subMessage={canAddServers ? "Get started by creating your first server" : "No servers available"}
              onCreateClick={canAddServers ? handlePlusClick : undefined}
              createButtonLabel={canAddServers ? "New Server" : undefined}
              showClearFilter={false}
              showCreateButton={canAddServers}
            />
          )}
          {isLoadingMore && (
            <div className={styles.loadingMore}>
              Loading more...
            </div>
          )}
        </div>

        {/* {visible.length === 0 && !loading && (
          <div
            className={styles.noServersFound}
            style={{
              width: "100%",
              padding: "32px 0",
              textAlign: "center",
              color: "#b0b0b0",
              fontSize: "18px",
              fontWeight: 600,
              fontStyle: "italic",
              letterSpacing: "0.5px",
              display: "flex",
              flexDirection: "column",
              alignItems: "center",
              justifyContent: "center",
            }}>
            <SVGIcons icon="fa-server" width={48} height={48} fill="#b0b0b0" style={{ marginBottom: "12px" }} />
            No servers found
          </div>
        )} */}

        <Modal
          isOpen={open && selected}
          onClose={() => setOpen(false)}
          size={String(selected?.type || "").toUpperCase() === "LOCAL" ? "xl" : "md"}
          ariaLabel={`Server details: ${selected?.name || ""}`}
          className={`${styles.serverModal} ${String(selected?.type || "").toUpperCase() === "LOCAL" ? styles.modalWide : ""}`}
        >
          {selected && (
            <>
              <h3 className={styles.modalTitle}>{selected.name}</h3>
              <div className={styles.modalBody} style={String(selected.type || "").toUpperCase() === "REMOTE" ? { flexDirection: "column" } : undefined}>
                <div className={styles.modalLeft} style={String(selected.type || "").toUpperCase() === "REMOTE" ? { flex: "1 1 100%", maxWidth: "100%" } : undefined}>
                  <div className={styles.infoGrid}>
                    <div className={styles.infoCol}>
                      <div className={styles.infoRow}>
                        <strong>Description:</strong>
                        <span>{selected.description}</span>
                      </div>
                      <div className={styles.infoRow}>
                        <strong>Created by:</strong>
                        <span>{selected.created_by || "-"}</span>
                      </div>
                      {(String(selected.type || "").toUpperCase() === "REMOTE" || selected.endpoint) && (
                        <div className={styles.infoRow}>
                          <strong>Endpoint:</strong>
                          {selected.endpoint ? (
                            <a href={selected.endpoint} target="_blank" rel="noreferrer">
                              {selected.endpoint}
                              <svg width="12" height="12" viewBox="0 0 12 12" fill="none" xmlns="http://www.w3.org/2000/svg">
                                <path d="M7.5 1.5H10.5V4.5" stroke="#0073CF" strokeLinecap="round" strokeLinejoin="round" />
                                <path d="M5 7L10.5 1.5" stroke="#0073CF" strokeLinecap="round" strokeLinejoin="round" />
                                <path
                                  d="M9 6.5V9.5C9 9.76522 8.89464 10.0196 8.70711 10.2071C8.51957 10.3946 8.26522 10.5 8 10.5H2.5C2.23478 10.5 1.98043 10.3946 1.79289 10.2071C1.60536 10.0196 1.5 9.76522 1.5 9.5V4C1.5 3.73478 1.60536 3.48043 1.79289 3.29289C1.98043 3.10536 2.23478 3 2.5 3H5.5"
                                  stroke="#0073CF"
                                  strokeLinecap="round"
                                  strokeLinejoin="round"
                                />
                              </svg>
                            </a>
                          ) : (
                            <span>—</span>
                          )}
                        </div>
                      )}
                      <div className={styles.infoRow}>
                        <strong>Type:</strong>
                        <span className={styles.typeBadge}>{selected.type}</span>
                      </div>
                      {String(selected.type || "").toUpperCase() === "EXTERNAL" && selected?.raw?.mcp_config?.args?.[1] && (
                        <div className={styles.infoRow}>
                          <strong>Module:</strong>
                          <span>{selected.raw.mcp_config.args[1]}</span>
                        </div>
                      )}
                      {(() => {
                        if (String(selected.type || "").toUpperCase() === "REMOTE") {
                          // Show liveToolDetails if available, else fallback to selected.tools
                          if (loadingTools) {
                            return (
                              <div className={styles.infoRow}>
                                <strong>Tools:</strong>
                                <span>Loading...</span>
                              </div>
                            );
                          }
                          if (Array.isArray(liveToolDetails) && liveToolDetails.length > 0) {
                            return (
                              <div className={styles.infoRow}>
                                <div>
                                  <strong style={{ display: "inline-block" }}>Tools:</strong> <span className={styles.count}>{liveToolDetails.length}</span>
                                </div>
                                <ol className={styles.infoList}>
                                  {liveToolDetails.map((tool, idx) => (
                                    <li key={tool.name || tool.tool_name || tool.id || idx}>{tool.name || tool.tool_name || `Tool ${idx + 1}`}</li>
                                  ))}
                                </ol>
                              </div>
                            );
                          }
                          const count = Array.isArray(selected.tools) ? selected.tools.length : 0;
                          if (count > 0) {
                            return (
                              <div className={styles.infoRow}>
                                <div>
                                  <strong style={{ display: "inline-block" }}>Tools:</strong> <span className={styles.count}>{count}</span>
                                </div>
                                <ol className={styles.infoList}>
                                  {selected.tools.map((tool, idx) => (
                                    <li key={tool.name || tool.tool_name || tool.id || idx}>{tool.name || tool.tool_name || `Tool ${idx + 1}`}</li>
                                  ))}
                                </ol>
                              </div>
                            );
                          }
                          return (
                            <div className={styles.infoRow}>
                              <strong>Tools:</strong>
                              <span>No tools found for this REMOTE server.</span>
                            </div>
                          );
                        } else if (loadingTools) {
                          return (
                            <div className={styles.infoRow}>
                              <strong>Tools:</strong>
                              <span>Loading...</span>
                            </div>
                          );
                        } else if (liveToolDetails.length > 0) {
                          return (
                            <div className={styles.infoRow}>
                              <div>
                                <strong style={{ display: "inline-block" }}>Tools:</strong> <span className={styles.count}>{liveToolDetails.length}</span>
                              </div>
                              <ol className={styles.infoList}>
                                {liveToolDetails.map((tool, idx) => (
                                  <li key={tool.name || tool.tool_name || tool.id || idx}>{tool.name || tool.tool_name || `Tool ${idx + 1}`}</li>
                                ))}
                              </ol>
                            </div>
                          );
                        } else {
                          return (
                            <div className={styles.infoRow}>
                              <strong>Tools:</strong>
                              <span>0</span>
                            </div>
                          );
                        }
                      })()}
                    </div>
                  </div>
                </div>
                {String(selected.type || "").toUpperCase() === "LOCAL" && (
                  <div className={styles.modalRight}>
                    <div className={styles.codeLabel}>Code Preview:</div>
                    <div className={styles.codeEditorContainer}>
                      <CodeEditor
                        mode="python"
                        codeToDisplay={getCodePreview(selected)}
                        width="100%"
                        height="250px"
                        fontSize={14}
                        readOnly={true}
                        setOptions={{
                          enableBasicAutocompletion: false,
                          enableLiveAutocompletion: false,
                          enableSnippets: false,
                          showLineNumbers: true,
                          tabSize: 4,
                          useWorker: false,
                          wrap: false,
                        }}
                        style={{
                          fontFamily: "Consolas, Monaco, 'Courier New', monospace",
                        }}
                      />
                    </div>
                  </div>
                )}
              </div>
            </>
          )}
        </Modal>

        {/* Zoom Popup for Description */}
        {zoomPopup.open && (
          <ZoomPopup title={zoomPopup.title} content={zoomPopup.content} type="text" readOnly={true} onClose={() => setZoomPopup({ open: false, title: "", content: "" })} />
        )}
      </div>
    </>
  );
}

function getCodePreview(s) {
  const type = String(s?.type || "").toUpperCase();
  const raw = s?.raw || s || {};
  if (type === "REMOTE") {
    return "# No code available for this server.";
  }

  const codeCandidates = [raw?.mcp_config?.args?.[1], raw?.mcp_file?.code_content, raw?.mcp_config?.file?.content, raw?.file?.content, raw?.code_content, raw?.code, raw?.script];

  for (const c of codeCandidates) {
    if (typeof c === "string" && c.trim().length > 0) return c;
  }

  // if raw contains a file-like object, pretty-print it
  if (raw && typeof raw === "object") {
    const fileLike = raw?.mcp_config?.file || raw?.mcp_file || raw?.file || raw?.mcp_config;
    if (fileLike && typeof fileLike === "object") {
      try {
        return JSON.stringify(fileLike, null, 2);
      } catch (e) {
        return String(fileLike);
      }
    }
  }

  return "# No code available for this server.";
}
