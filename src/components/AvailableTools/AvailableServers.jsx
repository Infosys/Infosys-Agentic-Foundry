import { useMemo, useState, useEffect, useCallback, useRef } from "react";
import SubHeader from "../commonComponents/SubHeader.jsx";
import styles from "../../css_modules/AvailableServers.module.css";
import { useMcpServerService } from "../../services/serverService";
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from "../../Hooks/MessageContext";
import Loader from "../commonComponents/Loader.jsx";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal";
import { useAuth } from "../../context/AuthContext";
import AddServer from "../AgentOnboard/AddServer.jsx";
import FilterModal from "../commonComponents/FilterModal.jsx";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import { useToolsAgentsService } from "../../services/toolService.js";
import { debounce } from "lodash";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import CodeEditor from "../commonComponents/CodeEditor.jsx";

export default function AvailableServers(props) {
  const { getLiveToolDetails, deleteServer, getServersSearchByPageLimit } = useMcpServerService();
  const { calculateDivs } = useToolsAgentsService();
  // State for live tool details
  const [liveToolDetails, setLiveToolDetails] = useState([]);
  const [loadingTools, setLoadingTools] = useState(false);
  const [loading, setLoading] = useState(false);
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
  const [showAddServerModal, setShowAddServerModal] = useState(false);
  const [editServerData, setEditServerData] = useState(null);
  const pageRef = useRef(1);
  const serverListContainerRef = useRef(null);
  const isLoadingRef = useRef(false);
  const [deleteClickedId, setDeleteClickedId] = useState(null);
  const [emailId, setEmailId] = useState("");
  const [tags, setTags] = useState([]);
  const { fetchData } = useFetch();
  const hasLoadedTagsOnce = useRef(false);

  const { handleError } = useErrorHandler();
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
      type = "EXTERNAL";
    } else if (hasCode) {
      type = "LOCAL";
    } else if (hasUrl) {
      type = "REMOTE";
    } else {
      type = ((raw.mcp_type || raw.type || "") + "").toUpperCase() || "UNKNOWN";
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
  const handleSearch = async (searchValue, divsCount, pageNumber, tagsToUse = null) => {
    setSearchTerm(searchValue || "");
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    setLoading(true);

    try {
      // Use provided tagsToUse or fall back to selectedFilterTags state
      const tagsForSearch = tagsToUse !== null ? tagsToUse : selectedFilterTags;
      const response = await getServersSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: searchValue ? searchValue : "",
        tags: tagsForSearch?.length > 0 ? tagsForSearch : undefined,
      });

      // Setting the total count from API response
      setTotalServersCount(response.total_count || 0);

      const dataToSearch = sanitizeServersResponse(response.details || response);
      // if (tagsForSearch?.length > 0) {
      //   dataToSearch = dataToSearch.filter((item) => {
      //     const typeFilters = tagsForSearch.filter((t) => t === "LOCAL" || t === "REMOTE");
      //     const tagFilters = tagsForSearch.filter((t) => t !== "LOCAL" && t !== "REMOTE");
      //     const mapped = mapServerData(item);
      //     const typeMatch = typeFilters.length === 0 || typeFilters.includes(String(mapped.type).toUpperCase());
      //     const tagMatch = tagFilters.length === 0 || (Array.isArray(mapped.tags) && mapped.tags.some((tag) => tagFilters.includes(tag)));
      //     return typeMatch && tagMatch;
      //   });
      // }
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
      return getServersDataWithTags(pageNumber, divsCount, selectedFilterTags);
    },
    [getServersSearchByPageLimit, mapServerData, selectedFilterTags]
  );
  const clearSearch = () => {
    setSearchTerm("");
    setSelectedFilterTags([]);
    setVisibleData([]);
    setHasMore(true);
    setTimeout(() => {
      // Trigger fetchServersData with no search term (reset to first page)
      const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
      pageRef.current = 1;
      getServersData(1, divsCount);
    }, 500);
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
      } catch (e) {}
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
      setLoading(true);
      let newData = [];

      if (searchTerm.trim()) {
        // Load more search results
        const response = await getServersSearchByPageLimit({
          page: nextPage,
          limit: divsCount,
          search: searchTerm,
          tags: selectedFilterTags?.length > 0 ? selectedFilterTags : undefined,
        });

        // Update total count if provided in response (though it should be the same)
        if (response.total_count !== undefined) {
          setTotalServersCount(response.total_count);
        }

        let initialData = sanitizeServersResponse(response.details || response);

        if (selectedFilterTags?.length > 0) {
          initialData = initialData.filter((item) => {
            const typeFilters = selectedFilterTags.filter((t) => t === "LOCAL" || t === "REMOTE" || t === "EXTERNAL");
            const tagFilters = selectedFilterTags.filter((t) => t !== "LOCAL" && t !== "REMOTE" && t !== "EXTERNAL");
            const mapped = mapServerData(item);
            const typeMatch = typeFilters.length === 0 || typeFilters.includes(String(mapped.type).toUpperCase());
            const tagMatch = tagFilters.length === 0 || (Array.isArray(mapped.tags) && mapped.tags.some((tag) => tagFilters.includes(tag)));
            return typeMatch && tagMatch;
          });
        }
        newData = initialData.map(mapServerData);
      } else {
        // Load more regular data
        const response = await getServersSearchByPageLimit({
          page: nextPage,
          limit: divsCount,
          search: "",
          tags: selectedFilterTags?.length > 0 ? selectedFilterTags : undefined,
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
      setLoading(false);
      isLoadingRef.current = false;
    }
  }, [loading, hasMore, searchTerm, selectedFilterTags, getServersSearchByPageLimit, mapServerData, calculateDivs]);
  useEffect(() => {
    const container = serverListContainerRef?.current;
    if (!container) return;

    // Function to check if we need to load more data on scroll
    const checkAndLoadMore = () => {
      const scrollTop = container.scrollTop;
      const scrollHeight = container.scrollHeight;
      const clientHeight = container.clientHeight;

      // Check if user has scrolled near the bottom (within 50px for better detection)
      if (scrollTop + clientHeight >= scrollHeight - 50 && !loading && !isLoadingRef.current && hasMore) {
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
  }, [hasMore, loading, handleScrollLoadMore]);

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
  const handleDeleteClick = (server) => {
    const loggedInUserEmail = Cookies.get("email");
    const userName = Cookies.get("userName");
    if (userName === "Guest") {
      setEmailId(server?.created_by || "");
    } else {
      setEmailId(loggedInUserEmail || "");
    }
    setDeleteClickedId(server.id);
  };

  const handleCancelDelete = () => {
    setDeleteClickedId(null);
    setEmailId("");
  };

  const handleDeleteConfirm = async (id, server) => {
    // Always attempt the delete API call and let the server enforce permissions.
    const role = Cookies.get("role") || "";
    const loggedInUserEmail = (Cookies.get("email") || emailId || "").trim();
    const isAdmin = (role || "").toLowerCase() === "admin";
    const data = { user_email_id: loggedInUserEmail, is_admin: isAdmin };

    try {
      const response = await deleteServer(data, id);
      if (response?.is_delete) {
        // Refresh the server list after delete
        const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
        getServersData(1, divsCount);
        addMessage(response?.message, "success");
        setShowPopup(true);
        setDeleteClickedId(null);
        setEmailId("");
      } else {
        // Handle error response properly - check for various error message formats
        let errorMessage = "No response received. Please try again.";

        if (response?.message) {
          errorMessage = response.message;
        }else if (response?.detail) {
          errorMessage = response.detail;
        } else if (typeof response === "string") {
          errorMessage = response;
        }

        addMessage(errorMessage, "error");
        // setErrorMessage(errorMessage);
      }
    } catch (err) {
      // Better error handling for network errors and unexpected failures
      let errorMessage = "Failed deleting server";

      if (err?.response?.data?.detail) {
        errorMessage = err.response.data.detail;
      } else if (err?.response?.data?.message) {
        errorMessage = err.response.data.message;
      } else if (err?.message) {
        errorMessage = err.message;
      } else if (typeof err === "string") {
        errorMessage = err;
      }

      addMessage(errorMessage, "error");
      // setErrorMessage(errorMessage);
    }
  };
  const { addMessage, setShowPopup } = useMessage();
  const { logout } = useAuth();
  const [deleteModal, setDeleteModal] = useState(false);
  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  useEffect(() => {
    const loggedInUserEmail = Cookies.get("email");
    const userName = Cookies.get("userName");
    if (userName === "Guest") setEmailId("");
    else setEmailId(loggedInUserEmail);
  }, []);

  const onSettingClick = () => {
    setFilterModal(true);
  }; // Explicit handlers for SubHeader refresh/clear (mirror AvailableTools)

  const handleRefreshClick = async () => {
    try {
      setSearchTerm("");
      setSelectedFilterTags([]);
      setServers([]);
      setVisibleData([]);
      setHasMore(true);
      pageRef.current = 1;
      const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
      // Call getServersDataWithTags with explicitly empty tags to match tools implementation
      await getServersDataWithTags(1, divsCount, []);
    } catch (e) {
      // swallow
    }
  };

  const handleFilterApply = async (selectedTagsParam) => {
    setSelectedFilterTags(selectedTagsParam || []);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    // Trigger new API call with selected tags - pass selectedTagsParam directly
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
    if (searchTerm.trim()) {
      // If there's a search term, use handleSearch with current search and new tags
      await handleSearch(searchTerm, divsCount, 1, selectedTagsParam);
    } else {
      // No search term, fetch data with tag filter - pass selectedTagsParam directly
      await getServersDataWithTags(1, divsCount, selectedTagsParam);
    }
  };

  const getServersDataWithTags = async (pageNumber, divsCount, tagsToUse) => {
    if (isLoadingRef.current) return []; // Prevent multiple simultaneous calls
    isLoadingRef.current = true;
    setLoading(true);
    try {
      // Use the new API endpoint for paginated servers with tag filtering
      const response = await getServersSearchByPageLimit({
        page: pageNumber,
        limit: divsCount,
        search: searchTerm,
        tags: tagsToUse?.length > 0 ? tagsToUse : undefined,
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

  return (
    <>
      <div className={styles.container}>
        <div className={styles.subHeaderContainer}>
          <SubHeader
            heading={""}
            activeTab={"servers"}
            onSearch={(value) => handleSearch(value, calculateDivs(serverListContainerRef, 200, 140, 16), 1)}
            searchValue={searchTerm}
            clearSearch={clearSearch}
            handleRefresh={handleRefreshClick}
            onPlusClick={handlePlusClick}
            onSettingClick={onSettingClick}
            selectedTags={selectedFilterTags}
            reverseButtons={true}
          />
        </div>

        {loading && <Loader />}
        {/* Search/filter info badges similar to AvailableTools */}
        <div style={{ display: "flex", gap: "12px", marginBottom: "3px", width: "100%", overflow: "hidden" }}>
          {/* Display searched server text if searchTerm exists and results are found */}
          {searchTerm.trim() && visible.length > 0 && (
            <div className={styles.searchedToolText}>
              <p>
                Search term:{" "}
                <span className={`boldText ${styles.filterOrSearchText}`} title={searchTerm}>
                  {searchTerm}
                </span>
              </p>
            </div>
          )}

          {/* Display filtered servers text if filters are applied */}
          {selectedFilterTags.length > 0 && visible.length > 0 && (
            <div className={styles.filteredToolText}>
              <p>
                Selected tags:{" "}
                <span className={`boldText ${styles.filterOrSearchText}`} title={selectedFilterTags.join(", ")}>
                  {selectedFilterTags.join(", ")}
                </span>
              </p>
            </div>
          )}

          {/* Display "No Tools Found" messages when search or filters applied but no results */}
          {searchTerm.trim() && visibleData.length < 1 && !loading && (
            <div className={styles.filteredToolText}>
              <p>
                No servers found for:{" "}
                <span className={`boldText ${styles.filterOrSearchText}`} title={searchTerm}>
                  {searchTerm}
                </span>
              </p>
            </div>
          )}

          {selectedFilterTags.length > 0 && visibleData.length < 1 && !loading && (
            <div className={styles.searchedToolText}>
              <p>
                No servers found for:{" "}
                <span className={`boldText ${styles.filterOrSearchText}`} title={selectedFilterTags.join(", ")}>
                  {selectedFilterTags.join(", ")}
                </span>
              </p>
            </div>
          )}
        </div>

        {/* Conditional summary line only when we have visible data */}
        {visible.length > 0 && (
          <div className={styles.summaryLine}>
            <strong>{visible.length}</strong> servers (of {totalServersCount} total)
          </div>
        )}
        <div
          ref={serverListContainerRef}
          className={`${styles.serverGrid} ${selectedFilterTags.length > 0 || searchTerm.trim() ? styles.tagOrSerachIsOnServer : ""}`}
          aria-label="Servers list scrollable container">
          {visible.map((s) => (
            <div
              key={s.id}
              className={styles.serverCard}
              style={{
                width: "200px",
                minHeight: "140px",
                height: "140px",
                maxHeight: "160px",
                padding: "11px",
                color: "white",
                position: "relative",
                backgroundColor: "#3d4359",
                boxShadow: "5px 15px 6px #00000029",
                borderRadius: "4px",
                cursor: "pointer",
                display: "flex",
                flexDirection: "column",
                justifyContent: "space-between",
                fontFamily: "Segoe UI",
                transition: "transform 0.2s ease, box-shadow 0.2s ease",
              }}
              onMouseOver={(e) => {
                e.currentTarget.style.transform = "translateY(-3px)";
                e.currentTarget.style.boxShadow = "5px 18px 10px #00000029";
              }}
              onMouseOut={(e) => {
                e.currentTarget.style.transform = "translateY(0)";
                e.currentTarget.style.boxShadow = "5px 15px 6px #00000029";
              }}>
              <div style={{ flex: 1 }}>
                <span
                  style={{
                    fontSize: "16px",
                    lineHeight: "14px",
                    fontWeight: 600,
                    letterSpacing: "-0.8px",
                    wordBreak: "break-word",
                    textTransform: "uppercase",
                    marginBottom: "4px",
                    maxHeight: "35px",
                    color: "#fff",
                  }}>
                  {s.name}
                </span>
                <div style={{ width: "28px", height: "2px", backgroundColor: "#0071b3", marginTop: "5px" }} />{" "}
                <div style={{ marginTop: "5px" }}>
                  <div style={{ font: "normal normal 600 12px/16px Segoe UI", letterSpacing: "0px", textTransform: "uppercase", opacity: 1 }}></div>
                  <div
                    title={s.description || "No description"}
                    style={{
                      font: "normal normal 400 12px/16px Segoe UI",
                      letterSpacing: "-0.24px",
                      color: "#ffffff",
                      wordBreak: "break-word",
                      whiteSpace: "pre-line",
                      maxHeight: "32px",
                      marginBottom: "30px",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      display: "-webkit-box",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                    }}>
                    {s.description || "No description"}
                  </div>
                </div>
              </div>
              <div style={{ position: "absolute", left: "2px", bottom: "10px", display: "flex", alignItems: "center", gap: "8px" }}>
                <span className={styles.typePill} style={{ fontSize: "12px", padding: "4px 10px", background: "#6b7280", color: "#fff", borderRadius: "8px" }}>
                  {s.type}
                </span>
              </div>
              <div className={styles.serverCardBtnWrapper} style={{ position: "absolute", right: "10px", bottom: "10px", display: "flex", gap: "8px" }}>
                <button
                  type="button"
                  style={{
                    background: "#007ac0",
                    boxShadow: "0px 4px 4px #00000029",
                    borderRadius: "3px",
                    width: "30px",
                    height: "24px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    border: "none",
                  }}
                  title="View details"
                  aria-label={`View ${s.name}`}
                  onClick={() => {
                    setSelected(s);
                    setOpen(true);
                  }}>
                  <SVGIcons icon="eye" width={20} height={16} fill="#fff" />
                </button>
                <button
                  type="button"
                  style={{
                    background: "#6a2020",
                    boxShadow: "0px 4px 4px #00000029",
                    borderRadius: "3px",
                    width: "30px",
                    height: "24px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    border: "none",
                  }}
                  title="Delete"
                  aria-label={`Delete ${s.name}`}
                  onClick={() => handleDeleteClick(s)}>
                  <SVGIcons icon="recycle-bin" width={20} height={16} fill="#fff" />
                </button>
                <button
                  type="button"
                  style={{
                    background: "#007ac0",
                    boxShadow: "0px 4px 4px #00000029",
                    borderRadius: "3px",
                    width: "30px",
                    height: "24px",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    border: "none",
                  }}
                  title="Edit"
                  aria-label={`Edit ${s.name}`}
                  onClick={() => {
                    // Always pass raw if available, fallback to s for legacy/local/remote
                    setEditServerData(s.raw && Object.keys(s.raw).length ? s.raw : s);
                    setShowAddServerModal(true);
                  }}>
                  <SVGIcons icon="fa-solid fa-pen" width={16} height={16} fill="#fff" />
                </button>
              </div>{" "}
              {deleteClickedId === s.id && (
                <div className={styles.cardDeleteOverlay}>
                  <button className={styles.overlayClose} onClick={handleCancelDelete} aria-label="Close delete">
                    <SVGIcons icon="fa-xmark" fill="#3D4359" />
                  </button>
                  <input className={styles.emailIdInput} type="text" value={s.created_by || ""} disabled />
                  <div className={styles.actionInfo}>
                    <span className={styles.warningIcon}>
                      <SVGIcons icon="warnings" width={16} height={16} fill="#B8860B" />
                    </span>
                    creator / admin can perform this action
                  </div>
                  <div className={styles.deleteBtnContainer}>
                    <button type="button" className={styles.confirmDeleteBtn} onClick={() => handleDeleteConfirm(s.tool_id || s.id, s)}>
                      DELETE <SVGIcons icon="fa-circle-xmark" />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}

          {/* Loading indicator for infinite scroll */}
          {loading && visible.length > 0 && (
            <div
              style={{
                width: "100%",
                padding: "20px",
                textAlign: "center",
                color: "#ffffff",
                fontSize: "14px",
              }}>
              Loading more servers...
            </div>
          )}

          {/* End of list indicator */}
          {/* {!hasMore && visible.length > 0 && (
            <div
              style={{
                width: "100%",
                padding: "20px",
                textAlign: "center",
                color: "#888888",
                fontSize: "14px",
                fontStyle: "italic",
              }}>
              No more servers to load
            </div>
          )} */}
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

        {open && selected && (
          <div className={styles.modalOverlay} onClick={() => setOpen(false)}>
            <div className={`${styles.modal} ${String(selected.type || "").toUpperCase() === "LOCAL" ? styles.modalWide : ""}`} onClick={(e) => e.stopPropagation()}>
              <button className={styles.closeBtn} onClick={() => setOpen(false)}>
                ×
              </button>
              <div className={styles.modalBody} style={String(selected.type || "").toUpperCase() === "REMOTE" ? { flexDirection: "column" } : undefined}>
                <div className={styles.modalLeft} style={String(selected.type || "").toUpperCase() === "REMOTE" ? { flex: "1 1 100%", maxWidth: "100%" } : undefined}>
                  <h2 className={styles.modalTitle} style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
                    {selected.name}
                    {String(selected.type || "").toUpperCase() === "REMOTE" && (
                      <span style={{ display: "inline-flex", alignItems: "center", fontSize: 14, fontWeight: 600 }}>
                        {loadingTools ? (
                          <span style={{ color: "#374151", fontWeight: 500 }}>Checking...</span>
                        ) : (
                          (() => {
                            const remoteCount =
                              Array.isArray(liveToolDetails) && liveToolDetails.length > 0 ? liveToolDetails.length : Array.isArray(selected.tools) ? selected.tools.length : 0;
                            const isActive = remoteCount > 0;
                            return (
                              <span
                                aria-label={isActive ? "Server Active" : "Server Inactive"}
                                style={{
                                  display: "inline-flex",
                                  alignItems: "center",
                                  background: isActive ? "#dcfce7" : "#fee2e2",
                                  color: isActive ? "#166534" : "#991b1b",
                                  padding: "4px 10px",
                                  borderRadius: 20,
                                  lineHeight: 1,
                                  boxShadow: "0 0 0 1px rgba(0,0,0,0.05)",
                                }}>
                                <span
                                  style={{
                                    width: 10,
                                    height: 10,
                                    borderRadius: "50%",
                                    backgroundColor: isActive ? "#16a34a" : "#dc2626",
                                    marginRight: 6,
                                    boxShadow: isActive ? "0 0 4px #16a34a" : "0 0 4px #dc2626",
                                  }}
                                />
                                {isActive ? "Active" : "Inactive"}
                              </span>
                            );
                          })()
                        )}
                      </span>
                    )}
                  </h2>

                  <div className={styles.infoGrid}>
                    <div className={styles.infoCol}>
                      <div className={styles.infoRow}>
                        <strong>Description:</strong> {selected.description}
                      </div>
                      <div className={styles.infoRow}>
                        <strong>Created by:</strong> {selected.created_by || "-"}
                      </div>
                      {(String(selected.type || "").toUpperCase() === "REMOTE" || selected.endpoint) && (
                        <div className={styles.infoRow}>
                          <strong>Endpoint:</strong>{" "}
                          {selected.endpoint ? (
                            <a href={selected.endpoint} target="_blank" rel="noreferrer">
                              {selected.endpoint}
                            </a>
                          ) : (
                            "—"
                          )}
                        </div>
                      )}
                      <div className={styles.infoRow}>
                        <strong>Type:</strong> {selected.type}
                      </div>
                      {String(selected.type || "").toUpperCase() === "EXTERNAL" && selected?.raw?.mcp_config?.args?.[1] && (
                        <div className={styles.infoRow}>
                          <strong>Module:</strong> {selected.raw.mcp_config.args[1]}
                        </div>
                      )}
                      {(() => {
                        if (String(selected.type || "").toUpperCase() === "REMOTE") {
                          // Show liveToolDetails if available, else fallback to selected.tools
                          if (loadingTools) {
                            return (
                              <div className={styles.infoRow}>
                                <strong>Tools:</strong> <span style={{ marginLeft: 8 }}>Loading...</span>
                              </div>
                            );
                          }
                          if (Array.isArray(liveToolDetails) && liveToolDetails.length > 0) {
                            return (
                              <div className={styles.infoRow}>
                                <strong>Tools:</strong> {liveToolDetails.length}
                                <ul style={{ margin: "6px 0 0 0", paddingLeft: 18, fontSize: "15px", color: "#111", fontWeight: 500 }}>
                                  {liveToolDetails.map((tool, idx) => (
                                    <li key={tool.name || tool.tool_name || tool.id || idx}>
                                      <strong>{tool.name || tool.tool_name || `Tool ${idx + 1}`}</strong>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            );
                          }
                          const count = Array.isArray(selected.tools) ? selected.tools.length : 0;
                          if (count > 0) {
                            return (
                              <div className={styles.infoRow}>
                                <strong>Tools:</strong> {count}
                                <ul style={{ margin: "6px 0 0 0", paddingLeft: 18, fontSize: "15px", color: "#111", fontWeight: 500 }}>
                                  {selected.tools.map((tool, idx) => (
                                    <li key={tool.name || tool.tool_name || tool.id || idx}>
                                      <strong>{tool.name || tool.tool_name || `Tool ${idx + 1}`}</strong>
                                    </li>
                                  ))}
                                </ul>
                              </div>
                            );
                          }
                          return (
                            <div className={styles.infoRow}>
                              <strong>Tools:</strong> <span style={{ marginLeft: 8 }}>No tools found for this REMOTE server.</span>
                            </div>
                          );
                        } else if (loadingTools) {
                          return (
                            <div className={styles.infoRow}>
                              <strong>Tools:</strong> <span style={{ marginLeft: 8 }}>Loading...</span>
                            </div>
                          );
                        } else if (liveToolDetails.length > 0) {
                          return (
                            <div className={styles.infoRow}>
                              <strong>Tools:</strong> {liveToolDetails.length}
                              <ul style={{ margin: "6px 0 0 0", paddingLeft: 18, fontSize: "15px", color: "#111", fontWeight: 500 }}>
                                {liveToolDetails.map((tool, idx) => (
                                  <li key={tool.name || tool.tool_name || tool.id || idx}>
                                    <strong>{tool.name || tool.tool_name || `Tool ${idx + 1}`}</strong>
                                  </li>
                                ))}
                              </ul>
                            </div>
                          );
                        } else {
                          return (
                            <div className={styles.infoRow}>
                              <strong>Tools:</strong> 0
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
                        theme="monokai"
                        isDarkTheme={true}
                        value={getCodePreview(selected)}
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
            </div>
          </div>
        )}

        <FilterModal
          show={filterModal}
          onClose={() => setFilterModal(false)}
          tags={tags}
          handleFilter={handleFilterApply}
          selectedTags={selectedFilterTags}
          showfilterHeader={"Filter Servers by Tags"}
          filterTypes="servers"
        />

        <DeleteModal show={deleteModal} onClose={() => setDeleteModal(false)}>
          <p>You are not authorized to delete this server. Please login with registered email.</p>
          <div className={styles.buttonContainer}>
            <button onClick={(e) => handleLoginButton(e)} className={styles.loginBtn}>
              Login
            </button>
            <button onClick={() => setDeleteModal(false)} className={styles.cancelBtn}>
              Cancel
            </button>
          </div>
        </DeleteModal>

        {/* AddServer modal for add/edit - OUTSIDE main container for full overlay */}
        {showAddServerModal &&
          (editServerData ? (
            <AddServer
              editMode={true}
              serverData={editServerData}
              setRefreshPaginated={() => {
                /* refresh handled by AddServer:RefreshRequested */
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
              setRefreshPaginated={() => {
                /* refresh handled by AddServer:RefreshRequested */
              }}
              onClose={() => {
                setShowAddServerModal(false);
                setEditServerData(null);
              }}
            />
          ))}
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
