import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import SubHeader from "../commonComponents/SubHeader.jsx";
import styles from "../../css_modules/AvailableServers.module.css";
import { useMcpServerService } from "../../services/serverService";
import { usePermissions } from "../../context/PermissionsContext";
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";
import { getRoleFromToken, getEmailFromToken, getUserNameFromToken } from "../../utils/jwtUtils";
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
import ShareModal from "../commonComponents/ShareModal/ShareModal.jsx";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import { useActiveNavClick } from "../../events/navigationEvents";
import { Modal } from "../commonComponents/Modal";
import ImportModal from "./ImportModal.jsx";
import useMultiSelect from "../../Hooks/useMultiSelect.js";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";

// ========================================
// Health Status Cache Configuration
// ========================================
const HEALTH_CACHE_TTL_MS = 5 * 60 * 1000; // 5 minutes TTL
const HEALTH_CHECK_DEBOUNCE_MS = 500; // 500ms debounce after pagination

// In-memory cache for health status (persists across re-renders within session)
const healthStatusCache = new Map();

/**
 * Get cached health status if not expired
 * @param {string} serverId - Server ID
 * @returns {Object|null} Cached status or null if expired/missing
 */
const getCachedHealthStatus = (serverId) => {
  const cached = healthStatusCache.get(serverId);
  if (cached && Date.now() - cached.timestamp < HEALTH_CACHE_TTL_MS) {
    return cached.data;
  }
  // Clean up expired entry
  if (cached) healthStatusCache.delete(serverId);
  return null;
};

/**
 * Set health status in cache with timestamp
 * @param {string} serverId - Server ID
 * @param {Object} status - Health status object
 */
const setCachedHealthStatus = (serverId, status) => {
  healthStatusCache.set(serverId, {
    data: status,
    timestamp: Date.now(),
  });
};

export default function AvailableServers(props) {
  const { getLiveToolDetails, deleteServer, getServersSearchByPageLimit, getServerById, checkServerHealth, exportServers, importServers } = useMcpServerService();
  const { calculateDivs } = useToolsAgentsService();
  // State for live tool details
  const [liveToolDetails, setLiveToolDetails] = useState([]);
  const [loadingTools, setLoadingTools] = useState(false);
  const [loading, setLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  // ========================================
  // Health Status State Management
  // ========================================
  // Map of serverId -> { status: 'healthy' | 'unhealthy' | 'unknown' | 'checking', toolCount: number }
  const [healthStatusMap, setHealthStatusMap] = useState({});
  // Ref to track which servers are currently being checked (to avoid duplicate calls)
  const healthCheckInProgressRef = useRef(new Set());
  // Handle server card click - fetch latest data from API before editing
  const handleServerCardClick = useCallback(async (item) => {
    const serverId = item?.raw?.tool_id || item?.id || item?.tool_id;
    if (!serverId) {
      setEditServerData(item.raw && Object.keys(item.raw).length ? item.raw : item);
      setShowAddServerModal(true);
      return;
    }
    setLoading(true);
    try {
      const response = await getServerById(serverId);
      // Handle both array and single object response
      const serverData = Array.isArray(response) ? response[0] : response;

      if (serverData && typeof serverData === "object" && !serverData.error) {
        setEditServerData(serverData);
      } else {
        // Fallback to local data if API fails
        setEditServerData(item.raw && Object.keys(item.raw).length ? item.raw : item);
      }
      setShowAddServerModal(true);
    } catch (error) {
      console.error("Error fetching server details:", error);
      // Fallback to local data on error
      setEditServerData(item.raw && Object.keys(item.raw).length ? item.raw : item);
      setShowAddServerModal(true);
    } finally {
      setLoading(false);
    }
  }, [getServerById]);

  // Handle eye icon click - fetch latest data from API before viewing
  const handleViewServerClick = useCallback(async (item) => {
    const serverId = item?.raw?.tool_id || item?.id || item?.tool_id;
    if (!serverId) {
      setSelected(item);
      setOpen(true);
      return;
    }
    setLoading(true);
    try {
      const response = await getServerById(serverId);
      // Handle both array and single object response
      const serverData = Array.isArray(response) ? response[0] : response;

      if (serverData && typeof serverData === "object" && !serverData.error) {
        // Map the API response to match expected format
        const raw = serverData;
        const hasCode = Boolean(raw?.mcp_config?.args?.[1] || raw?.mcp_file?.code_content || raw?.code_content || raw?.code || raw?.script);
        const hasUrl = Boolean(raw?.mcp_config?.url || raw?.mcp_url || raw?.endpoint || raw?.mcp_config?.mcp_url || raw?.mcp_config?.endpoint);

        let type;
        if (raw.mcp_type === "module") {
          type = "External";
        } else if (raw.mcp_type === "file" || hasCode) {
          type = "Local";
        } else if (raw.mcp_type === "url" || hasUrl) {
          type = "Remote";
        } else {
          const rawType = String(raw.mcp_type || raw.type || "");
          type = rawType ? rawType.charAt(0).toUpperCase() + rawType.slice(1).toLowerCase() : "Unknown";
        }

        const endpoint = raw.mcp_url || (raw.mcp_config && (raw.mcp_config.url || raw.mcp_config.mcp_url || raw.mcp_config.endpoint)) || raw.endpoint || "";

        const mappedData = {
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
        setSelected(mappedData);
      } else {
        setSelected(item);
      }
      setOpen(true);
    } catch (error) {
      console.error("Error fetching server details:", error);
      setSelected(item);
      setOpen(true);
    } finally {
      setLoading(false);
    }
  }, [getServerById]);

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

  // Share modal state
  const [shareModalData, setShareModalData] = useState(null);
  const [showShareModal, setShowShareModal] = useState(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const pageRef = useRef(1);
  const serverListContainerRef = useRef(null);
  const isLoadingRef = useRef(false);
  const [tags, setTags] = useState([]);
  const { fetchData, deleteData } = useFetch();
  const hasLoadedTagsOnce = useRef(false);

  // Copy and Zoom popup state
  const [copiedStates, setCopiedStates] = useState({});
  const [zoomPopup, setZoomPopup] = useState({ open: false, title: "", content: "" });

  // Created By dropdown state
  const [createdBy, setCreatedBy] = useState("All");
  const loggedInUserEmail = getEmailFromToken();
  const userName = getUserNameFromToken();

  const { handleError } = useErrorHandler();

  // Permission checks for CRUD operations on servers (using mcp_servers permissions)
  const { hasPermission, loading: permissionsLoading } = usePermissions();
  const canReadServers = typeof hasPermission === "function" ? hasPermission("read_access.mcp_servers") : false;
  const canAddServers = typeof hasPermission === "function" ? hasPermission("add_access.mcp_servers") : false;
  const canUpdateServers = typeof hasPermission === "function" ? hasPermission("update_access.mcp_servers") : false;
  const canDeleteServers = typeof hasPermission === "function" ? hasPermission("delete_access.mcp_servers") : false;
  const isAdmin = getRoleFromToken().toLowerCase() === "admin";

  // Multi-select delete state
  const {
    selectedIds: multiSelectIds,
    selectedCount: multiSelectCount,
    isAllSelected,
    isPartiallySelected,
    handleSelectionChange: handleMultiSelectChange,
    handleSelectAll,
    clearSelection: clearMultiSelection,
  } = useMultiSelect({ data: visibleData, idKey: "id" });
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false);
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);

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
    } else if (raw.mcp_type === "file" || hasCode) {
      type = "Local";
    } else if (raw.mcp_type === "url" || hasUrl) {
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

  // ========================================
  // Health Check Logic for Remote Servers
  // ========================================

  /**
   * Check health status for a single remote server
   * Uses cache to avoid redundant API calls
   */
  const checkSingleServerHealth = useCallback(
    async (server) => {
      const serverId = server.id;
      if (!serverId) return;

      // Check cache first
      const cached = getCachedHealthStatus(serverId);
      if (cached) {
        setHealthStatusMap((prev) => ({
          ...prev,
          [serverId]: cached,
        }));
        return;
      }

      // Skip if already checking
      if (healthCheckInProgressRef.current.has(serverId)) return;
      healthCheckInProgressRef.current.add(serverId);

      // Set checking state
      setHealthStatusMap((prev) => ({
        ...prev,
        [serverId]: { status: "checking", toolCount: 0 },
      }));

      try {
        const result = await checkServerHealth(serverId);
        const healthStatus = {
          status: result.status,
          toolCount: result.toolCount,
        };

        // Update state and cache
        setHealthStatusMap((prev) => ({
          ...prev,
          [serverId]: healthStatus,
        }));
        setCachedHealthStatus(serverId, healthStatus);
      } catch (error) {
        // On error, mark as unknown
        const unknownStatus = { status: "unknown", toolCount: 0 };
        setHealthStatusMap((prev) => ({
          ...prev,
          [serverId]: unknownStatus,
        }));
        setCachedHealthStatus(serverId, unknownStatus);
      } finally {
        healthCheckInProgressRef.current.delete(serverId);
      }
    },
    [checkServerHealth]
  );

  /**
   * Check health for all visible remote servers
   * Runs sequentially to avoid overwhelming the backend (MCP connections can be slow)
   */
  const checkRemoteServersHealth = useCallback(
    async (servers) => {
      // Filter only remote (URL-based) servers
      const remoteServers = servers.filter(
        (server) => server.type === "Remote" || server.raw?.mcp_type === "url"
      );

      if (remoteServers.length === 0) return;

      // Process servers sequentially (one at a time) since MCP connections can be slow
      // and parallel requests can overwhelm the backend
      for (const server of remoteServers) {
        await checkSingleServerHealth(server);
      }
    },
    [checkSingleServerHealth]
  );

  /**
   * Debounced health check trigger - runs 1 second after pagination settles
   */
  const debouncedHealthCheck = useMemo(
    () =>
      debounce((servers) => {
        checkRemoteServersHealth(servers);
      }, 1000), // Increased debounce to 1 second
    [checkRemoteServersHealth]
  );

  // Trigger health checks when visible data changes
  useEffect(() => {
    if (visibleData.length > 0 && !loading) {
      debouncedHealthCheck(visibleData);
    }

    // Cleanup debounce on unmount
    return () => {
      if (debouncedHealthCheck.cancel) {
        debouncedHealthCheck.cancel();
      }
    };
  }, [visibleData, loading, debouncedHealthCheck]);

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
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : createdByValue === "System" ? "system" : undefined;
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
        // Pass created_by value based on filter selection
        const createdByEmail = createdBy === "Me" ? loggedInUserEmail : createdBy === "System" ? "system" : undefined;
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
      return;
    }

    // Call the delete API directly since Card.jsx already shows confirmation
    const role = getRoleFromToken();
    const loggedInUserEmail = getEmailFromToken().trim();
    const isAdmin = (role || "").toLowerCase() === "admin";
    const data = { user_email_id: loggedInUserEmail, is_admin: isAdmin };

    try {
      const response = await deleteServer(data, serverId);
      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
        const isSuccess = !hasAnyFailure;
        if (isSuccess) {
          const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
          getServersData(1, divsCount);
        }
        if (statusMsg) {
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
        if (isSuccess) setShowPopup(true);
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

  // Bulk delete handler for multi-select — single API call
  const handleBulkDeleteServers = async () => {
    if (multiSelectIds.length === 0) return;
    // Filter out items created by the current user (creator cannot delete own items)
    const currentEmail = (loggedInUserEmail || "").trim().toLowerCase();
    const ownItems = visibleData.filter((item) => multiSelectIds.includes(item.id) && (item.created_by || "").trim().toLowerCase() === currentEmail);
    const deletableIds = multiSelectIds.filter((id) => {
      const item = visibleData.find((d) => d.id === id);
      return !item || (item.created_by || "").trim().toLowerCase() !== currentEmail;
    });
    if (ownItems.length > 0) {
      addMessage(`${ownItems.length} server(s) created by you were skipped. You cannot delete your own servers.`, "error");
    }
    if (deletableIds.length === 0) {
      clearMultiSelection();
      setShowBulkDeleteModal(false);
      return;
    }
    setBulkDeleteLoading(true);
    const role = getRoleFromToken();
    const isAdmin = (role || "").toLowerCase() === "admin";

    try {
      const apiUrl = APIs.MCP_DELETE_TOOLS.replace(/\/$/, "");
      const payload = { tool_ids: deletableIds, is_admin: isAdmin, user_email_id: loggedInUserEmail };
      const response = await deleteData(apiUrl, payload);
      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }
    } catch {
      // silent catch
    }

    clearMultiSelection();
    setShowBulkDeleteModal(false);
    setBulkDeleteLoading(false);
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
    getServersData(1, divsCount);
  };

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
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : createdByValue === "System" ? "system" : undefined;
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

  // Export selected servers as zip
  const handleExportServers = async () => {
    if (multiSelectIds.length === 0) return;
    setExportLoading(true);
    try {
      const blob = await exportServers(multiSelectIds);
      if (!blob) throw new Error("Failed to export servers");
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "servers_export.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      addMessage(`${multiSelectIds.length} server${multiSelectIds.length !== 1 ? "s" : ""} exported successfully!`, "success");
      clearMultiSelection();
    } catch (err) {
      const errorMessage = err?.message || "Export failed";
      addMessage(errorMessage, "error");
    } finally {
      setExportLoading(false);
    }
  };

  // Import servers from zip file
  const handleImportServers = async (zipFile) => {
    setImportLoading(true);
    setShowImportModal(false);
    try {
      const createdByEmail = getEmailFromToken();
      const response = await importServers(zipFile, createdByEmail);
      if (response?.status === "success") {
        const result = response.result || {};
        const imported = result.imported?.length || 0;
        const skipped = result.skipped?.length || 0;
        const failed = result.failed?.length || 0;
        addMessage(
          result.message || `Import complete. ${imported} imported, ${skipped} skipped, ${failed} failed.`,
          failed > 0 && imported === 0 ? "error" : "success"
        );
        if (imported > 0) {
          handleRefreshClick();
        }
      } else {
        addMessage(response?.message || response?.detail || "Import failed", "error");
      }
    } catch (err) {
      const errorMessage = err?.message || err?.detail || "Import failed";
      addMessage(errorMessage, "error");
    } finally {
      setImportLoading(false);
    }
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
            key={editServerData?.tool_id || editServerData?.id || "edit"}
            editMode={true}
            serverData={editServerData}
            readOnly={!canUpdateServers}
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

      {(loading || exportLoading || importLoading) && <Loader />}

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
          tertiaryButtonLabel={canAddServers ? "Export" : undefined}
          onTertiaryButtonClick={canAddServers ? handleExportServers : undefined}
          tertiaryButtonDisabled={multiSelectIds.length === 0 || exportLoading}
          tertiaryButtonTitle={multiSelectIds.length === 0 ? "Select servers to export" : ""}
          quaternaryButtonLabel={canAddServers ? "Import" : undefined}
          onQuaternaryButtonClick={canAddServers ? () => setShowImportModal(true) : undefined}
          quaternaryButtonDisabled={importLoading}
          quaternaryButtonTitle="Import servers from a zip file"
          showSelectAll={canDeleteServers && isAdmin && visibleData.length > 1}
          isAllSelected={isAllSelected}
          isPartiallySelected={isPartiallySelected}
          onSelectAll={handleSelectAll}
          selectedCount={multiSelectCount}
          onDeleteSelected={canDeleteServers && isAdmin ? () => setShowBulkDeleteModal(true) : null}
          deleteSelectedLabel="Delete"
        />

        {/* Conditional summary line only when we have visible data */}
        <SummaryLine visibleCount={visible.length} totalCount={totalServersCount} />
        <div className="listWrapper" ref={serverListContainerRef} aria-label="Servers list scrollable container">
          {visible?.length > 0 && (
            <DisplayCard1
              data={visible}
              onCardClick={(canReadServers || canUpdateServers) ? (name, item) => handleServerCardClick(item) : undefined}
              onButtonClick={(name, item) => handleViewServerClick(item)}
              onEditClick={canUpdateServers ? (item) => handleServerCardClick(item) : undefined}
              onCreateClick={canAddServers ? handlePlusClick : undefined}
              showDeleteButton={false}
              showButton={true}
              showCreateCard={false}
              buttonIcon={<SVGIcons icon="eye" width={16} height={16} />}
              enableComplexDelete={false}
              cardNameKey="name"
              cardDescriptionKey="description"
              cardOwnerKey="created_by"
              cardCategoryKey="type"
              emptyMessage="No servers found"
              contextType="server"
              cardDisabled={!canReadServers && !canUpdateServers}
              healthStatusMap={healthStatusMap}
              hideActions={!canReadServers}
              showCheckbox={canAddServers || canDeleteServers}
              onSelectionChange={(canAddServers || canDeleteServers) ? handleMultiSelectChange : undefined}
              selectedIds={multiSelectIds}
              idKey="id"
              onShareClick={(item) => {
                setShareModalData(item.raw || item);
                setShowShareModal(true);
              }}
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

        <ShareModal
          show={showShareModal}
          onClose={() => setShowShareModal(false)}
          itemData={shareModalData}
          entityType="server"
        />

        {showImportModal && (
          <ImportModal
            type="servers"
            onClose={() => setShowImportModal(false)}
            onImport={handleImportServers}
            loading={importLoading}
          />
        )}
        {showBulkDeleteModal && (
          <ConfirmationModal
            message={`Are you sure you want to delete ${multiSelectCount} selected server(s)? This action cannot be undone.`}
            onConfirm={handleBulkDeleteServers}
            setShowConfirmation={setShowBulkDeleteModal}
          />
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
