import { useState, useCallback } from "react";

/**
 * useModal - Custom hook for managing modal state in Agentic Pro UI
 *
 * This hook provides a clean API for managing modal visibility and associated data.
 * It's designed to work seamlessly with the FullModal component.
 *
 * Features:
 * - Open/close state management
 * - Data passing to modal
 * - Toggle functionality
 * - Clean state reset on close
 *
 * @param {boolean} initialState - Initial open state (default: false)
 * @returns {Object} Modal state and control functions
 *
 * @example
 * // Basic usage
 * const { isOpen, open, close } = useModal();
 *
 * <button onClick={open}>Open Modal</button>
 * <FullModal isOpen={isOpen} onClose={close}>
 *   Content here
 * </FullModal>
 *
 * @example
 * // With data
 * const { isOpen, open, close, data } = useModal();
 *
 * const handleEditAgent = (agent) => {
 *   open({ agent, mode: "edit" });
 * };
 *
 * <FullModal isOpen={isOpen} onClose={close}>
 *   <p>Editing: {data?.agent?.name}</p>
 * </FullModal>
 *
 * @example
 * // Multiple modals
 * const createModal = useModal();
 * const editModal = useModal();
 *
 * <button onClick={createModal.open}>Create</button>
 * <button onClick={() => editModal.open({ id: 123 })}>Edit</button>
 *
 * <FullModal isOpen={createModal.isOpen} onClose={createModal.close}>
 *   Create form
 * </FullModal>
 *
 * <FullModal isOpen={editModal.isOpen} onClose={editModal.close}>
 *   Edit form for ID: {editModal.data?.id}
 * </FullModal>
 */
const useModal = (initialState = false) => {
  const [isOpen, setIsOpen] = useState(initialState);
  const [data, setData] = useState(null);

  /**
   * Open the modal, optionally with associated data
   * @param {any} modalData - Data to pass to the modal
   */
  const open = useCallback((modalData = null) => {
    setData(modalData);
    setIsOpen(true);
  }, []);

  /**
   * Close the modal and optionally clear data
   * @param {boolean} clearData - Whether to clear data immediately (default: false)
   */
  const close = useCallback((clearData = false) => {
    setIsOpen(false);
    if (clearData) {
      setData(null);
    } else {
      // Delay clearing data to allow exit animations
      setTimeout(() => setData(null), 300);
    }
  }, []);

  /**
   * Toggle the modal open/closed state
   */
  const toggle = useCallback(() => {
    setIsOpen((prev) => !prev);
  }, []);

  /**
   * Update the modal data without affecting open state
   * @param {any} newData - New data to set
   */
  const updateData = useCallback((newData) => {
    setData(newData);
  }, []);

  /**
   * Update specific properties in the modal data
   * @param {Object} updates - Properties to merge into existing data
   */
  const patchData = useCallback((updates) => {
    setData((prev) => (prev ? { ...prev, ...updates } : updates));
  }, []);

  return {
    /** Whether the modal is currently open */
    isOpen,
    /** Open the modal (optionally with data) */
    open,
    /** Close the modal */
    close,
    /** Toggle the modal open/closed */
    toggle,
    /** Data associated with the modal */
    data,
    /** Set/replace the modal data */
    setData,
    /** Update specific properties in modal data */
    updateData,
    /** Merge updates into existing modal data */
    patchData,
  };
};

export default useModal;
