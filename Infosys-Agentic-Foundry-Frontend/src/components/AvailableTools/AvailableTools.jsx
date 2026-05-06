import React, { useEffect, useState, useCallback, useRef } from "react";
import ToolOnBoarding from "./ToolOnBoarding.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import { useToolsAgentsService } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import { usePermissions } from "../../context/PermissionsContext";
import { APIs } from "../../constant";
import useFetch from "../../Hooks/useAxios.js";
import FilterModal from "../commonComponents/FilterModal.jsx";
import SubHeader from "../commonComponents/SubHeader.jsx";
import { debounce } from "lodash";
import { useErrorHandler } from "../../Hooks/useErrorHandler";
import { useActiveNavClick } from "../../events/navigationEvents";
import { useMessage } from "../../Hooks/MessageContext";
import { useAuth } from "../../context/AuthContext";
import { getRoleFromToken, getEmailFromToken } from "../../utils/jwtUtils";
import EmptyState from "../commonComponents/EmptyState.jsx";
import ShareModal from "../commonComponents/ShareModal/ShareModal.jsx";
import GenerateServerModal from "./GenerateServerModal.jsx";
import ImportModal from "./ImportModal.jsx";
import ConflictResolutionModal from "./ConflictResolutionModal.jsx";
import styles from "../../css_modules/AvailableTools.module.css";
import useMultiSelect from "../../Hooks/useMultiSelect.js";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";

const AvailableTools = () => {
  const { loading: permissionsLoading, hasPermission } = usePermissions();

  // Permission checks for CRUD operations - default to false when permissions not loaded
  const canReadTools = typeof hasPermission === "function" ? hasPermission("read_access.tools") : false;
  const canAddTools = typeof hasPermission === "function" ? hasPermission("add_access.tools") : false;
  const canUpdateTools = typeof hasPermission === "function" ? hasPermission("update_access.tools") : false;
  const canDeleteTools = typeof hasPermission === "function" ? hasPermission("delete_access.tools") : false;

  const [toolList, setToolList] = useState([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isAddTool, setIsAddTool] = useState(true);
  const [editTool, setEditTool] = useState({});
  const [loading, setLoading] = useState(false);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [visibleData, setVisibleData] = useState([]);
  const [page, setPage] = useState(1);
  const [filterModal, setFilterModal] = useState(false);
  const [tags, setTags] = useState([]);
  const [selectedTags, setSelectedTags] = useState([]);
  const [selectedToolType, setSelectedToolType] = useState([]); // Changed to array for multi-select
  const [totalToolsCount, setTotalToolsCount] = useState(0);
  const [hasMore, setHasMore] = useState(true); // track if more pages are available
  const [selectedToolIds, setSelectedToolIds] = useState([]); // Selected tools for generate server
  const [showGenerateModal, setShowGenerateModal] = useState(false);

  // Share modal state
  const [shareModalData, setShareModalData] = useState(null);
  const [showShareModal, setShowShareModal] = useState(false); // Generate server modal
  const toolListContainerRef = useRef(null);
  const { fetchData, postData, deleteData } = useFetch();
  const pageRef = useRef(1);
  const [loader, setLoaderState] = useState(false);
  const isLoadingRef = React.useRef(false);
  const [exportLoading, setExportLoading] = useState(false);
  const [importLoading, setImportLoading] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [showConflictModal, setShowConflictModal] = useState(false);
  const [previewData, setPreviewData] = useState(null);
  const [pendingImportFile, setPendingImportFile] = useState(null);
  const [pendingModelName, setPendingModelName] = useState("");
  const [importResultData, setImportResultData] = useState(null);
  const { getToolsAndValidatorsPaginated, calculateDivs, exportTools, importTools, importToolsPreview } = useToolsAgentsService();
  // Track validator tools fetched once (backend returns full list without pagination)
  const validatorToolsRef = useRef([]);
  const hasLoadedValidatorsOnce = useRef(false);
  const { handleError } = useErrorHandler();

  const loggedInUserEmail = getEmailFromToken();
  const role = getRoleFromToken();
  const isAdmin = role?.toLowerCase() === "admin";

  // Created By dropdown state
  const [createdBy, setCreatedBy] = useState("All");

  // Multi-select delete state
  const {
    selectedIds: multiSelectIds,
    selectedCount: multiSelectCount,
    isAllSelected,
    isPartiallySelected,
    handleSelectionChange: handleMultiSelectChange,
    handleSelectAll,
    clearSelection: clearMultiSelection,
  } = useMultiSelect({ data: visibleData, idKey: "tool_id" });
  const [showBulkDeleteModal, setShowBulkDeleteModal] = useState(false);
  const [bulkDeleteLoading, setBulkDeleteLoading] = useState(false);

  // Helper to force re-fetch of validator tools on explicit refreshes (e.g. after adding a validator)
  const resetValidatorsCache = useCallback(() => {
    hasLoadedValidatorsOnce.current = false;
    validatorToolsRef.current = [];
  }, []);

  // Normalize API responses to always return a clean array of tool objects
  const sanitizeToolsResponse = (response) => {
    if (!response) return [];
    // If backend sometimes returns an object instead of array
    if (!Array.isArray(response)) return [];
    // If array contains a single message object with no tool fields, treat as empty
    if (response.length === 1 && response[0] && typeof response[0] === "object" && "message" in response[0] && !("tool_id" in response[0])) {
      return [];
    }
    return response
      .filter((item) => item && typeof item === "object" && ("tool_id" in item || "tool_name" in item))
      .map((item) => {
        let isValidator = false;
        if (item.tool_id) {
          if (String(item.tool_id).startsWith("_validator_")) {
            isValidator = true;
          }
        }
        // Set type with proper title case for badge display
        const type = isValidator ? "Validator" : "Tool";
        return { ...item, is_validator: isValidator, type };
      });
  };

  // Helper function to convert selectedToolType array to show_tools and show_validators params
  const getToolTypeParams = (toolTypeArray) => {
    // Default: show both
    let show_tools = true;
    let show_validators = true;

    if (toolTypeArray && toolTypeArray.length > 0) {
      const hasTools = toolTypeArray.includes("tool");
      const hasValidators = toolTypeArray.includes("validator");

      if (hasTools && !hasValidators) {
        // Only tools selected
        show_tools = true;
        show_validators = false;
      } else if (!hasTools && hasValidators) {
        // Only validators selected
        show_tools = false;
        show_validators = true;
      }
      // If both or neither selected, show both (default)
    }

    return { show_tools, show_validators };
  };

  const handleSearch = async (searchValue, divsCount, pageNumber, tagsToUse = null, toolTypeToUse = null, createdByToUse = null) => {
    setSearchTerm(searchValue || "");
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    setLoading(true);

    try {
      // Use provided params or fall back to state
      const tagsForSearch = tagsToUse !== null ? tagsToUse : selectedTags;
      const typesForSearch = toolTypeToUse !== null ? toolTypeToUse : selectedToolType;
      const { show_tools, show_validators } = getToolTypeParams(typesForSearch);
      // Use createdByToUse if provided, otherwise fall back to state
      const createdByValue = createdByToUse !== null ? createdByToUse : createdBy;
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : createdByValue === "System" ? "system" : undefined;
      const response = await getToolsAndValidatorsPaginated({
        page: pageNumber,
        limit: divsCount,
        search: searchValue ? searchValue : "",
        tags: tagsForSearch?.length > 0 ? tagsForSearch : undefined,
        show_tools,
        show_validators,
        created_by: createdByEmail,
      });
      let dataToSearch = sanitizeToolsResponse(response?.details);
      if (tagsForSearch?.length > 0) {
        dataToSearch = dataToSearch.filter((item) => item.tags && item.tags.some((tag) => tagsForSearch.includes(tag?.tag_name)));
      }
      setTotalToolsCount(response.total_count || 0);
      setVisibleData(dataToSearch);
      setHasMore(dataToSearch.length >= divsCount);
    } catch (error) {
      handleError(error, { context: "AvailableTools.handleSearch" });
      setVisibleData([]); // Clear visibleData on error
      setHasMore(false);
    } finally {
      setLoading(false); // Hide loader
    }
  };

  const getToolsData = async (pageNumber, divsCount, showLoader = true) => {
    return getToolsDataWithTags(pageNumber, divsCount, selectedTags, selectedToolType, null, showLoader);
  };

  const getToolsDataWithTags = async (pageNumber, divsCount, tagsToUse, toolTypeToUse, createdByToUse = null, showLoader = true) => {
    if (showLoader) setLoading(true);
    try {
      const { show_tools, show_validators } = getToolTypeParams(toolTypeToUse);
      // Use createdByToUse if provided, otherwise fall back to state
      const createdByValue = createdByToUse !== null ? createdByToUse : createdBy;
      const createdByEmail = createdByValue === "Me" ? loggedInUserEmail : createdByValue === "System" ? "system" : undefined;
      const response = await getToolsAndValidatorsPaginated({
        page: pageNumber,
        limit: divsCount,
        search: "",
        tags: tagsToUse?.length > 0 ? tagsToUse : undefined,
        show_tools,
        show_validators,
        created_by: createdByEmail,
      });

      // Check if response is an error
      if (!response || response.error || !response.details) {
        console.error("[AvailableTools] API Error or empty response:", response);
        setVisibleData([]);
        setHasMore(false);
        return [];
      }

      const data = sanitizeToolsResponse(response?.details);
      let finalData = data;
      if ((tagsToUse || []).length > 0) {
        finalData = data.filter((item) => item.tags && item.tags.some((tag) => (tagsToUse || []).includes(tag?.tag_name)));
      }
      const currentTotal = response.total_count || data?.length || 0;
      setTotalToolsCount(currentTotal);
      if (pageNumber === 1) {
        setToolList(finalData);
        setVisibleData(finalData);
      } else {
        if (finalData.length > 0) {
          setVisibleData((prev) => {
            const updated = Array.isArray(prev) ? [...prev, ...finalData] : [...finalData];
            if (updated.length >= currentTotal) setHasMore(false);
            return updated;
          });
        }
      }
      if (data.length < divsCount) {
        setHasMore(false);
      } else if (pageNumber === 1) {
        // Reset hasMore on fresh load only when page is full
        setHasMore(true);
      }
      return finalData; // return fetched merged data for caller decisions
    } catch (error) {
      handleError(error, { context: "AvailableTools.getToolsData" });
      if (pageNumber === 1) {
        setToolList([]);
        setVisibleData([]);
      }
      setHasMore(false);
      return [];
    } finally {
      if (showLoader) setLoading(false);
    }
  };

  const clearSearch = () => {
    // Reset all filter states
    setSearchTerm("");
    setSelectedTags([]);
    setSelectedToolType([]);
    setCreatedBy("All");
    setVisibleData([]);
    setHasMore(true);
    setPage(1);
    pageRef.current = 1;

    // Reset validators cache
    resetValidatorsCache();
    setTimeout(() => {
      // Trigger fetchToolsData with no search term and no tags (reset to first page)
      const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
      setPage(1);
      pageRef.current = 1;
      // Call getToolsData with explicitly empty tags
      getToolsDataWithTags(1, divsCount, [], []);
    }, 5);
  };

  useEffect(() => {
    const container = toolListContainerRef?.current;
    if (!container) return;

    // Extract the check logic into a separate function
    const checkAndLoadMore = () => {
      if (
        container.scrollTop + container.clientHeight >= container.scrollHeight - 10 &&
        !loading &&
        !isLoadingMore &&
        !isLoadingRef.current &&
        hasMore // Prevent if no more pages
      ) {
        handleScrollLoadMore();
      }
    };

    const debouncedCheckAndLoad = debounce(checkAndLoadMore, 200); // 200ms debounce

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
  }, [toolListContainerRef, hasMore, loading, isLoadingMore]);

  const handleScrollLoadMore = async () => {
    if (loader || isLoadingRef.current || !hasMore) return; // Prevent multiple calls or if no more data
    isLoadingRef.current = true;
    const nextPage = pageRef.current + 1;
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    try {
      setLoaderState(true);
      setIsLoadingMore(true);
      let newData = [];
      const { show_tools, show_validators } = getToolTypeParams(selectedToolType);
      // Pass created_by value based on filter selection
      const createdByEmail = createdBy === "Me" ? loggedInUserEmail : createdBy === "System" ? "system" : undefined;
      if (searchTerm.trim()) {
        const res = await getToolsAndValidatorsPaginated({
          page: nextPage,
          limit: divsCount,
          search: searchTerm,
          tags: selectedTags?.length > 0 ? selectedTags : undefined,
          show_tools,
          show_validators,
          created_by: createdByEmail,
        });
        newData = sanitizeToolsResponse(res.details);

        if (selectedTags?.length > 0) {
          newData = newData.filter((item) => item.tags && item.tags.some((tag) => selectedTags.includes(tag?.tag_name)));
        }

        if (newData.length > 0) {
          setVisibleData((prev) => {
            const updated = Array.isArray(prev) ? [...prev, ...newData] : [...newData];
            if (updated.length >= totalToolsCount) setHasMore(false);
            return updated;
          });
          // Only increment page if we actually appended data
          setPage(nextPage);
          pageRef.current = nextPage;
        }
        if (newData.length < divsCount) setHasMore(false);
      } else {
        // Only call fetchToolsData if no searchTerm;
        // Pass showLoader=false to avoid full screen loader during pagination
        const appended = await getToolsData(nextPage, divsCount, false);

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
      setIsLoadingMore(false);
      isLoadingRef.current = false;
    }
  };

  const handlePlusIconClick = () => {
    setShowForm(true);
    setIsAddTool(true);
  };

  const getTags = async () => {
    try {
      const data = await fetchData(APIs.GET_TAGS);
      setTags(data);
    } catch (e) {
      console.error(e);
    }
  };

  // Use a ref to ensure tags are fetched only once
  const hasLoadedTagsOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedTagsOnce.current) return;
    hasLoadedTagsOnce.current = true;
    getTags();
  }, [showForm]);

  const hasLoadedOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedOnce.current) return; // prevent duplicate initial load
    hasLoadedOnce.current = true;

    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    pageRef.current = 1;
    setPage(1);
    getToolsData(1, divsCount);
  }, []);

  const handleRefresh = () => {
    setPage(1);
    pageRef.current = 1;
    setSearchTerm("");
    setSelectedTags([]);
    setSelectedToolType([]); // Reset tool type filter
    setCreatedBy("All"); // Reset created by filter
    setVisibleData([]);
    setHasMore(true);
    resetValidatorsCache();
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    // Call getToolsData with explicitly empty tags
    getToolsDataWithTags(1, divsCount, [], []);
  };
  const handleFilter = async (selectedTagsParam, typesParam = null, createdByParam = null) => {
    setSelectedTags(selectedTagsParam);
    // If types parameter is provided, use it; otherwise use current state
    const typesToUse = typesParam !== null ? typesParam : selectedToolType;
    if (typesParam !== null) {
      setSelectedToolType(typesParam);
    }
    // If createdBy parameter is provided, update state
    const createdByToUse = createdByParam !== null ? createdByParam : createdBy;
    if (createdByParam !== null) {
      setCreatedBy(createdByParam);
    }
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);

    // Trigger new API call with selected tags - pass all parameters directly
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    if (searchTerm.trim()) {
      // If there's a search term, use handleSearch with current search, tags, types, and createdBy
      await handleSearch(searchTerm, divsCount, 1, selectedTagsParam, typesToUse, createdByToUse);
    } else {
      // If no search term, fetch data with all filters
      await getToolsDataWithTags(1, divsCount, selectedTagsParam, typesToUse, createdByToUse);
    }
  };

  const handleTypeFilter = async (e) => {
    const types = e.target.value; // array for multi-select
    setSelectedToolType(types);
    setPage(1);
    pageRef.current = 1;
    setVisibleData([]);
    setHasMore(true);
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    if (searchTerm.trim()) {
      await handleSearch(searchTerm, divsCount, 1, selectedTags, types, createdBy);
    } else {
      await getToolsDataWithTags(1, divsCount, selectedTags, types, createdBy);
    }
  };

  // Handler for Created By dropdown - only updates state
  // API call is triggered by handleFilter via onTagsChange/onApply
  const handleCreatedByChange = (value) => { setCreatedBy(value) };

  const fetchPaginatedTools = async (pageNumber = 1, refreshValidators = false) => {
    setVisibleData([]);
    setPage(pageNumber);
    pageRef.current = pageNumber;
    setHasMore(true);
    const divsCount = calculateDivs(toolListContainerRef, 200, 141, 40);
    if (refreshValidators || pageNumber === 1) {
      // If explicitly requested or first page reset, invalidate validator cache so latest validators appear
      resetValidatorsCache();
    }
    // Preserve search term: if search is active, use handleSearch to maintain filtered results
    if (searchTerm.trim()) {
      await handleSearch(searchTerm, divsCount, pageNumber, selectedTags, selectedToolType, createdBy);
    } else {
      await getToolsData(pageNumber, divsCount);
    }
  };

  useActiveNavClick(["/", "/tools"], () => {
    setShowForm((open) => (open ? false : open));
  });
  const { addMessage } = useMessage();
  const { logout } = useAuth();

  if (permissionsLoading) {
    return <Loader />;
  }

  // Tool selection handlers for Generate Server feature
  const handleToolSelect = (toolName, checked) => {
    const tool = visibleData.find((t) => (t.tool_name || t.name) === toolName);
    if (tool) {
      const toolId = tool.id || tool.tool_id;
      setSelectedToolIds((prev) => (checked ? [...prev, toolId] : prev.filter((id) => id !== toolId)));
    }
  };

  const handleGenerateClick = () => {
    if (selectedToolIds.length === 0) return;
    setShowGenerateModal(true);
  };

  const handleExportTools = async () => {
    if (selectedToolIds.length === 0) return;
    setExportLoading(true);
    try {
      const blob = await exportTools(selectedToolIds);
      if (!blob) throw new Error("Failed to export tools");
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `tools_export.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
      addMessage(`${selectedToolIds.length} tool${selectedToolIds.length !== 1 ? "s" : ""} exported successfully!`, "success");
      setSelectedToolIds([]);
    } catch (err) {
      const errorMessage = err?.message || "Export failed";
      addMessage(errorMessage, "error");
    } finally {
      setExportLoading(false);
    }
  };

  const handleImportTools = async (zipFile, modelName) => {
    setImportLoading(true);
    setShowImportModal(false);
    try {
      // Step 1: Call import-preview to check for conflicts
      const previewResponse = await importToolsPreview(zipFile);
      const previewResult = previewResponse?.result || previewResponse;

      // If preview returned an error object (service catches errors and returns { message })
      if (previewResult?.message && !previewResult?.tools && !previewResult?.has_conflicts) {
        const errorDetail = previewResult?.detail || previewResult?.error || "";
        const fullErrorMsg = errorDetail
          ? `${previewResult.message} — ${errorDetail}`
          : previewResult.message;
        addMessage(fullErrorMsg, "error");
        setImportLoading(false);
        return;
      }

      if (previewResult?.has_conflicts) {
        // Conflicts found — show conflict resolution modal
        setPendingImportFile(zipFile);
        setPendingModelName(modelName);
        setPreviewData(previewResult);
        setShowConflictModal(true);
        setImportLoading(false);
        return;
      }

      // No conflicts — proceed directly with import
      await executeImport(zipFile, modelName, "create_new_tool");
    } catch (err) {
      const errorMessage = err?.message || err?.detail || "Import preview failed";
      addMessage(errorMessage, "error");
      setImportLoading(false);
    }
  };

  // Called when user picks an option in the conflict modal
  const handleConflictProceed = async (conflictResolution, nameOverrides = null) => {
    // If user chose "skip", don't call import — just cancel
    if (conflictResolution === "skip") {
      setShowConflictModal(false);
      addMessage("Import skipped by user.", "success");
      setPendingImportFile(null);
      setPendingModelName("");
      setPreviewData(null);
      return;
    }

    setShowConflictModal(false);
    setImportLoading(true);
    try {
      await executeImport(pendingImportFile, pendingModelName, conflictResolution, nameOverrides);
    } finally {
      // Only clear pending data if previewData wasn't re-set by pending conflicts
      // executeImport sets new previewData + showConflictModal when has_pending_conflicts
      // We check importLoading — if still loading, modal was re-opened
    }
  };

  // Shared import execution logic
  const executeImport = async (zipFile, modelName, conflictResolution = "create_new_tool", nameOverrides = null) => {
    try {
      const createdBy = getEmailFromToken();
      const response = await importTools(zipFile, modelName, createdBy, conflictResolution, nameOverrides);

      // If service returned an error object instead of throwing
      if (response?.message && !response?.status && !response?.result) {
        addMessage(response.message, "error");
        return;
      }

      // Check if validation failed — re-open conflict modal with validation errors
      const resultData = response?.result || response || {};
      if (resultData.validation_failed) {
        const validationErrors = resultData.validation_errors || {};
        // Build tools array for ConflictResolutionModal from validation errors
        const toolsFromErrors = Object.entries(validationErrors).map(([toolName, info]) => ({
          tool_name: info.original_name || toolName,
          status: "needs_new_name",
          requires_decision: true,
          message: info.reason || "Please choose a different name.",
          validationError: !info.valid ? info.reason : null,
        }));
        setPreviewData({
          tools: toolsFromErrors,
          has_conflicts: true,
          conflicts_count: toolsFromErrors.length,
          validationErrors: validationErrors,
        });
        setShowConflictModal(true);
        setImportLoading(false);
        addMessage(resultData.message || "Validation failed. Please fix the errors and try again.", "error");
        return;
      }

      // Check if there are still pending conflicts (e.g. user entered a duplicate/invalid name)
      const hasPending = resultData.has_pending_conflicts || response?.has_pending_conflicts;
      const pendingList = resultData.pending_conflicts || response?.pending_conflicts;

      if (hasPending && pendingList && pendingList.length > 0) {
        // Re-open the conflict modal — wrap array into the shape the modal expects
        setPreviewData({
          tools: pendingList,
          has_conflicts: true,
          conflicts_count: pendingList.length,
        });
        setShowConflictModal(true);
        setImportLoading(false);
        return;
      }

      // No more conflicts — clear pending state
      setPendingImportFile(null);
      setPendingModelName("");
      setPreviewData(null);

      // Parse import response
      const result = response?.result || response || {};
      const imported = result.imported || [];
      const failedItems = result.failed || [];
      const mergedToExisting = result.merged_to_existing || [];

      const importedCount = imported.length;
      const failedCount = failedItems.length;
      const mergedCount = mergedToExisting.length;

      // Show detailed results in a dialog
      setImportResultData(result);

      // Refresh tools list to show newly imported / merged tools
      if (importedCount > 0 || mergedCount > 0) {
        handleRefresh();
      }
    } catch (err) {
      const errorMessage = err?.message || err?.detail || "Import failed";
      addMessage(errorMessage, "error");
    } finally {
      setImportLoading(false);
    }
  };

  // Check if any selected tool is a validator (validators can't be converted to MCP)
  const hasSelectedValidators = selectedToolIds.some((id) =>
    visibleData.some((t) => (t.id || t.tool_id) === id && t.is_validator)
  );

  const handleGenerateServer = async (serverName, serverDescription) => {
    setLoading(true);
    try {
      const payload = {
        tool_ids: selectedToolIds,
        server_name: serverName,
        server_description: serverDescription,
        server_type: "file",
      };
      const response = await postData(APIs.MCP_CONVERSION_GENERATE_SERVER, payload);
      if (response) {
        addMessage(response?.message || "Server generated successfully!", "success");
        setSelectedToolIds([]);
        setShowGenerateModal(false);
        // Navigate to servers page
        window.location.href = "/servers";
      }
    } catch (error) {
      // Extract error message from API response
      const errorMessage = error?.response?.data?.detail || error?.message || "Failed to generate server";
      addMessage(errorMessage, "error");
    } finally {
      setLoading(false);
    }
  };

  // Bulk delete handler for multi-select — single API call
  const handleBulkDelete = async () => {
    if (multiSelectIds.length === 0) return;
    setBulkDeleteLoading(true);
    const isAdmin = role && role?.toLowerCase() === "admin";

    try {
      const apiUrl = APIs.DELETE_TOOLS;
      const payload = { tool_ids: multiSelectIds, is_admin: isAdmin, user_email_id: loggedInUserEmail, version: null };
      const response = await deleteData(apiUrl, payload);
      if (response && typeof response !== "string") {
        const statusMsg = response.status_message || response.message;
        if (statusMsg) {
          const hasAnyFailure = Array.isArray(response.results) && response.results.some((r) => r.is_delete === false);
          addMessage(statusMsg, hasAnyFailure ? "error" : "success");
        } else {
          addMessage(`${multiSelectIds.length} tool(s) deleted successfully`, "success");
        }
      } else if (typeof response === "string") {
        addMessage(response, "error");
      }
    } catch (err) {
      const errMsg =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        err?.message ||
        "Failed to delete selected tools. Please try again.";
      addMessage(errMsg, "error");
    } finally {
      clearMultiSelection();
      setShowBulkDeleteModal(false);
      setBulkDeleteLoading(false);
      await fetchPaginatedTools(1);
    }
  };

  return (
    <>
      {showForm && (
        <ToolOnBoarding
          setShowForm={setShowForm}
          isAddTool={isAddTool}
          editTool={editTool}
          setIsAddTool={setIsAddTool}
          tags={tags}
          fetchPaginatedTools={fetchPaginatedTools}
          hideServerTab={true}
          contextType="tools"
          readOnly={!isAddTool && !canUpdateTools}
        />
      )}
      {(loading || exportLoading || importLoading) && <Loader />}
      <div className={"pageContainer"}>
        <SubHeader
          heading={"Tools"}
          activeTab={"tools"}
          searchValue={searchTerm}
          onSearch={(value) => handleSearch(value, calculateDivs(toolListContainerRef, 200, 141, 40), 1)}
          onPlusClick={canAddTools ? handlePlusIconClick : undefined}
          showPlusButton={canAddTools}
          handleRefresh={handleRefresh}
          selectedTags={selectedTags}
          clearSearch={clearSearch}
          showTagsDropdown={true}
          availableTags={tags.map((tag) => tag.tag_name || tag)}
          selectedTagsForDropdown={selectedTags}
          onTagsChange={handleFilter}
          handleTypeFilter={handleTypeFilter}
          selectedAgentType={selectedToolType}
          showCreatedByDropdown={true}
          createdBy={createdBy}
          onCreatedByChange={handleCreatedByChange}
          secondaryButtonLabel={canAddTools ? "Convert to MCP" : undefined}
          onSecondaryButtonClick={canAddTools ? handleGenerateClick : undefined}
          secondaryButtonDisabled={canAddTools ? (selectedToolIds.length === 0 || hasSelectedValidators) : true}
          secondaryButtonTitle={hasSelectedValidators ? "Validators cannot be converted to MCP" : ""}
          tertiaryButtonLabel={canAddTools ? "Export" : undefined}
          onTertiaryButtonClick={canAddTools ? handleExportTools : undefined}
          tertiaryButtonDisabled={selectedToolIds.length === 0 || exportLoading}
          tertiaryButtonTitle={selectedToolIds.length === 0 ? "Select tools to export" : ""}
          quaternaryButtonLabel={canAddTools ? "Import" : undefined}
          onQuaternaryButtonClick={canAddTools ? () => setShowImportModal(true) : undefined}
          quaternaryButtonDisabled={importLoading}
          quaternaryButtonTitle="Import tools from a zip file"
          showSelectAll={canDeleteTools && isAdmin && visibleData.length > 1}
          isAllSelected={isAllSelected}
          isPartiallySelected={isPartiallySelected}
          onSelectAll={handleSelectAll}
          selectedCount={multiSelectCount}
          onDeleteSelected={canDeleteTools && isAdmin ? () => setShowBulkDeleteModal(true) : null}
          deleteSelectedLabel="Delete"
        />

        {/* Display total count summary */}
        <SummaryLine visibleCount={visibleData.length} totalCount={totalToolsCount} />
        <div className="listWrapper" ref={toolListContainerRef}>
          {visibleData?.length > 0 && (
            <DisplayCard1
              data={visibleData}
              onCardClick={canReadTools ? (_cardName, item) => {
                setEditTool(item);
                setShowForm(true);
                setIsAddTool(false);
              } : undefined}
              onInfoClick={() => { }}
              cardNameKey="tool_name"
              cardDescriptionKey="tool_description"
              cardCategoryKey="type"
              contextType="tool"
              onCreateClick={canAddTools ? handlePlusIconClick : undefined}
              showCreateCard={false}
              showCheckbox={canDeleteTools || canAddTools}
              onSelectionChange={(name, checked) => {
                // Update both multi-select (for delete) and tool select (for MCP conversion)
                handleMultiSelectChange(name, checked);
                if (canAddTools) handleToolSelect(name, checked);
              }}
              selectedIds={multiSelectIds}
              idKey="tool_id"
              hideActions={!canReadTools}
              onShareClick={(item) => {
                setShareModalData(item);
                setShowShareModal(true);
              }}
            />
          )}
          {/* Display EmptyState when filters are active but no results */}
          {(searchTerm.trim() || selectedTags.length > 0 || selectedToolType.length > 0 || (createdBy && createdBy !== "All")) && visibleData.length === 0 && !loading && (
            <EmptyState
              filters={[
                ...selectedTags,
                ...selectedToolType.map((type) => (type === "tool" ? "Tools" : "Validator")),
                ...(createdBy === "Me" ? ["Created By: Me"] : []),
                ...(searchTerm.trim() ? [`Search: ${searchTerm}`] : []),
              ]}
              onClearFilters={clearSearch}
              onCreateClick={canAddTools ? handlePlusIconClick : undefined}
              createButtonLabel={canAddTools ? "New Tool" : undefined}
            />
          )}
          {/* Display EmptyState when no data exists from backend (no filters applied) */}
          {!searchTerm.trim() && selectedTags.length === 0 && selectedToolType.length === 0 && createdBy === "All" && visibleData.length === 0 && !loading && (
            <EmptyState
              message="No tools found"
              subMessage={canAddTools ? "Get started by creating your first tool" : "No tools available"}
              onCreateClick={canAddTools ? handlePlusIconClick : undefined}
              createButtonLabel={canAddTools ? "New Tool" : undefined}
              showClearFilter={false}
            />
          )}
          {/* Loading more indicator for pagination */}
          {isLoadingMore && <div className={styles.loadingMore}>Loading more...</div>}
        </div>
      </div>

      {showImportModal && (
        <ImportModal
          type="tools"
          onClose={() => setShowImportModal(false)}
          onImport={handleImportTools}
          loading={importLoading}
        />
      )}

      {showConflictModal && previewData && (
        <ConflictResolutionModal
          previewData={previewData}
          validationErrors={previewData?.validationErrors || null}
          onClose={() => {
            setShowConflictModal(false);
            setPreviewData(null);
            setPendingImportFile(null);
            setPendingModelName("");
          }}
          onProceed={handleConflictProceed}
          loading={importLoading}
        />
      )}

      {showGenerateModal && (
        <GenerateServerModal
          onClose={() => setShowGenerateModal(false)}
          onGenerate={handleGenerateServer}
          loading={loading}
          selectedCount={selectedToolIds.length}
        />
      )}

      <ShareModal
        show={showShareModal}
        onClose={() => setShowShareModal(false)}
        itemData={shareModalData}
        entityType="tool"
      />

      {showBulkDeleteModal && (
        <ConfirmationModal
          message={`Deleting the ${multiSelectCount} selected tool(s) will permanently remove all versions associated with them. Do you wish to proceed?`}
          onConfirm={handleBulkDelete}
          setShowConfirmation={setShowBulkDeleteModal}
        />
      )}

      {importResultData && (
        <ConfirmationModal
          message={importResultData.message || "Import complete."}
          onConfirm={() => setImportResultData(null)}
          setShowConfirmation={() => setImportResultData(null)}
          confirmLabel="OK"
          hideCancel
        />
      )}

    </>
  );
};

export default AvailableTools;
