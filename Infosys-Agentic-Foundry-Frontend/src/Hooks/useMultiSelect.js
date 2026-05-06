import { useState, useCallback, useMemo } from "react";

/**
 * useMultiSelect - Reusable hook for managing multi-select state with "Select All" and bulk delete.
 *
 * @param {Object} options
 * @param {Array} options.data - The currently visible data array
 * @param {string} options.idKey - The key used to extract each item's unique ID (e.g., "tool_id", "agentic_application_id")
 * @returns {Object} Multi-select state and handlers
 *
 * Usage:
 *   const { selectedIds, isAllSelected, handleSelectionChange, handleSelectAll, clearSelection } = useMultiSelect({ data, idKey: "tool_id" });
 */
const useMultiSelect = ({ data = [], idKey = "id" }) => {
  const [selectedIds, setSelectedIds] = useState([]);

  // Extract ID from an item, trying multiple fallback keys
  const getItemId = useCallback(
    (item) => {
      if (!item) return null;
      return item[idKey] || item.id || item.tool_id || item.agentic_application_id || item.workflow_id || item.kb_id || item.group_name || item.access_key || null;
    },
    [idKey]
  );

  // All valid IDs from visible data
  const allIds = useMemo(() => {
    return data.map((item) => getItemId(item)).filter(Boolean);
  }, [data, getItemId]);

  // Whether all visible items are selected
  const isAllSelected = useMemo(() => {
    return allIds.length > 0 && allIds.every((id) => selectedIds.includes(id));
  }, [allIds, selectedIds]);

  // Whether some (but not all) items are selected — useful for indeterminate checkbox state
  const isPartiallySelected = useMemo(() => {
    return selectedIds.length > 0 && !isAllSelected;
  }, [selectedIds, isAllSelected]);

  // Toggle individual item selection — matches Card.jsx onSelectionChange(name, checked) signature
  const handleSelectionChange = useCallback(
    (nameOrId, checked) => {
      // Find the item by name or ID to get the actual ID
      const item = data.find((d) => {
        const itemId = getItemId(d);
        const itemName =
          d.tool_name || d.agentic_application_name || d.agent_name || d.name || d.workflow_name || d.group_name || d.kb_name || d.access_key || "";
        return itemName === nameOrId || String(itemId) === String(nameOrId);
      });

      const id = item ? getItemId(item) : nameOrId;
      if (!id) return;

      setSelectedIds((prev) => (checked ? [...prev.filter((i) => i !== id), id] : prev.filter((i) => i !== id)));
    },
    [data, getItemId]
  );

  // Select All / Deselect All toggle
  const handleSelectAll = useCallback(
    (checked) => {
      if (checked) {
        setSelectedIds(allIds);
      } else {
        setSelectedIds([]);
      }
    },
    [allIds]
  );

  // Clear all selections
  const clearSelection = useCallback(() => {
    setSelectedIds([]);
  }, []);

  // Get the count of selected items
  const selectedCount = selectedIds.length;

  return {
    selectedIds,
    selectedCount,
    isAllSelected,
    isPartiallySelected,
    handleSelectionChange,
    handleSelectAll,
    clearSelection,
  };
};

export default useMultiSelect;
