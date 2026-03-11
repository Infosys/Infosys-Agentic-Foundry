/**
 * Pipeline List Component
 *
 * Displays a grid of available pipelines with search, filtering, and CRUD operations.
 * Features a modern card-based UI with hover effects and smooth transitions.
 */

import { useState, useEffect, useCallback, useRef } from "react";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button.jsx";
import { usePipelineService } from "../../services/pipelineService";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { usePermissions } from "../../context/PermissionsContext";
import SubHeader from "../commonComponents/SubHeader";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState.jsx";
import { getNodeCount } from "./pipelineUtils";
import Cookies from "js-cookie";

/**
 * PipelineList - Displays all available pipelines
 * @param {Object} props
 * @param {Function} props.onCreateNew - Handler for creating new pipeline
 * @param {Function} props.onEditPipeline - Handler for editing existing pipeline
 */
const PipelineList = ({ onCreateNew, onEditPipeline }) => {
  const [pipelines, setPipelines] = useState([]);
  const [loading, setLoading] = useState(true);
  const [searchTerm, setSearchTerm] = useState("");
  const [hasMore, setHasMore] = useState(true); // Add hasMore state
  const [createdBy, setCreatedBy] = useState("All"); // Created By filter state
  const pageRef = useRef(1);
  const containerRef = useRef(null);
  const isLoadingRef = useRef(false);
  const { getPipelinesPaginated, deletePipeline } = usePipelineService();
  const { addMessage } = useMessage();
  const { handleError } = useErrorHandler();
  const hasLoadedOnce = useRef(false);
  const loggedInUserEmail = Cookies.get("email");

  // Permission checks for CRUD operations on pipelines (using agents permissions)
  const { hasPermission } = usePermissions();
  const canReadPipelines = typeof hasPermission === "function" ? hasPermission("read_access.agents") : false;
  const canAddPipelines = typeof hasPermission === "function" ? hasPermission("add_access.agents") : false;
  const canUpdatePipelines = typeof hasPermission === "function" ? hasPermission("update_access.agents") : false;
  const canDeletePipelines = typeof hasPermission === "function" ? hasPermission("delete_access.agents") : false;

  // Fetch pipelines with pagination
  const fetchPipelines = useCallback(
    async (page = 1, search = "", createdByFilter = "All") => {
      setLoading(true);
      try {
        // Pass created_by email when "Me" filter is selected
        const createdByEmail = createdByFilter === "Me" ? loggedInUserEmail : undefined;
        const params = {
          page,
          limit: 20,
          search,
          is_active: true,
          created_by: createdByEmail,
        };
        const response = await getPipelinesPaginated(params);
        const pipelineData = response?.details || response?.pipelines || [];

        // Update hasMore based on response length
        setHasMore(pipelineData.length === 20);

        setPipelines((prev) => (page === 1 ? pipelineData : [...prev, ...pipelineData]));
      } catch (error) {
        // Handle 404 "no results" as empty array, not error
        if (error?.response?.status === 404) {
          if (page === 1) {
            setPipelines([]);
          }
          setHasMore(false);
        } else {
          handleError(error, { customMessage: "Failed to fetch pipelines" });
        }
      } finally {
        setLoading(false);
      }
    },
    [getPipelinesPaginated, handleError]
  );

  useEffect(() => {
    if (hasLoadedOnce.current) return;
    hasLoadedOnce.current = true;
    fetchPipelines(1, "", createdBy);
  }, [fetchPipelines, createdBy]);

  // Scroll-based infinite loading
  useEffect(() => {
    const container = containerRef?.current;
    if (!container) return;

    const handleScroll = () => {
      if (isLoadingRef.current || !hasMore) return;

      const { scrollTop, scrollHeight, clientHeight } = container;
      if (scrollTop + clientHeight >= scrollHeight - 50) {
        // Load next page
        isLoadingRef.current = true;
        const nextPage = pageRef.current + 1;
        fetchPipelines(nextPage, searchTerm, createdBy).finally(() => {
          pageRef.current = nextPage;
          isLoadingRef.current = false;
        });
      }
    };

    container.addEventListener("scroll", handleScroll);
    return () => container.removeEventListener("scroll", handleScroll);
  }, [hasMore, searchTerm, fetchPipelines]);

  // Handle search input
  const handleSearch = useCallback(
    (value) => {
      setSearchTerm(value);
      pageRef.current = 1;
      fetchPipelines(1, value, createdBy);
    },
    [fetchPipelines, createdBy]
  );
  /**
   * Clear search
   */

  const clearSearch = useCallback(() => {
    setSearchTerm("");
    setCreatedBy("All");
    pageRef.current = 1;
    fetchPipelines(1, "", "All");
  }, [fetchPipelines]);

  /**
   * Handle refresh - clears search and reloads data
   */
  const handleRefresh = useCallback(() => {
    setSearchTerm("");
    setCreatedBy("All");
    setHasMore(true); // Reset hasMore on refresh
    pageRef.current = 1;
    fetchPipelines(1, "", "All");
  }, [fetchPipelines]);

  /**
   * Handle pipeline deletion
   */
  const handleDelete = useCallback(
    async (pipelineId) => {
      try {
        const response = await deletePipeline(pipelineId);
        addMessage(response?.result?.message || "Pipeline deleted successfully", "success");
        // No card flip needed
        fetchPipelines(1, searchTerm, createdBy);
      } catch (error) {
        const errorMessage = error?.response?.data?.detail || "Failed to delete pipeline";
        addMessage(errorMessage, "error");
        // No card flip needed
      }
    },
    [deletePipeline, addMessage, fetchPipelines, searchTerm, createdBy]
  );

  /**
   * Handle created by filter change
   */
  const handleCreatedByChange = useCallback(
    (value) => {
      setCreatedBy(value);
      pageRef.current = 1;
      fetchPipelines(1, searchTerm, value);
    },
    [fetchPipelines, searchTerm]
  );

  return (
    <>
      {loading && <Loader />}
      <div className={"pageContainer"} ref={containerRef}>
        <SubHeader
          heading="Pipelines"
          onSearch={handleSearch}
          onPlusClick={canAddPipelines ? onCreateNew : undefined}
          showPlusButton={canAddPipelines}
          handleRefresh={handleRefresh}
          clearSearch={clearSearch}
          searchValue={searchTerm}
          showFilter={false}
          plusButtonLabel="New Pipeline"
          showCreatedByDropdown={true}
          createdBy={createdBy}
          onCreatedByChange={handleCreatedByChange}
        />

        {/* Pipeline Grid using DisplayCard1 */}
        <div className="listWrapper" ref={containerRef}>
          {pipelines?.length > 0 && (
            <DisplayCard1
              data={pipelines.map((pipeline) => {
                const nodeCount = getNodeCount(pipeline);
                return {
                  ...pipeline,
                  name: pipeline.pipeline_name,
                  description: pipeline.pipeline_description,
                  category: `${nodeCount} node${nodeCount === 1 ? "" : "s"}`,
                  id: pipeline.pipeline_id,
                };
              })}
              onCardClick={(canReadPipelines || canUpdatePipelines) ? (name, item) => onEditPipeline(item) : undefined}
              onDeleteClick={canDeletePipelines ? (name, item) => handleDelete(item.pipeline_id) : undefined}
              onCreateClick={canAddPipelines ? onCreateNew : undefined}
              cardNameKey="name"
              cardDescriptionKey="description"
              cardCategoryKey="category"
              idKey="id"
              contextType="pipeline"
              showCreateCard={false}
              showDeleteButton={canDeletePipelines}
              cardDisabled={!canReadPipelines && !canUpdatePipelines}
              emptyMessage={searchTerm ? "No pipelines match your search criteria." : "Create your first pipeline to orchestrate your agents."}
              loading={loading}
              ButtonComponent={Button}
            />
          )}
          {/* Display EmptyState when search returns no results */}
          {searchTerm.trim() && pipelines.length === 0 && !loading && (
            <EmptyState
              filters={[`Search: ${searchTerm}`]}
              onClearFilters={clearSearch}
              onCreateClick={canAddPipelines ? onCreateNew : undefined}
              createButtonLabel={canAddPipelines ? "Create Pipeline" : undefined}
              showCreateButton={canAddPipelines}
            />
          )}
          {/* Display EmptyState when no data exists from backend (no filters applied) */}
          {!searchTerm.trim() && pipelines.length === 0 && !loading && (
            <EmptyState
              message="No pipelines found"
              subMessage={canAddPipelines ? "Get started by creating your first pipeline to orchestrate your agents" : "No pipelines available"}
              onCreateClick={canAddPipelines ? onCreateNew : undefined}
              createButtonLabel={canAddPipelines ? "Create Pipeline" : undefined}
              showClearFilter={false}
              showCreateButton={canAddPipelines}
            />
          )}
        </div>
      </div>
    </>
  );
};

export default PipelineList;
