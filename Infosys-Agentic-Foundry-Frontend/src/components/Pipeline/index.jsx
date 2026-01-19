/**
 * Pipeline Component
 *
 * Main entry component for Pipeline management.
 * Handles view switching between list and builder views.
 */

import React, { useState, useCallback } from "react";
import PipelineList from "./PipelineList";
import PipelineBuilder from "./PipelineBuilder";
import styles from "../../css_modules/PipelineBuilder.module.css";

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

  /**
   * Handle creating new pipeline
   */
  const handleCreateNew = useCallback(() => {
    setSelectedPipeline(null);
    setCurrentView(VIEWS.BUILDER);
  }, []);

  /**
   * Handle editing existing pipeline
   */
  const handleEditPipeline = useCallback((pipeline) => {
    setSelectedPipeline(pipeline);
    setCurrentView(VIEWS.BUILDER);
  }, []);

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

  return (
    <>
      {currentView === VIEWS.LIST ? (
        <PipelineList
          onCreateNew={handleCreateNew}
          onEditPipeline={handleEditPipeline}
        />
      ) : (
        <PipelineBuilder
          pipeline={selectedPipeline}
          onBack={handleBackToList}
          onSave={handleSaveSuccess}
        />
      )}
    </>
  );
};

export default Pipeline;
export { PipelineList, PipelineBuilder };