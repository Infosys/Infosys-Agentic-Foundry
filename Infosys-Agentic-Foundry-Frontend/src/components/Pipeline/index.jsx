/**
 * Pipeline Component
 *
 * Main entry component for Pipeline management.
 * Handles view switching between list and builder views.
 */

import { useState, useCallback } from "react";
import PipelineList from "./PipelineList";
import PipelineBuilder from "./PipelineBuilder";
import { useActiveNavClick } from "../../events/navigationEvents";
import { usePipelineService } from "../../services/pipelineService";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { usePermissions } from "../../context/PermissionsContext";
import Loader from "../commonComponents/Loader";

/**
 * Views for the Pipeline component
 */
const VIEWS = {
  LIST: "list",
  BUILDER: "builder",
};

/**
 * Pipeline - Main container component
 * @param {Object} props
 * @param {Function} props.onClose - Optional handler to close pipeline view
 */
const Pipeline = ({ onClose }) => {
  const [currentView, setCurrentView] = useState(VIEWS.LIST);
  const [selectedPipeline, setSelectedPipeline] = useState(null);
  const [loadingPipeline, setLoadingPipeline] = useState(false);
  const { getPipelineById } = usePipelineService();
  const { addMessage } = useMessage();
  const { handleError } = useErrorHandler();
  const { hasPermission } = usePermissions();
  const canUpdatePipelines = typeof hasPermission === "function" ? hasPermission("update_access.agents") : false;

  /**
   * Handle creating new pipeline
   */
  const handleCreateNew = useCallback(() => {
    setSelectedPipeline(null);
    setCurrentView(VIEWS.BUILDER);
  }, []);

  /**
   * Handle editing existing pipeline - fetches fresh data by ID
   */
  const handleEditPipeline = useCallback(async (pipeline) => {
    const pipelineId = pipeline?.pipeline_id;
    if (!pipelineId) {
      addMessage("Pipeline ID not found", "error");
      return;
    }
    setLoadingPipeline(true);
    try {
      const response = await getPipelineById(pipelineId);
      setSelectedPipeline(response?.pipeline || response);
      setCurrentView(VIEWS.BUILDER);
    } catch (error) {
      handleError(error);
    } finally {
      setLoadingPipeline(false);
    }
  }, [getPipelineById, addMessage, handleError]);

  /**
   * Handle going back to list
   */
  const handleBackToList = useCallback(() => {
    setSelectedPipeline(null);
    setCurrentView(VIEWS.LIST);
  }, []);

  /**
   * Handle successful save
   */
  const handleSaveSuccess = useCallback(() => {
    setSelectedPipeline(null);
    setCurrentView(VIEWS.LIST);
  }, []);

  useActiveNavClick("/pipeline", () => {
    // Reset to list view when pipeline nav is clicked while already active
    handleBackToList();
  });

  return (
    <>
      {loadingPipeline && <Loader />}
      {currentView === VIEWS.LIST ? (
        <PipelineList onCreateNew={handleCreateNew} onEditPipeline={handleEditPipeline} />
      ) : (
        <PipelineBuilder pipeline={selectedPipeline} onBack={handleBackToList} onSave={handleSaveSuccess} readOnly={!canUpdatePipelines} />
      )}
    </>
  );
};

export default Pipeline;
export { PipelineList, PipelineBuilder };
