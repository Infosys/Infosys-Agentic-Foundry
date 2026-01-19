/**
 * Pipeline List Component
 *
 * Displays a grid of available pipelines with search and filtering.
 * Similar to tools/servers listing in the onboarding page.
 */

import React, { useState, useEffect, useCallback, useRef } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faProjectDiagram,
} from "@fortawesome/free-solid-svg-icons";
import { usePipelineService } from "../../services/pipelineService";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import Loader from "../commonComponents/Loader";
import DeleteModal from "../commonComponents/DeleteModal";
import styles from "../../css_modules/PipelineBuilder.module.css";
import Cookies from "js-cookie";
import SubHeader from "../commonComponents/SubHeader";
import SVGIcons from "../../Icons/SVGIcons";

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
  const [totalCount, setTotalCount] = useState(0);
  const [deleteConfirm, setDeleteConfirm] = useState(null);

  const pageRef = useRef(1);
  const containerRef = useRef(null);

  const { getPipelinesPaginated, deletePipeline } = usePipelineService();
  const { addMessage } = useMessage();
  const { handleError } = useErrorHandler();
  const userEmail = Cookies.get("email");
  const userRole = Cookies.get("role")?.toLowerCase();

  /**
   * Fetch pipelines with pagination
   * - Regular users see only their own active pipelines
   * - Admin users see all active pipelines
   */
  const fetchPipelines = useCallback(
    async (page = 1, search = "") => {
      setLoading(true);
      try {
        const params = {
          page,
          limit: 20,
          search,
          is_active: true, // Only show active pipelines (soft-delete filter)
        };
        
        // Non-admin users only see their own pipelines
        if (userRole !== "admin" && userEmail) {
          params.created_by = userEmail;
        }

        const response = await getPipelinesPaginated(params);

        const pipelineData = response?.details || response?.pipelines || [];
        setPipelines((prev) =>
          page === 1 ? pipelineData : [...prev, ...pipelineData]
        );
        setTotalCount(response?.total_count || pipelineData.length);
      } catch (error) {
        // Handle 404 as empty state, not error
        if (error?.response?.status === 404) {
          setPipelines([]);
          setTotalCount(0);
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
    fetchPipelines(1, searchTerm);
  }, []);

  /**
   * Handle search input
   */
  const handleSearch = useCallback(
    (value) => {
      setSearchTerm(value);
      pageRef.current = 1;
      fetchPipelines(1, value);
    },
    [fetchPipelines]
  );

  /**
   * Clear search
   */
  const clearSearch = useCallback(() => {
    setSearchTerm("");
    pageRef.current = 1;
    fetchPipelines(1, "");
  }, [fetchPipelines]);

  /**
   * Handle refresh - clears search and reloads data
   */
  const handleRefresh = useCallback(() => {
    setSearchTerm("");
    pageRef.current = 1;
    fetchPipelines(1, "");
  }, [fetchPipelines]);

  /**
   * Handle pipeline deletion
   */
  const handleDelete = useCallback(
    async (pipelineId) => {
      try {
        const response = await deletePipeline(pipelineId);
        addMessage(response?.result?.message, "success");
        setDeleteConfirm(null);
        fetchPipelines(1, searchTerm);
      } catch (error) {
        const errorMessage = error?.response?.data?.detail;
        addMessage(errorMessage, "error");
        setDeleteConfirm(null);
      }
    },
    [deletePipeline, addMessage, fetchPipelines, searchTerm]
  );

  /**
   * Format date for display
   */
  const formatDate = (dateString) => {
    if (!dateString) return "N/A";
    try {
      const date = new Date(dateString);
      return date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return "N/A";
    }
  };

  /**
   * Get node count from pipeline definition
   */
  const getNodeCount = (pipeline) => {
    try {
      const definition = pipeline?.pipeline_definition;
      if (definition?.nodes) {
        return definition.nodes.length;
      }
      return 0;
    } catch {
      return 0;
    }
  };

  return (
    <div className={styles.pipelineListContainer} ref={containerRef}>
      {/* SubHeader with search, refresh, and create button */}
      <div className={styles.pipelineListHeader}>
        <SubHeader
          heading="Pipelines"
          onSearch={handleSearch}
          onPlusClick={onCreateNew}
          handleRefresh={handleRefresh}
          clearSearch={clearSearch}
          searchValue={searchTerm}
          showFilter={false}
        />
      </div>

      {/* Pipeline Grid */}
      {loading && pipelines.length === 0 ? (
        <Loader />
      ) : pipelines.length === 0 ? (
        <div className={styles.emptyState}>
          <FontAwesomeIcon icon={faProjectDiagram} className={styles.emptyStateIcon} />
          <h3 className={styles.emptyStateTitle}>No Pipelines Found</h3>
          <p className={styles.emptyStateText}>
            {searchTerm
              ? "No pipelines match your search criteria."
              : "Create your first pipeline to get started."}
          </p>
          {!searchTerm && (
            <button
              onClick={onCreateNew}
              className={styles.plus}
              title={"Add"}
            >
              <SVGIcons icon="fa-plus" fill="#007CC3" width={16} height={16} />
            </button>
          )}
        </div>
      ) : (
        <div className={styles.pipelineGrid}>
          {pipelines.map((pipeline) => (
            <div
              key={pipeline.pipeline_id}
              className={styles.pipelineCard}
              onClick={() => onEditPipeline(pipeline)}
            >
              <div className={styles.pipelineCardHeader}>
                <h4 className={styles.pipelineCardTitle}>
                  {pipeline.pipeline_name}
                </h4>
                {/* <span
                  className={`${styles.pipelineCardStatus} ${
                    pipeline.is_active !== false
                      ? styles.statusActive
                      : styles.statusInactive
                  }`}
                >
                  {pipeline.is_active !== false ? "Active" : "Inactive"}
                </span> */}
              </div>
              <div className={styles.pipelineCardDash}></div>
              <p className={styles.pipelineCardDescription}>
                {pipeline.pipeline_description || "No description provided."}
              </p>

              <div className={styles.pipelineCardMeta}>
                <span className={styles.pipelineCardMetaItem}>
                  {getNodeCount(pipeline)} nodes
                </span>
              </div>

              <div
                className={styles.pipelineCardActions}
                onClick={(e) => e.stopPropagation()}
              >
                <button
                  className={`${styles.cardActionBtn} ${styles.deleteBtn}`}
                  onClick={() => setDeleteConfirm(pipeline.pipeline_id)}
                  title="Delete Pipeline"
                >
                  <SVGIcons icon="recycle-bin" width={20} height={16} />
                </button>
                <button
                  className={`${styles.cardActionBtn} ${styles.editBtn}`}
                  onClick={() => onEditPipeline(pipeline)}
                  title="Edit Pipeline"
                >
                  <SVGIcons icon="fa-solid fa-pen" width={16} height={16} />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Delete Confirmation Modal */}
      <DeleteModal show={!!deleteConfirm} onClose={() => setDeleteConfirm(null)}>
        <p>Are you sure you want to delete this pipeline? This action cannot be undone.</p>
        <div className={styles.buttonContainer}>
          <button
            className={styles.deleteBtns}
            onClick={() => handleDelete(deleteConfirm)}
          >
            Delete
          </button>
          <button
            className={styles.cancelBtn}
            onClick={() => setDeleteConfirm(null)}
          >
            Cancel
          </button>
        </div>
      </DeleteModal>
    </div>
  );
};

export default PipelineList;