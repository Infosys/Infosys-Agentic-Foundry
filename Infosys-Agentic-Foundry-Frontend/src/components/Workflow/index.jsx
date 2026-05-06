/**
 * Workflow Component
 *
 * Main entry component for Workflow management.
 * Handles view switching between list and builder views.
 */

import { useState, useCallback } from "react";
import WorkflowList from "./WorkflowList";
import WorkflowBuilder from "./WorkflowBuilder";
import { useActiveNavClick } from "../../events/navigationEvents";
import { useWorkflowService } from "../../services/workflowService";
import { useMessage } from "../../Hooks/MessageContext";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { usePermissions } from "../../context/PermissionsContext";
import Loader from "../commonComponents/Loader";

/**
 * Views for the Workflow component
 */
const VIEWS = {
  LIST: "list",
  BUILDER: "builder",
};

/**
 * Workflow - Main container component
 * @param {Object} props
 * @param {Function} props.onClose - Optional handler to close workflow view
 */
const Workflow = ({ onClose }) => {
  const [currentView, setCurrentView] = useState(VIEWS.LIST);
  const [selectedWorkflow, setSelectedWorkflow] = useState(null);
  const [loadingWorkflow, setLoadingWorkflow] = useState(false);
  const { getWorkflowById } = useWorkflowService();
  const { addMessage } = useMessage();
  const { handleError } = useErrorHandler();
  const { hasPermission } = usePermissions();
  const canUpdateWorkflows = typeof hasPermission === "function" ? hasPermission("update_access.workflows") : false;

  /**
   * Handle creating new workflow
   */
  const handleCreateNew = useCallback(() => {
    setSelectedWorkflow(null);
    setCurrentView(VIEWS.BUILDER);
  }, []);

  /**
   * Handle editing existing workflow - fetches fresh data by ID
   */
  const handleEditWorkflow = useCallback(async (workflowItem) => {
    const workflowId = workflowItem?.workflow_id;
    if (!workflowId) {
      addMessage("Workflow ID not found", "error");
      return;
    }
    setLoadingWorkflow(true);
    try {
      const response = await getWorkflowById(workflowId);
      setSelectedWorkflow(response?.workflow || response);
      setCurrentView(VIEWS.BUILDER);
    } catch (error) {
      handleError(error);
    } finally {
      setLoadingWorkflow(false);
    }
  }, [getWorkflowById, addMessage, handleError]);

  /**
   * Handle going back to list
   */
  const handleBackToList = useCallback(() => {
    setSelectedWorkflow(null);
    setCurrentView(VIEWS.LIST);
  }, []);

  /**
   * Handle successful save
   */
  const handleSaveSuccess = useCallback(() => {
    setSelectedWorkflow(null);
    setCurrentView(VIEWS.LIST);
  }, []);

  useActiveNavClick("/workflows", () => {
    // Reset to list view when workflow nav is clicked while already active
    handleBackToList();
  });

  return (
    <>
      {loadingWorkflow && <Loader />}
      {currentView === VIEWS.LIST ? (
        <WorkflowList onCreateNew={handleCreateNew} onEditWorkflow={handleEditWorkflow} />
      ) : (
        <WorkflowBuilder workflow={selectedWorkflow} onBack={handleBackToList} onSave={handleSaveSuccess} readOnly={!canUpdateWorkflows} />
      )}
    </>
  );
};

export default Workflow;
export { WorkflowList, WorkflowBuilder };