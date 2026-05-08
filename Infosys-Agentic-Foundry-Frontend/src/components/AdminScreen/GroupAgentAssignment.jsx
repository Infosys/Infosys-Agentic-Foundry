import React, { useEffect, useState, useRef, useCallback } from "react";
import { getRoleFromToken, getEmailFromToken } from "../../utils/jwtUtils";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import Loader from "../commonComponents/Loader.jsx";
import { usePermissions } from "../../context/PermissionsContext";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios.js";
import { extractErrorMessage } from "../../utils/errorUtils";
import { debounce } from "lodash";
import { useMessage } from "../../Hooks/MessageContext";
import EmptyState from "../commonComponents/EmptyState.jsx";
import GroupOnBoarding from "./GroupOnBoarding.jsx";
import useMultiSelect from "../../Hooks/useMultiSelect";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import CheckBox from "../../iafComponents/GlobalComponents/CheckBox/CheckBox";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import SVGIcons from "../../Icons/SVGIcons";
import subHeaderStyles from "../commonComponents/SubHeader.module.css";

const ITEMS_PER_PAGE = 20;
const CARD_MIN_WIDTH = 200;
const CARD_MIN_HEIGHT = 141;
const CARD_GAP = 40;
const DEBOUNCE_MS = 200;
const SCROLL_THRESHOLD = 10;
const DELAY_MS = 5;

const GroupAgentAssignment = ({ externalSearchTerm = "", onPlusClickRef, onClearSearchRef, onClearParentSearch }) => {
  const { loading: permissionsLoading } = usePermissions();
  const [groupList, setGroupList] = useState([]);
  const [searchTerm, setSearchTerm] = useState(externalSearchTerm);
  const [showForm, setShowForm] = useState(false);
  const [isAddGroup, setIsAddGroup] = useState(true);
  const [editGroup, setEditGroup] = useState({});
  const [loading, setLoading] = useState(false);
  const [visibleData, setVisibleData] = useState([]);
  const [, setPage] = useState(1);
  const [totalGroupsCount, setTotalGroupsCount] = useState(0);
  const [hasMore, setHasMore] = useState(true);
  const groupListContainerRef = useRef(null);
  const { fetchData, deleteData } = useFetch();
  const pageRef = useRef(1);
  const [loader, setLoaderState] = useState(false);
  const isLoadingRef = useRef(false);
  const { addMessage } = useMessage();

  // Additional state for Card component functionality
  const loggedInUserEmail = getEmailFromToken();
  const role = getRoleFromToken();
  const normalizedRole = role ? role.toUpperCase().replace(/[\s_-]/g, "") : "";
  const isSuperAdmin = normalizedRole === "SUPERADMIN";
  const isAdmin = normalizedRole === "ADMIN";
  const canManageGroups = isSuperAdmin || isAdmin;

  // Created By dropdown state
  const [createdBy, setCreatedBy] = useState("All");
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false);
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);

  // Calculate number of cards that fit in the container
  const calculateDivs = (containerRef) => {
    if (!containerRef?.current) return ITEMS_PER_PAGE;
    const containerWidth = containerRef.current.clientWidth;
    const containerHeight = containerRef.current.clientHeight;
    const cardsPerRow = Math.max(1, Math.floor((containerWidth + CARD_GAP) / (CARD_MIN_WIDTH + CARD_GAP)));
    const rowsVisible = Math.max(1, Math.ceil((containerHeight + CARD_GAP) / (CARD_MIN_HEIGHT + CARD_GAP)));
    return Math.max(ITEMS_PER_PAGE, cardsPerRow * (rowsVisible + 1)); // +1 for buffer
  };

  // Normalize API responses to always return a clean array of group objects
  const sanitizeGroupsResponse = (response) => {
    if (!response) return [];

    // Handle different response formats
    let source = [];
    if (Array.isArray(response.details)) {
      source = response.details;
    } else if (Array.isArray(response.groups)) {
      source = response.groups;
    } else if (Array.isArray(response.data)) {
      source = response.data;
    } else if (Array.isArray(response)) {
      source = response;
    }

    return source
      .filter((item) => item && typeof item === "object" && (item.group_name || item.name))
      .map((item) => ({
        id: item.group_name || item.name,
        group_name: item.group_name || item.name,
        group_description: item.group_description || item.description || "",
        user_emails: item.user_emails || [],
        agent_ids: item.agent_ids || [],
        created_by: item.created_by || "",
        created_at: item.created_at || "",
        type: "Group",
      }));
  };

  // Apply created_by filter
  const applyCreatedByFilter = (data, filterValue) => {
    if (!filterValue || filterValue === "All") return data;
    if (filterValue === "Me") {
      return data.filter((item) => item.created_by === loggedInUserEmail);
    }
    return data;
  };

  const handleSearch = async (searchValue, divsCount, pageNumber) => {
    const trimmedSearch = (searchValue || "").trim();
    setSearchTerm(searchValue || "");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    try {
      setLoading(true);
      const response = await getGroupsPaginated({
        page: pageNumber,
        limit: divsCount,
        search: trimmedSearch,
      });
      let dataToSearch = sanitizeGroupsResponse(response);
      dataToSearch = applyCreatedByFilter(dataToSearch, createdBy);

      setTotalGroupsCount(response?.total_count || dataToSearch.length);
      setVisibleData(dataToSearch);
      setHasMore(dataToSearch.length >= divsCount);

      // Also update groupList when not searching (for empty search reset)
      if (!trimmedSearch) {
        setGroupList(dataToSearch);
      }
    } catch (error) {
      console.error("Error searching groups:", error);
      setVisibleData([]);
      setHasMore(false);
    } finally {
      setLoading(false);
    }
  };

  // Fetch paginated groups from backend
  const getGroupsPaginated = async ({ page = 1, limit = ITEMS_PER_PAGE, search = "" }) => {
    try {
      const params = [];
      params.push(`page_number=${page}`);
      params.push(`page_size=${limit}`);
      if (search && search.trim() !== "") {
        params.push(`search_value=${encodeURIComponent(search.trim())}`);
      }

      const apiUrl = `${APIs.GET_GROUPS_SEARCH_PAGINATED}?${params.join("&")}`;
      const response = await fetchData(apiUrl);
      return response;
    } catch (error) {
      console.error("Failed to fetch groups:", error);
      throw error;
    }
  };

  const getGroupsData = async (pageNumber, divsCount) => {
    setLoading(true);
    try {
      const response = await getGroupsPaginated({
        page: pageNumber,
        limit: divsCount,
        search: "",
      });
      let data = sanitizeGroupsResponse(response);
      data = applyCreatedByFilter(data, createdBy);

      if (pageNumber === 1) {
        setGroupList(data);
        setVisibleData(data);
      } else {
        if (data.length > 0) {
          setVisibleData((prev) => (Array.isArray(prev) ? [...prev, ...data] : [...data]));
        }
      }
      setTotalGroupsCount(response?.total_count || data.length);
      if (data.length < divsCount) {
        setHasMore(false);
      } else if (pageNumber === 1) {
        setHasMore(true);
      }
      return data;
    } catch (error) {
      console.error("Error fetching groups:", error);
      if (pageNumber === 1) {
        setGroupList([]);
        setVisibleData([]);
      }
      setHasMore(false);
      return [];
    } finally {
      setLoading(false);
    }
  };

  const clearSearch = useCallback(() => {
    setSearchTerm("");
    setCreatedBy("All");
    setVisibleData([]);
    setHasMore(true);
    setPage(1);
    pageRef.current = 1;

    setTimeout(() => {
      const divsCount = calculateDivs(groupListContainerRef);
      setPage(1);
      pageRef.current = 1;
      getGroupsData(1, divsCount);
    }, DELAY_MS);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Expose clearSearch to parent via ref
  useEffect(() => {
    if (onClearSearchRef) {
      onClearSearchRef.current = clearSearch;
    }
  }, [onClearSearchRef, clearSearch]);

  // Sync with external search term from parent (skip initial render)
  useEffect(() => {
    // Skip first render - handled by initial load useEffect
    if (prevExternalSearchTerm.current === externalSearchTerm && !hasLoadedOnce.current) {
      return;
    }
    // Skip if value hasn't changed
    if (prevExternalSearchTerm.current === externalSearchTerm) {
      return;
    }
    prevExternalSearchTerm.current = externalSearchTerm;

    const divsCount = calculateDivs(groupListContainerRef);
    handleSearch(externalSearchTerm, divsCount, 1);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalSearchTerm]);

  // Scroll load more
  useEffect(() => {
    const container = groupListContainerRef?.current;
    if (!container) return;

    const checkAndLoadMore = () => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - SCROLL_THRESHOLD &&
        !loading &&
        !isLoadingRef.current &&
        hasMore
      ) {
        handleScrollLoadMore();
      }
    };

    const debouncedCheckAndLoad = debounce(checkAndLoadMore, DEBOUNCE_MS);

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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [groupListContainerRef, hasMore, loading]);

  const handleScrollLoadMore = async () => {
    if (loader || isLoadingRef.current || !hasMore) return;
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(groupListContainerRef);

    try {
      setLoaderState(true);
      setLoading(true);
      let newData = [];

      if (searchTerm.trim()) {
        const res = await getGroupsPaginated({
          page: nextPage,
          limit: divsCount,
          search: searchTerm,
        });
        newData = sanitizeGroupsResponse(res);
        newData = applyCreatedByFilter(newData, createdBy);

        if (newData.length > 0) {
          setVisibleData((prev) => (Array.isArray(prev) ? [...prev, ...newData] : [...newData]));
          setPage(nextPage);
          pageRef.current = nextPage;
        }
        if (newData.length < divsCount) setHasMore(false);
      } else {
        const appended = await getGroupsData(nextPage, divsCount);
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
      setLoading(false);
      isLoadingRef.current = false;
    }
  };

  const handlePlusIconClick = useCallback(() => {
    setShowForm(true);
    setIsAddGroup(true);
    setEditGroup({});
  }, []);

  // Expose handlePlusIconClick to parent via ref
  useEffect(() => {
    if (onPlusClickRef) {
      onPlusClickRef.current = handlePlusIconClick;
    }
  }, [onPlusClickRef, handlePlusIconClick]);

  // Initial data load - use externalSearchTerm for initial search
  const hasLoadedOnce = useRef(false);
  const prevExternalSearchTerm = useRef(externalSearchTerm);

  useEffect(() => {
    if (hasLoadedOnce.current) return;
    hasLoadedOnce.current = true;

    const divsCount = calculateDivs(groupListContainerRef);
    pageRef.current = 1;
    setPage(1);

    // Use externalSearchTerm for initial load
    if (externalSearchTerm) {
      handleSearch(externalSearchTerm, divsCount, 1);
    } else {
      getGroupsData(1, divsCount);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const handleRefresh = () => {
    setPage(1);
    pageRef.current = 1;
    setSearchTerm("");
    setCreatedBy("All");
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(groupListContainerRef);
    getGroupsData(1, divsCount);
  };

  // Fetch groups data after form close
  const fetchGroupsAfterFormClose = () => {
    handleRefresh();
  };

  // Permission checks - show loader inline instead of replacing entire component
  const isPermissionsLoading = permissionsLoading;

  // Multi-select state
  const {
    selectedIds: multiSelectIds,
    selectedCount: multiSelectCount,
    isAllSelected,
    isPartiallySelected,
    handleSelectionChange: handleMultiSelectChange,
    handleSelectAll,
    clearSelection: clearMultiSelection,
  } = useMultiSelect({ data: visibleData, idKey: "group_name" });

  // Bulk delete handler — single API call
  const handleBulkDeleteGroups = async () => {
    if (multiSelectIds.length === 0) return;
    setBulkDeleteLoading(true);

    try {
      const payload = { group_names: multiSelectIds };
      const response = await deleteData(APIs.DELETE_GROUP.replace(/\/$/, ""), payload);

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
    handleRefresh();
  };

  const handleCardDelete = async (groupName) => {
    const group = visibleData.find((g) => g.group_name === groupName);
    if (group) {
      if (!canManageGroups) {
        addMessage("Only Admins and Super Admins can delete groups", "error");
        return;
      }

      // Use bulk endpoint for single delete
      setLoading(true);
      try {
        const payload = { group_names: [groupName] };
        const result = await deleteData(APIs.DELETE_GROUP.replace(/\/$/, ""), payload);

        const statusMsg = result?.status_message || result?.message;
        const hasAnyFailure = Array.isArray(result?.results) && result.results.some((r) => r.is_delete === false);
        if (statusMsg) {
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
        if (!hasAnyFailure) handleRefresh();
      } catch (error) {
        const errorMsg = extractErrorMessage(error).message;
        if (errorMsg) addMessage(errorMsg, "error");
      }
      setLoading(false);
    }
  };

  return (
    <>
      {showForm && (
        <GroupOnBoarding
          setShowForm={setShowForm}
          isAddGroup={isAddGroup}
          editGroup={editGroup}
          setIsAddGroup={setIsAddGroup}
          fetchGroupsAfterFormClose={fetchGroupsAfterFormClose}
        />
      )}
      {(loading || isPermissionsLoading) && <Loader />}
      <>
        {/* Summary + Delete button row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "0 4px" }}>
          <SummaryLine visibleCount={visibleData.length} totalCount={totalGroupsCount} />
          {canManageGroups && multiSelectCount > 0 && (
            <IAFButton
              type="primary"
              className={subHeaderStyles.deleteSelectedBtn}
              onClick={() => setShowBulkDeleteModal(true)}
              icon={<SVGIcons icon="trash" width={14} height={14} color="#fff" />}
            >
              Delete ({multiSelectCount})
            </IAFButton>
          )}
        </div>
        {/* Select All row - above cards */}
        {canManageGroups && visibleData.length > 1 && (
          <div className={subHeaderStyles.selectAllRow}>
            <label className={subHeaderStyles.selectAllWrapper}>
              <CheckBox
                checked={isAllSelected}
                indeterminate={isPartiallySelected}
                onChange={handleSelectAll}
              />
              <span className={subHeaderStyles.selectAllLabel}>Select All</span>
            </label>
          </div>
        )}
        <div className="listWrapper" ref={groupListContainerRef}>
          {/* Show DisplayCard1 when there's data */}
          {!loading && visibleData?.length > 0 && (
            <DisplayCard1
              data={visibleData}
              onCardClick={(_cardName, item) => {
                console.log("Editing group:", item);
                setEditGroup(item);
                setShowForm(true);
                setIsAddGroup(false);
              }}
              onDeleteClick={(cardName) => handleCardDelete(cardName)}
              showDeleteButton={canManageGroups}
              showCheckbox={canManageGroups}
              onSelectionChange={handleMultiSelectChange}
              selectedIds={multiSelectIds}
              idKey="group_name"
              cardNameKey="group_name"
              cardDescriptionKey="group_description"
              cardOwnerKey="created_by"
              cardCategoryKey="type"
              contextType="group"
              onCreateClick={handlePlusIconClick}
              showCreateCard={false}
              footerButtonsConfig={[{ type: "delete", visible: canManageGroups }]}
            />
          )}
          {/* Display EmptyState when filters are active but no results */}
          {(searchTerm.trim() || (createdBy && createdBy !== "All")) && visibleData.length === 0 && !loading && (
            <EmptyState
              filters={[
                ...(createdBy === "Me" ? ["Created By: Me"] : []),
                ...(searchTerm.trim() ? [`Search: ${searchTerm}`] : []),
              ]}
              onClearFilters={() => {
                setSearchTerm("");
                setCreatedBy("All");
                if (onClearParentSearch) onClearParentSearch();
                handleRefresh();
              }}
              onCreateClick={canManageGroups ? handlePlusIconClick : undefined}
              createButtonLabel="Create Group"
              showCreateButton={canManageGroups}
            />
          )}
          {/* Display EmptyState when no data exists (no filters applied) */}
          {!searchTerm.trim() && (!createdBy || createdBy === "All") && visibleData.length === 0 && !loading && (
            <EmptyState
              message="No groups found"
              subMessage={canManageGroups ? "Get started by creating your first group" : "No groups available"}
              onCreateClick={canManageGroups ? handlePlusIconClick : undefined}
              createButtonLabel={canManageGroups ? "Create Group" : undefined}
              showClearFilter={false}
              showCreateButton={canManageGroups}
            />
          )}
        </div>
      </>

      {showBulkDeleteModal && (
        <ConfirmationModal
          message={`Are you sure you want to delete ${multiSelectCount} selected group(s)? This action cannot be undone.`}
          onConfirm={handleBulkDeleteGroups}
          setShowConfirmation={setShowBulkDeleteModal}
        />
      )}
    </>
  );
};

export default GroupAgentAssignment;
