import React, { useMemo, useState, useEffect, useCallback, useRef } from "react";
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

  const getTags = useCallback(async () => {
    try {
      const data = await fetchData(APIs.GET_TAGS);
      setTags(data);
    } catch (e) {
      console.error(e);
    }
  }, [fetchData]);

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

    const type = hasCode ? "LOCAL" : hasUrl ? "REMOTE" : ((raw.mcp_type || raw.type || "") + "").toUpperCase() || "UNKNOWN";

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

      let dataToSearch = sanitizeServersResponse(response.details || response);
      if (tagsForSearch?.length > 0) {
        dataToSearch = dataToSearch.filter((item) => {
          const typeFilters = tagsForSearch.filter((t) => t === "LOCAL" || t === "REMOTE");
          const tagFilters = tagsForSearch.filter((t) => t !== "LOCAL" && t !== "REMOTE");
          const mapped = mapServerData(item);
          const typeMatch = typeFilters.length === 0 || typeFilters.includes(String(mapped.type).toUpperCase());
          const tagMatch = tagFilters.length === 0 || (Array.isArray(mapped.tags) && mapped.tags.some((tag) => tagFilters.includes(tag)));
          return typeMatch && tagMatch;
        });
      }
      const mappedData = dataToSearch.map(mapServerData);
      setVisibleData(mappedData);
      setHasMore(dataToSearch.length >= divsCount);
    } catch (error) {
      console.error("Error fetching search results:", error);
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
    setVisibleData([]);
    setHasMore(true);
    // Trigger fetchServersData with no search term (reset to first page)
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
    pageRef.current = 1;
    getServersData(1, divsCount);
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
  const handleScrollLoadMore = useCallback(async () => {
    if (loading || isLoadingRef.current || !hasMore) return; // Prevent multiple calls or if no more data
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);

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

        let dataToSearch = sanitizeServersResponse(response.details || response);
        if (selectedFilterTags?.length > 0) {
          dataToSearch = dataToSearch.filter((item) => {
            const typeFilters = selectedFilterTags.filter((t) => t === "LOCAL" || t === "REMOTE");
            const tagFilters = selectedFilterTags.filter((t) => t !== "LOCAL" && t !== "REMOTE");
            const mapped = mapServerData(item);
            const typeMatch = typeFilters.length === 0 || typeFilters.includes(String(mapped.type).toUpperCase());
            const tagMatch = tagFilters.length === 0 || (Array.isArray(mapped.tags) && mapped.tags.some((tag) => tagFilters.includes(tag)));
            return typeMatch && tagMatch;
          });
        }
        newData = dataToSearch.map(mapServerData);
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
      console.error("Error loading more servers:", error);
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

      const isNearBottom = scrollTop + clientHeight >= scrollHeight - 50;

      // Check if user has scrolled near the bottom (within 50px for better detection)
      if (isNearBottom && !loading && !isLoadingRef.current && hasMore) {
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
    if (open && selected) {
      setLoadingTools(true);
      getLiveToolDetails(selected.id)
        .then((data) => {
          setLiveToolDetails(Array.isArray(data) ? data : []);
        })
        .catch(() => setLiveToolDetails([]))
        .finally(() => setLoadingTools(false));
    } else {
      setLiveToolDetails([]);
      setLoadingTools(false);
    }
  }, [open, selected, getLiveToolDetails]);
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
    const userName = Cookies.get("userName");
    const role = Cookies.get("role");
    if (userName === "Guest") {
      setDeleteModal(true);
      return;
    }
    const loggedInUserEmail = (Cookies.get("email") || emailId || "").trim();
    const creatorEmail = (server?.created_by || "").trim();
    const isAdmin = role?.toLowerCase() === "admin" || role?.toUpperCase() === "ADMIN";

    // Admin can delete any server, non-admin can only delete their own servers
    if (!isAdmin && (!loggedInUserEmail || !creatorEmail || loggedInUserEmail.toLowerCase() !== creatorEmail.toLowerCase())) {
      addMessage("Only creator/admin can delete this server", "error");
      return;
    }

    const data = { user_email_id: loggedInUserEmail, is_admin: isAdmin };

    try {
      const response = await deleteServer(data, id);
      if (response?.is_delete) {
        // Refresh the server list after delete
        const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16);
        getServersData(1, divsCount);
        addMessage("Server has been deleted successfully!", "success");
        setShowPopup(true);
        setDeleteClickedId(null);
        setEmailId("");
      } else {
        // Handle error response properly - check for various error message formats
        let errorMessage = "No response received. Please try again.";

        if (response?.message) {
          errorMessage = response.message;
        } else if (response?.status_message) {
          errorMessage = response.status_message;
        } else if (response?.detail) {
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
      await getServersData(1, divsCount);
    } catch (e) {
      // swallow
    }
  };

  const handleFilterApply = async (selectedTagsParam) => {
    setSelectedFilterTags(selectedTagsParam || []);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    // Close modal if tags are cleared
    if (!selectedTagsParam || selectedTagsParam.length === 0) {
      setFilterModal(false);
    }

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
        search: "",
        tags: tagsToUse?.length > 0 ? tagsToUse : undefined,
      });

      const data = sanitizeServersResponse(response.details || response);
      const mappedData = data.map(mapServerData);
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
      <FilterModal
        show={filterModal}
        onClose={() => setFilterModal(false)}
        tags={tags}
        handleFilter={handleFilterApply}
        selectedTags={selectedFilterTags}
        showfilterHeader={"Filter Servers by Tags"}
        filterTypes="servers"
      />
      <div className={styles.container}>
        <div className={styles.subHeaderContainer}>
          <SubHeader
            heading={"LIST OF SERVERS"}
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

        {/* Display searched server text if searchTerm exists and results are found */}
        {searchTerm.trim() && visible.length > 0 && (
          <div className={styles.searchedServerText}>
            <p>Servers Found: {searchTerm}</p>
          </div>
        )}

        {/* Display filtered servers text if filters are applied */}
        {selectedFilterTags.length > 0 && visible.length > 0 && (
          <div className={styles.filteredServerText}>
            <p>Servers Found: {selectedFilterTags.join(", ")}</p>
          </div>
        )}

        {/* Display "No Servers Found" messages when search or filters applied but no results */}
        {searchTerm.trim() && visible.length === 0 && (
          <div className={styles.filteredServerText}>
            <p>No Servers Found: {searchTerm}</p>
          </div>
        )}

        {selectedFilterTags.length > 0 && visible.length === 0 && (
          <div className={styles.searchedServerText}>
            <p>No Servers Found: {selectedFilterTags.join(", ")}</p>
          </div>
        )}

        <div className={styles.summaryLine}>
          <strong>{visible.length}</strong> servers (of {totalServersCount} total)
        </div>
        <div
          ref={serverListContainerRef}
          className={styles.serverGrid}
          style={{
            maxHeight: "60vh",
            height: "60vh", // Force a fixed height
            overflowY: "auto",
            overflowX: "hidden",
            scrollBehavior: "smooth",
            minHeight: "400px", // Increased min height
            border: "1px solid transparent", // Help with scroll detection
          }}
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
              <div style={{ position: "absolute", left: "10px", bottom: "10px", display: "flex", alignItems: "center", gap: "8px" }}>
                <span className={styles.typePill} style={{ fontSize: "12px", padding: "4px 10px", background: "#6b7280", color: "#fff", borderRadius: "8px" }}>
                  {s.type}
                </span>
              </div>
              <div style={{ position: "absolute", right: "10px", bottom: "10px", display: "flex", gap: "8px" }}>
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
                  <SVGIcons icon="fa-solid fa-user-xmark" width={20} height={16} fill="#fff" />
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
                    setEditServerData(s);
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
          {!hasMore && visible.length > 0 && (
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
          )}
          {visible.length === 0 && !loading && (
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
          )}
        </div>

        {open && selected && (
          <div className={styles.modalOverlay} onClick={() => setOpen(false)}>
            <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
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
                {String(selected.type || "").toUpperCase() !== "REMOTE" && (
                  <div className={styles.modalRight}>
                    <div className={styles.codeLabel}>Code Preview:</div>
                    <pre className={styles.codePreview}>{getCodePreview(selected)}</pre>
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
          showfilterHeader={"Filter servers by Tags"}
          filterTypes={"servers"}
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
            <div
              className={styles.modalOverlay}
              onClick={() => {
                setShowAddServerModal(false);
                setEditServerData(null);
              }}>
              <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
                <button
                  className={styles.closeBtn}
                  onClick={() => {
                    setShowAddServerModal(false);
                    setEditServerData(null);
                  }}>
                  ×
                </button>{" "}
                <AddServer
                  editMode={true}
                  serverData={editServerData}
                  setRefreshPaginated={() => {
                    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
                    getServersData(1, divsCount);
                  }}
                  onClose={() => {
                    try {
                      const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
                      getServersData(1, divsCount);
                    } catch (e) {}
                    setShowAddServerModal(false);
                    setEditServerData(null);
                  }}
                  drawerFormClass={styles.availableServersDrawerForm}
                />
              </div>
            </div>
          ) : (
            <div
              className={styles.modalOverlay}
              onClick={() => {
                setShowAddServerModal(false);
                setEditServerData(null);
              }}>
              <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
                <button
                  className={styles.closeBtn}
                  onClick={() => {
                    setShowAddServerModal(false);
                    setEditServerData(null);
                  }}>
                  ×
                </button>{" "}
                <AddServer
                  editMode={false}
                  serverData={null}
                  setRefreshPaginated={() => {
                    const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
                    getServersData(1, divsCount);
                  }}
                  onClose={() => {
                    try {
                      const divsCount = calculateDivs(serverListContainerRef, 200, 140, 16); // Use dynamic calculation
                      getServersData(1, divsCount);
                    } catch (e) {}
                    setShowAddServerModal(false);
                    setEditServerData(null);
                  }}
                  drawerFormClass={styles.availableServersDrawerForm}
                />
              </div>
            </div>
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
