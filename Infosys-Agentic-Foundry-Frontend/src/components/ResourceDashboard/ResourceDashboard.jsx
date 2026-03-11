import { useEffect, useState, useRef, useCallback } from "react";
import styles from "./ResourceDashboard.module.css";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import SubHeader from "../commonComponents/SubHeader.jsx";
import Loader from "../commonComponents/Loader.jsx";
import EmptyState from "../commonComponents/EmptyState.jsx";
import useFetch from "../../Hooks/useAxios.js";
import { useMessage } from "../../Hooks/MessageContext";
import { APIs } from "../../constant";
import { extractErrorMessage } from "../../utils/errorUtils";
import { debounce } from "lodash";
import CreateAccessKeyModal from "./CreateAccessKeyModal.jsx";
import EditAccessKeyModal from "./EditAccessKeyModal.jsx";
import SVGIcons from "../../Icons/SVGIcons.js";

/**
 * ResourceDashboard Component
 * Displays access keys and resource information in a card-based layout
 * @param {Object} props - Component props
 * @param {string} props.externalSearchTerm - Search term passed from parent (e.g., AdminScreen)
 * @param {boolean} props.hideSubHeader - Hide internal SubHeader when used within Admin screen
 */
export default function ResourceDashboard({ externalSearchTerm = "", hideSubHeader = false }) {
  const [accessKeys, setAccessKeys] = useState([]);
  const [visibleData, setVisibleData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [totalCount, setTotalCount] = useState(0);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createLoading, setCreateLoading] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editLoading, setEditLoading] = useState(false);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const [accessKeyToEdit, setAccessKeyToEdit] = useState(null);

  // Users modal state - shows users with access to a specific access key
  const [showUsersModal, setShowUsersModal] = useState(false);
  const [usersLoading, setUsersLoading] = useState(false);
  const [accessKeyUsers, setAccessKeyUsers] = useState([]);
  const [selectedKeyForUsers, setSelectedKeyForUsers] = useState(null);
  const listContainerRef = useRef(null);
  const pageRef = useRef(1);
  const isLoadingRef = useRef(false);
  const { fetchData, postData, deleteData, putData } = useFetch();
  const { addMessage } = useMessage();

  const PAGE_SIZE = 20;

  // Fetch access keys from the API
  const fetchAccessKeys = useCallback(async (pageNumber = 1, search = "") => {
    if (isLoadingRef.current) return;
    isLoadingRef.current = true;
    setLoading(true);

    try {
      // Hit the endpoint without pagination params
      const apiUrl = APIs.RD_GET_ACCESS_KEYS;
      const response = await fetchData(apiUrl);

      // Debug: Log the API response to see its structure
      console.log("Resource Dashboard API Response:", response);

      // Handle response - the API returns { access_keys: [...], total_count: n, department_name: "..." }
      const data = response?.access_keys || response?.details || response?.data || response || [];
      console.log("Extracted data:", data);

      const total = response?.total_count || data.length || 0;

      // Transform data for DisplayCard1 component
      const transformedData = Array.isArray(data) ? data.map((item, index) => ({
        id: item.id || item.key_id || item.access_key || `key-${index}`,
        name: item.access_key || item.name || item.key_name || "Unnamed Key",
        access_key: item.access_key || item.name || "",
        description: item.description || item.key_description || "No description available",
        created_by: item.created_by || item.owner || "Unknown",
        type: item.type || item.key_type || "Access Key",
        status: item.status || "Active",
        department_name: item.department_name || "",
        created_at: item.created_at || "",
        ...item
      })) : [];

      if (pageNumber === 1) {
        setAccessKeys(transformedData);
        setVisibleData(transformedData);
      } else {
        setAccessKeys((prev) => [...prev, ...transformedData]);
        setVisibleData((prev) => [...prev, ...transformedData]);
      }

      setTotalCount(total);
      setHasMore(transformedData.length >= PAGE_SIZE);
    } catch (error) {
      console.error("Error fetching access keys:", error);
      const errorMessage = extractErrorMessage(error).message || "Failed to fetch access keys";
      addMessage(errorMessage, "error");
      if (pageNumber === 1) {
        setAccessKeys([]);
        setVisibleData([]);
      }
      setHasMore(false);
    } finally {
      setLoading(false);
      isLoadingRef.current = false;
    }
  }, [fetchData, addMessage]);

  // Initial data load
  useEffect(() => {
    fetchAccessKeys(1, "");
  }, []);

  // Handle external search term from parent (Admin screen)
  useEffect(() => {
    if (externalSearchTerm !== undefined) {
      setSearchTerm(externalSearchTerm);
      setPage(1);
      pageRef.current = 1;
      // Filter existing data based on external search term
      if (externalSearchTerm.trim()) {
        const filtered = accessKeys.filter(
          (item) =>
            (item.name && item.name.toLowerCase().includes(externalSearchTerm.toLowerCase())) ||
            (item.description && item.description.toLowerCase().includes(externalSearchTerm.toLowerCase())) ||
            (item.created_by && item.created_by.toLowerCase().includes(externalSearchTerm.toLowerCase())) ||
            (item.type && item.type.toLowerCase().includes(externalSearchTerm.toLowerCase()))
        );
        setVisibleData(filtered);
      } else {
        setVisibleData(accessKeys);
      }
    }
  }, [externalSearchTerm, accessKeys]);

  // Handle search - filter locally from already fetched data
  const handleSearch = useCallback((searchValue) => {
    setSearchTerm(searchValue);
    setPage(1);
    pageRef.current = 1;
    if (searchValue.trim()) {
      const filtered = accessKeys.filter(
        (item) =>
          (item.name && item.name.toLowerCase().includes(searchValue.toLowerCase())) ||
          (item.description && item.description.toLowerCase().includes(searchValue.toLowerCase())) ||
          (item.created_by && item.created_by.toLowerCase().includes(searchValue.toLowerCase())) ||
          (item.type && item.type.toLowerCase().includes(searchValue.toLowerCase()))
      );
      setVisibleData(filtered);
    } else {
      setVisibleData(accessKeys);
    }
  }, [accessKeys]);

  // Handle refresh
  const handleRefresh = useCallback(() => {
    setSearchTerm("");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    fetchAccessKeys(1, "");
  }, [fetchAccessKeys]);

  // Clear search - reset to full data
  const clearSearch = useCallback(() => {
    setSearchTerm("");
    setPage(1);
    pageRef.current = 1;
    setVisibleData(accessKeys);
  }, [accessKeys]);

  // Handle scroll for pagination
  useEffect(() => {
    const container = listContainerRef?.current;
    if (!container) return;

    const handleScrollLoadMore = async () => {
      if (isLoadingRef.current || !hasMore) return;

      if (container.scrollTop + container.clientHeight >= container.scrollHeight - 10) {
        const nextPage = pageRef.current + 1;
        pageRef.current = nextPage;
        setPage(nextPage);
        await fetchAccessKeys(nextPage, searchTerm);
      }
    };

    const debouncedScroll = debounce(handleScrollLoadMore, 200);
    container.addEventListener("scroll", debouncedScroll);

    return () => {
      debouncedScroll.cancel && debouncedScroll.cancel();
      container.removeEventListener("scroll", debouncedScroll);
    };
  }, [hasMore, searchTerm, fetchAccessKeys]);

  // Handle card click - fetch full access details (allowed and excluded values)
  const handleCardClick = async (cardName, item) => {
    console.log("Card clicked:", cardName, item);
    const accessKey = item.access_key || item.name || cardName;

    if (!accessKey) {
      addMessage("Unable to get access key details", "error");
      return;
    }

    // Open modal first with loading state
    setAccessKeyToEdit(item);
    setDetailsLoading(true);
    setShowEditModal(true);

    try {
      // Use the my-access/full endpoint to get both allowed and excluded values
      const apiUrl = `${APIs.RD_GET_MY_FULL_ACCESS}${encodeURIComponent(accessKey)}/my-access/full`;
      const response = await fetchData(apiUrl);
      console.log("Access Key Full Access Response:", response);
      // Merge response with original item data
      setAccessKeyToEdit({ ...item, ...response });
    } catch (error) {
      console.error("Error fetching access key details:", error);
      // If API fails, use the item data we already have
      setAccessKeyToEdit(item);
    } finally {
      setDetailsLoading(false);
    }
  };

  // Handle delete click - directly delete without confirmation (Card component has built-in confirmation)
  const handleDeleteClick = async (cardName, item) => {
    console.log("Delete clicked:", cardName, item);
    const accessKey = item.access_key || item.name || cardName;

    if (!accessKey) {
      addMessage("Unable to delete - access key not found", "error");
      return;
    }

    try {
      const apiUrl = `${APIs.RD_DELETE_ACCESS_KEY}${encodeURIComponent(accessKey)}`;
      await deleteData(apiUrl);
      addMessage("Access key deleted successfully", "success");
      // Refresh the list
      isLoadingRef.current = false;
      fetchAccessKeys(1, "");
    } catch (error) {
      console.error("Error deleting access key:", error);
      const errorMessage = extractErrorMessage(error).message || "Failed to delete access key";
      addMessage(errorMessage, "error");
    }
  };

  // Handle eye icon click - fetch tools that use this access key
  const handleViewTools = async (cardName, item) => {
    console.log("View tools clicked:", cardName, item);
    const accessKey = item?.access_key || item?.name || cardName;

    if (!accessKey) {
      addMessage("Unable to get tools - access key not found", "error");
      return;
    }

    setSelectedKeyForUsers(accessKey);
    setUsersLoading(true);
    setShowUsersModal(true);

    try {
      // Use GET /resource-dashboard/access-keys/{access_key}/tools endpoint
      const apiUrl = `${APIs.RD_GET_ACCESS_KEY_TOOLS}${encodeURIComponent(accessKey)}/tools`;
      const response = await fetchData(apiUrl);
      console.log("Access Key Tools Response:", response);
      // Handle response - could be array or object with tools array
      const tools = response?.tools || response || [];
      setAccessKeyUsers(Array.isArray(tools) ? tools : []);
    } catch (error) {
      console.error("Error fetching access key tools:", error);
      setAccessKeyUsers([]);
      const errorMessage = extractErrorMessage(error).message || "Failed to fetch tools for this access key";
      addMessage(errorMessage, "error");
    } finally {
      setUsersLoading(false);
    }
  };

  // Handle update access key values submission
  const handleUpdateAccessKey = async ({ add_values = [], remove_values = [], add_exclusions = [], remove_exclusions = [] }) => {
    if (!accessKeyToEdit) return;

    const accessKey = accessKeyToEdit.access_key || accessKeyToEdit.name;
    if (!accessKey) {
      addMessage("Unable to update - access key not found", "error");
      return;
    }

    // Check if there are any changes to submit
    if (add_values.length === 0 && remove_values.length === 0 && add_exclusions.length === 0 && remove_exclusions.length === 0) {
      addMessage("No changes to save", "info");
      setShowEditModal(false);
      setAccessKeyToEdit(null);
      return;
    }

    setEditLoading(true);
    try {
      // Use PUT /resource-dashboard/access-keys/{access_key}/my-access endpoint
      // API expects: add_values, remove_values, add_exclusions, remove_exclusions
      const apiUrl = `${APIs.RD_UPDATE_MY_ACCESS}${encodeURIComponent(accessKey)}/my-access`;
      const requestBody = {};
      if (add_values.length > 0) requestBody.add_values = add_values;
      if (remove_values.length > 0) requestBody.remove_values = remove_values;
      if (add_exclusions.length > 0) requestBody.add_exclusions = add_exclusions;
      if (remove_exclusions.length > 0) requestBody.remove_exclusions = remove_exclusions;
      const response = await putData(apiUrl, requestBody);
      console.log("Update Access Key Response:", response);
      addMessage("Access key updated successfully", "success");
      setShowEditModal(false);
      setAccessKeyToEdit(null);
      // Refresh the list
      isLoadingRef.current = false;
      fetchAccessKeys(1, "");
    } catch (error) {
      console.error("Error updating access key:", error);
      const errorMessage = extractErrorMessage(error).message || "Failed to update access key";
      addMessage(errorMessage, "error");
    } finally {
      setEditLoading(false);
    }
  };

  // Handle create button click
  const handleCreateClick = () => {
    setShowCreateModal(true);
  };

  // Handle create access key submission
  const handleCreateAccessKey = async (formData) => {
    setCreateLoading(true);
    try {
      const response = await postData(APIs.RD_CREATE_ACCESS_KEY, formData);
      console.log("Create Access Key Response:", response);
      addMessage("Access key created successfully", "success");
      setShowCreateModal(false);
      // Reset loading ref and refresh the list
      isLoadingRef.current = false;
      setSearchTerm("");
      setPage(1);
      pageRef.current = 1;
      setVisibleData([]);
      setHasMore(true);
      // Fetch fresh data
      fetchAccessKeys(1, "");
    } catch (error) {
      console.error("Error creating access key:", error);
      const errorMessage = extractErrorMessage(error).message || "Failed to create access key";
      addMessage(errorMessage, "error");
    } finally {
      setCreateLoading(false);
    }
  };

  return (
    <>
      {loading && <Loader />}

      {/* Create Access Key Modal */}
      {showCreateModal && (
        <CreateAccessKeyModal
          onClose={() => setShowCreateModal(false)}
          onSubmit={handleCreateAccessKey}
          loading={createLoading}
        />
      )}

      {/* Edit Access Key Modal */}
      {showEditModal && (
        <EditAccessKeyModal
          onClose={() => {
            setShowEditModal(false);
            setAccessKeyToEdit(null);
          }}
          onSubmit={handleUpdateAccessKey}
          loading={editLoading}
          detailsLoading={detailsLoading}
          accessKeyData={accessKeyToEdit}
        />
      )}

      {/* Tools Modal - Shows tools that use this access key */}
      {showUsersModal && (
        <div className={styles.modalOverlay} onClick={() => {
          setShowUsersModal(false);
          setAccessKeyUsers([]);
          setSelectedKeyForUsers(null);
        }}>
          <div className={styles.modal} onClick={(e) => e.stopPropagation()}>
            <button
              className={"closeBtn " + styles.closeBtn}
              onClick={() => {
                setShowUsersModal(false);
                setAccessKeyUsers([]);
                setSelectedKeyForUsers(null);
              }}
            >
              ×
            </button>
            <h3 className={styles.modalTitle}>Tools using Access Key "{selectedKeyForUsers}"</h3>
            <div className={styles.modalBody}>
              {usersLoading ? (
                <p className={styles.loadingText}>Loading tools...</p>
              ) : accessKeyUsers.length > 0 ? (
                <div className={styles.infoRow}>
                  <div>
                    <strong style={{ display: "inline-block" }}>Tools:</strong>
                    <span className={styles.count}>{accessKeyUsers.length}</span>
                  </div>
                  <ol className={styles.infoList}>
                    {accessKeyUsers.map((tool, index) => (
                      <li key={index}>
                        {tool.tool_name || tool.name || tool}
                      </li>
                    ))}
                  </ol>
                </div>
              ) : (
                <p className={styles.emptyMessage}>No tools are using this access key.</p>
              )}
            </div>
          </div>
        </div>
      )}

      {/* When used in Admin screen, hide SubHeader and use simpler container */}
      {hideSubHeader ? (
        <div className={styles.adminContainer}>
          <SummaryLine visibleCount={visibleData.length} totalCount={totalCount} />

          <div className="listWrapper" ref={listContainerRef}>
            {visibleData?.length > 0 && (
              <DisplayCard1
                data={visibleData}
                onCardClick={handleCardClick}
                onDeleteClick={handleDeleteClick}
                onButtonClick={handleViewTools}
                showButton={true}
                buttonIcon={<SVGIcons icon="eye" width={16} height={16} />}
                cardNameKey="name"
                cardDescriptionKey="description"
                cardOwnerKey="created_by"
                cardCategoryKey="type"
                contextType="resource"
                showCreateCard={false}
                onCreateClick={handleCreateClick}
                showCheckbox={false}
                showDeleteButton={true}
                className="resource-cards"
              />
            )}

            {/* Empty state when search returns no results */}
            {searchTerm.trim() && visibleData.length === 0 && !loading && (
              <EmptyState
                filters={[`Search: ${searchTerm}`]}
                onClearFilters={clearSearch}
              />
            )}

            {/* Empty state when no data exists */}
            {!searchTerm.trim() && visibleData.length === 0 && !loading && (
              <EmptyState
                message="No access keys found"
                subMessage="Get started by creating your first access key"
                showClearFilter={false}
                onCreateClick={handleCreateClick}
                createButtonLabel="Create Access Key"
              />
            )}
          </div>
        </div>
      ) : (
        <div className="pageContainer">
          <SubHeader
            heading="Resource Dashboard"
            activeTab="resource-dashboard"
            searchValue={searchTerm}
            onSearch={handleSearch}
            handleRefresh={handleRefresh}
            clearSearch={clearSearch}
            showPlusButton={true}
            onPlusClick={handleCreateClick}
            plusButtonLabel="New Access Key"
          />

          <SummaryLine visibleCount={visibleData.length} totalCount={totalCount} />

          <div className="listWrapper" ref={listContainerRef}>
            {visibleData?.length > 0 && (
              <DisplayCard1
                data={visibleData}
                onCardClick={handleCardClick}
                onDeleteClick={handleDeleteClick}
                onButtonClick={handleViewTools}
                showButton={true}
                buttonIcon={<SVGIcons icon="eye" width={16} height={16} />}
                cardNameKey="name"
                cardDescriptionKey="description"
                cardOwnerKey="created_by"
                cardCategoryKey="type"
                contextType="resource"
                showCreateCard={false}
                onCreateClick={handleCreateClick}
                showCheckbox={false}
                showDeleteButton={true}
                className="resource-cards"
              />
            )}

            {/* Empty state when search returns no results */}
            {searchTerm.trim() && visibleData.length === 0 && !loading && (
              <EmptyState
                filters={[`Search: ${searchTerm}`]}
                onClearFilters={clearSearch}
              />
            )}

            {/* Empty state when no data exists */}
            {!searchTerm.trim() && visibleData.length === 0 && !loading && (
              <EmptyState
                message="No access keys found"
                subMessage="Get started by creating your first access key"
                showClearFilter={false}
                onCreateClick={handleCreateClick}
                createButtonLabel="Create Access Key"
              />
            )}
          </div>
        </div>
      )}
    </>
  );
}
