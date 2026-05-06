/**
 * Workflow List Component
 *
 * Displays a grid of available workflows with search, filtering, and CRUD operations.
 * Features a modern card-based UI with hover effects and smooth transitions.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import { useWorkflowService } from "../../services/workflowService";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { usePermissions } from "../../context/PermissionsContext";
import SubHeader from "../commonComponents/SubHeader";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState.jsx";
import useMultiSelect from "../../Hooks/useMultiSelect";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import ShareModal from "../commonComponents/ShareModal/ShareModal.jsx";
import { getNodeCount } from "./workflowUtils";
import { getRoleFromToken, getEmailFromToken } from "../../utils/jwtUtils";


/**
 * WorkflowList - Displays all available workflows
 * @param {Object} props
 * @param {Function} props.onCreateNew - Handler for creating new workflow
 * @param {Function} props.onEditWorkflow - Handler for editing existing workflow
 */
const WorkflowList = ({ onCreateNew, onEditWorkflow }) => {
  // Bulk delete handler for workflows (uses deleteWorkflowsBulk API)
  const { getWorkflowsPaginated, deleteWorkflow, deleteWorkflowsBulk } = useWorkflowService();
  const handleBulkDeleteWorkflows = async () => {
    if (multiSelectIds.length === 0) return;
    // Filter out items created by the current user (creator cannot delete own items)
    const currentEmail = (loggedInUserEmail || "").trim().toLowerCase();
    const ownItems = workflows.filter((item) => multiSelectIds.includes(item.workflow_id) && (item.created_by || "").trim().toLowerCase() === currentEmail);
    const deletableIds = multiSelectIds.filter((id) => {
      const item = workflows.find((d) => d.workflow_id === id);
      return !item || (item.created_by || "").trim().toLowerCase() !== currentEmail;
    });
    if (ownItems.length > 0) {
      addMessage(`${ownItems.length} workflow(s) created by you were skipped. You cannot delete your own workflows.`, "error");
    }
    if (deletableIds.length === 0) {
      clearMultiSelection();
      setShowBulkDeleteModal(false);
      return;
    }
    // setBulkDeleteLoading(true); // Removed: loading state not used
    const role = getRoleFromToken();
    const isAdmin = role.toLowerCase() === "admin";
    try {
      const response = await deleteWorkflowsBulk({
        workflow_ids: deletableIds,
        is_admin: isAdmin,
        user_email_id: loggedInUserEmail,
      });
      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        }
      }
    } catch (error) {
      // silent catch
    }
    clearMultiSelection();
    setShowBulkDeleteModal(false);
    fetchWorkflows(1, searchTerm, createdBy);
  };
  const [workflows, setWorkflows] = useState([]);
  const [loading, setLoading] = useState(true);

  const {
    selectedIds: multiSelectIds,
    selectedCount: multiSelectCount,
    isAllSelected,
    isPartiallySelected,
    handleSelectionChange: handleMultiSelectChange,
    handleSelectAll,
    clearSelection: clearMultiSelection,
  } = useMultiSelect({ data: workflows, idKey: "workflow_id" });
  const [searchTerm, setSearchTerm] = useState("");
  const [hasMore, setHasMore] = useState(true); // Add hasMore state
  const [createdBy, setCreatedBy] = useState("All"); // Created By filter state
  const [shareModalData, setShareModalData] = useState(null);
  const [showShareModal, setShowShareModal] = useState(false);
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false);
  // Bulk delete loading state (not currently used, reserved for future use)

  const pageRef = useRef(1);
  const containerRef = useRef(null);
  const isLoadingRef = useRef(false);
  const { addMessage } = useMessage();
  const { handleError } = useErrorHandler();
  const hasLoadedOnce = useRef(false);
  const loggedInUserEmail = getEmailFromToken();
  const role = getRoleFromToken();
  const isAdmin = role?.toLowerCase() === "admin";

  // Permission checks for CRUD operations on workflows
  const { hasPermission } = usePermissions();
  const canReadWorkflows = typeof hasPermission === "function" ? hasPermission("read_access.workflows") : false;
  const canAddWorkflows = typeof hasPermission === "function" ? hasPermission("add_access.workflows") : false;
  const canUpdateWorkflows = typeof hasPermission === "function" ? hasPermission("update_access.workflows") : false;
  const canDeleteWorkflows = typeof hasPermission === "function" ? hasPermission("delete_access.workflows") : false;


  const fetchWorkflows = useCallback(
    async (page = 1, search = "", createdByFilter = "All") => {
      setLoading(true);
      try {
        // Pass created_by value based on filter selection
        const createdByEmail = createdByFilter === "Me" ? loggedInUserEmail : createdByFilter === "System" ? "system" : null;
        const params = {
          page,
          limit: 20,
          search,
          is_active: true,
          created_by: createdByEmail,
        };
        const response = await getWorkflowsPaginated(params);
        let workflowData = response?.details || response?.workflows || [];
        // Ensure each workflow has a workflow_id (map from pipeline_id if needed)
        workflowData = workflowData.map((wf) => ({
          ...wf,
          workflow_id: wf.workflow_id || wf.pipeline_id || "",
        }));

        // Update hasMore based on response length
        const PAGE_SIZE = 20;
        setHasMore(workflowData.length === PAGE_SIZE);

        setWorkflows((prev) => (page === 1 ? workflowData : [...prev, ...workflowData]));
      } catch (error) {
        // Handle 404 "no results" as empty array, not error
        const NOT_FOUND = 404;
        if (error?.response?.status === NOT_FOUND) {
          if (page === 1) {
            setWorkflows([]);
          }
          setHasMore(false);
        } else {
          handleError(error, { customMessage: "Failed to fetch workflows" });
        }
      } finally {
        setLoading(false);
      }
    },
    [getWorkflowsPaginated, handleError, loggedInUserEmail]
  );

  useEffect(() => {
    if (hasLoadedOnce.current) return;
    hasLoadedOnce.current = true;
    fetchWorkflows(1, "", createdBy);
  }, [fetchWorkflows, createdBy]);

  // Scroll-based infinite loading
  useEffect(() => {
    const container = containerRef?.current;
    if (!container) return;

    const handleScroll = () => {
      if (isLoadingRef.current || !hasMore) return;

      const { scrollTop, scrollHeight, clientHeight } = container;
      const SCROLL_THRESHOLD = 50;
      if (scrollTop + clientHeight >= scrollHeight - SCROLL_THRESHOLD) {
        // Load next page
        isLoadingRef.current = true;
        const nextPage = pageRef.current + 1;
        fetchWorkflows(nextPage, searchTerm, createdBy).finally(() => {
          pageRef.current = nextPage;
          isLoadingRef.current = false;
        });
      }
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, [hasMore, searchTerm, fetchWorkflows, createdBy]);

  // Handle search input
  const handleSearch = useCallback(
    (value) => {
      setSearchTerm(value);
      pageRef.current = 1;
      fetchWorkflows(1, value, createdBy);
    },
    [fetchWorkflows, createdBy]
  );
  /**
   * Clear search
   */

  const clearSearch = useCallback(() => {
    setSearchTerm("");
    setCreatedBy("All");
    pageRef.current = 1;
    fetchWorkflows(1, "", "All");
  }, [fetchWorkflows]);

  /**
   * Handle refresh - clears search and reloads data
   */
  const handleRefresh = useCallback(() => {
    setSearchTerm("");
    setCreatedBy("All");
    setHasMore(true); // Reset hasMore on refresh
    pageRef.current = 1;
    fetchWorkflows(1, "", "All");
  }, [fetchWorkflows]);

  /**
   * Handle workflow deletion
   */
  // Unified delete handler: always use bulk delete API for both single and multi
  const handleDelete = useCallback(
    async (workflowId) => {
      const role = getRoleFromToken();
      const isAdmin = role.toLowerCase() === "admin";
      try {
        const response = await deleteWorkflowsBulk({
          workflow_ids: [workflowId],
          is_admin: isAdmin,
          user_email_id: loggedInUserEmail,
        });
        if (response && typeof response !== "string") {
          const statusMsg = response.status_message || response.message;
          if (statusMsg) {
            const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
            addMessage(statusMsg, hasAnyFailure ? "error" : "success");
          }
        }
        fetchWorkflows(1, searchTerm, createdBy);
      } catch (error) {
        // silent catch
      }
    },
    [deleteWorkflowsBulk, addMessage, fetchWorkflows, searchTerm, createdBy, loggedInUserEmail]
  );

  /**
   * Handle created by filter change
   */
  const handleCreatedByChange = useCallback(
    (value) => {
      setCreatedBy(value);
      pageRef.current = 1;
      fetchWorkflows(1, searchTerm, value);
    },
    [fetchWorkflows, searchTerm]
  );

  /**
   * Bulk delete handler for multi-select — single API call
   */
  // Bulk delete logic for workflows should be implemented here if needed

  return (
    <>
      <div className={"pageContainer"} ref={containerRef}>
        {loading && <Loader />}
        <SubHeader
          heading="Workflows"
          onSearch={handleSearch}
          onPlusClick={canAddWorkflows ? onCreateNew : null}
          showPlusButton={canAddWorkflows}
          handleRefresh={handleRefresh}
          clearSearch={clearSearch}
          searchValue={searchTerm}
          showFilter={false}
          plusButtonLabel="New Workflow"
          showCreatedByDropdown={true}
          createdBy={createdBy}
          onCreatedByChange={handleCreatedByChange}
          showSelectAll={canDeleteWorkflows && isAdmin && workflows.length > 1}
          isAllSelected={isAllSelected}
          isPartiallySelected={isPartiallySelected}
          onSelectAll={handleSelectAll}
          selectedCount={multiSelectCount}
          onDeleteSelected={canDeleteWorkflows && isAdmin ? () => setShowBulkDeleteModal(true) : null}
        />

        {/* Workflow Grid using DisplayCard1 */}
        <div className="listWrapper" ref={containerRef}>
          {workflows?.length > 0 && (
            <DisplayCard1
              data={workflows.map((workflow) => {
                const nodeCount = getNodeCount(workflow);
                return {
                  ...workflow,
                  name: workflow.workflow_name,
                  description: workflow.workflow_description,
                  category: `${nodeCount} node${nodeCount === 1 ? "" : "s"}`,
                  id: workflow.workflow_id,
                };
              })}
              onCardClick={canReadWorkflows ? (name, item) => onEditWorkflow(item) : null}
              onCreateClick={canAddWorkflows ? onCreateNew : null}
              cardNameKey="name"
              cardDescriptionKey="description"
              cardCategoryKey="category"
              idKey="id"
              contextType="workflow"
              showCreateCard={false}
              showDeleteButton={false}
              showCheckbox={canDeleteWorkflows && isAdmin}
              onSelectionChange={handleMultiSelectChange}
              selectedIds={multiSelectIds}
              onShareClick={(item) => {
                setShareModalData(item);
                setShowShareModal(true);
              }}
              cardDisabled={!canReadWorkflows && !canUpdateWorkflows}
              emptyMessage={searchTerm ? "No workflows match your search criteria." : "Create your first workflow to orchestrate your agents."}
              loading={loading}
              ButtonComponent={Button}
              hideActions={!canReadWorkflows}
            />
          )}
          {/* Display EmptyState when search returns no results */}
          {searchTerm.trim() && workflows.length === 0 && !loading && (
            <EmptyState
              filters={[`Search: ${searchTerm}`]}
              onClearFilters={clearSearch}
              onCreateClick={canAddWorkflows ? onCreateNew : null}
              createButtonLabel={canAddWorkflows ? "Create Workflow" : null}
              showCreateButton={canAddWorkflows}
            />
          )}
          {/* Display EmptyState when no data exists from backend (no filters applied) */}
          {!searchTerm.trim() && workflows.length === 0 && !loading && (
            <EmptyState
              message="No workflows found"
              subMessage={canAddWorkflows ? "Get started by creating your first workflow to orchestrate your agents" : "No workflows available"}
              onCreateClick={canAddWorkflows ? onCreateNew : null}
              createButtonLabel={canAddWorkflows ? "Create Workflow" : null}
              showClearFilter={false}
              showCreateButton={canAddWorkflows}
            />
          )}
        </div>
      </div>

      <ShareModal
        show={showShareModal}
        onClose={() => setShowShareModal(false)}
        itemData={shareModalData}
        entityType="workflow"
      />

      {showBulkDeleteModal && (
        <ConfirmationModal
          message={`Are you sure you want to delete ${multiSelectCount} selected workflow(s)? This action cannot be undone.`}
          onConfirm={handleBulkDeleteWorkflows}
          setShowConfirmation={setShowBulkDeleteModal}
        />
      )}
    </>
  );
};

export default WorkflowList;