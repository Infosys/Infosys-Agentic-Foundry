import { useState, useEffect, useRef } from "react";
import { usePermissions } from "../../context/PermissionsContext";
import styles from "./Vault.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import { APIs } from "../../constant";
import { copyToClipboard } from "../../utils/clipboardUtils";
import Cookies from "js-cookie";
import Loader from "../commonComponents/Loader";
import SubHeader from "../commonComponents/SubHeader";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import Button from "../../iafComponents/GlobalComponents/Buttons/Button";
import CodeEditor from "../commonComponents/CodeEditor";
import codeEditorStyles from "../commonComponents/CodeEditor.module.css";

// Constants for SAST/DAST compliance - string literals stored as constants
const LABELS = {
  VAULT_ITEM_LABEL: "Secret",
  ADD_NEW_VAULT_ITEM: "Secrets",
  PRIVATE: "Private",
  PUBLIC: "Public",
  GROUP: "Group",
  NAME: "Name",
  VALUE: "Value",
  PYTHON: "Python",
};

// Configuration constants
const AUTO_MASK_TIMEOUT = 30000;
const MAX_VALUE_LENGTH = 10000;
const MAX_NAME_LENGTH = 255;

const Vault = () => {
  const { permissions, loading: permissionsLoading, hasPermission } = usePermissions();
  const lastRowRef = useRef(null);
  const { postData, putData, deleteData, fetchData } = useFetch();
  const role = Cookies.get("role");
  const { addMessage } = useMessage();
  // Separate caches for each tab to prevent value interchange
  const privateVaultCache = useRef({});
  const publicVaultCache = useRef({});
  const groupVaultCache = useRef({});
  // Single timer for auto-masking (only one item visible at a time)
  const autoMaskTimer = useRef(null);
  // Track which item is currently visible (index and tab)
  const currentVisibleIndex = useRef(null);
  const currentVisibleTab = useRef(null);

  // Sanitize vault value to prevent XSS and limit length
  const sanitizeVaultValue = (value) => {
    if (!value) return "";
    // Convert to string and limit length
    const sanitized = String(value).substring(0, MAX_VALUE_LENGTH);
    return sanitized;
  };

  // Get the appropriate cache based on current tab
  const getVaultCache = (tab) => {
    switch (tab) {
      case "Private":
        return privateVaultCache;
      case "Public":
        return publicVaultCache;
      case "Group":
        return groupVaultCache;
      default:
        return privateVaultCache;
    }
  };

  // Clear all scts from all caches and reset timer
  const clearAllSctsFromCache = () => {
    privateVaultCache.current = {};
    publicVaultCache.current = {};
    groupVaultCache.current = {};
    if (autoMaskTimer.current) {
      clearTimeout(autoMaskTimer.current);
      autoMaskTimer.current = null;
    }
    currentVisibleIndex.current = null;
    currentVisibleTab.current = null;
  };

  // Clear specific item from cache
  const clearSctFromCache = (index, tab) => {
    const cache = getVaultCache(tab);
    delete cache.current[index];
    if (currentVisibleIndex.current === index && currentVisibleTab.current === tab) {
      if (autoMaskTimer.current) {
        clearTimeout(autoMaskTimer.current);
        autoMaskTimer.current = null;
      }
      currentVisibleIndex.current = null;
      currentVisibleTab.current = null;
    }
  };

  // Hide the currently visible item (used when showing a new one or changing tabs)
  const hideCurrentlyVisibleItem = (newRows = null) => {
    if (currentVisibleIndex.current !== null && currentVisibleTab.current !== null) {
      const prevIndex = currentVisibleIndex.current;
      const prevTab = currentVisibleTab.current;
      const cache = getVaultCache(prevTab);

      // Clear from cache
      delete cache.current[prevIndex];

      // Clear timer
      if (autoMaskTimer.current) {
        clearTimeout(autoMaskTimer.current);
        autoMaskTimer.current = null;
      }

      // Update rows to mask the previously visible item
      // Only if the previous tab matches current activeTab
      setRows((prevRows) => {
        const updatedRows = [...prevRows];
        if (updatedRows[prevIndex] && prevTab === activeTab) {
          updatedRows[prevIndex].isMasked = true;
          updatedRows[prevIndex].value = "";
          // Reset isUpdated to restore Eye/Delete icons
          updatedRows[prevIndex].isUpdated = false;
          // Restore original value in case user made edits
          updatedRows[prevIndex].name = updatedRows[prevIndex].originalName;
        }
        return updatedRows;
      });

      currentVisibleIndex.current = null;
      currentVisibleTab.current = null;
    }
  };

  // Auto-mask after 30 seconds - only one item visible at a time
  const scheduleAutoMask = (index, tab) => {
    // Clear any existing timer
    if (autoMaskTimer.current) {
      clearTimeout(autoMaskTimer.current);
    }

    // Track the currently visible item
    currentVisibleIndex.current = index;
    currentVisibleTab.current = tab;

    // Set new timer
    autoMaskTimer.current = setTimeout(() => {
      const cache = getVaultCache(tab);
      setRows((prevRows) => {
        const updatedRows = [...prevRows];
        if (updatedRows[index]) {
          updatedRows[index].isMasked = true;
          updatedRows[index].value = "";
          // Reset isUpdated to restore Eye/Delete icons
          updatedRows[index].isUpdated = false;
          // Restore original name in case user made edits
          updatedRows[index].name = updatedRows[index].originalName;
        }
        return updatedRows;
      });
      delete cache.current[index];
      currentVisibleIndex.current = null;
      currentVisibleTab.current = null;
      addMessage("Secret automatically hidden for security.", "success");
    }, AUTO_MASK_TIMEOUT);
  };

  const [rows, setRows] = useState(() => {
    const role = Cookies.get("role");
    return role?.toUpperCase() === "GUEST" ? [] : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }];
  });
  const [activeTab, setActiveTab] = useState("Private");
  const [showConfirmation, setShowConfirmation] = useState(false);
  const [deleteIndex, setDeleteIndex] = useState(null);
  const [availableGroups, setAvailableGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState("");
  const [selectedGroupObj, setSelectedGroupObj] = useState(null);
  const [groupSearchTerm, setGroupSearchTerm] = useState("");
  const [appliedGroupSearchTerm, setAppliedGroupSearchTerm] = useState("");
  const [showGroupDropdown, setShowGroupDropdown] = useState(false);
  const [highlightedGroupIndex, setHighlightedGroupIndex] = useState(-1);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");

  /* eslint-disable react-hooks/exhaustive-deps */
  // Fetch vault data when active tab changes - dependencies intentionally limited to activeTab
  useEffect(() => {
    setLoading(true);
    // Clear search term when switching tabs
    setSearchTerm("");
    // Clear all scts and timers when tab changes
    clearAllSctsFromCache();

    const fetchVaultData = async () => {
      let data;
      let formatted;
      if (activeTab === LABELS.PUBLIC) {
        data = await getPublicScripts();
        formatted = Array.isArray(data)
          ? data.map((item) => ({
            name: item.name || "",
            value: "",
            isSaved: true,
            isMasked: true,
            isUpdated: false,
            originalName: item.name || "",
            originalValue: "",
          }))
          : [];
      } else if (activeTab === LABELS.GROUP) {
        data = await getGroupScripts();
        formatted = Array.isArray(data)
          ? data.map((item) => ({
            name: item.name || "",
            value: "",
            isSaved: true,
            isMasked: true,
            isUpdated: false,
            originalName: item.name || "",
            originalValue: "",
          }))
          : [];
      } else {
        data = await getScripts();
        const vaultItems = data || {};

        formatted = Object.entries(vaultItems).map(([key, value]) => ({
          name: String(value || "").substring(0, MAX_NAME_LENGTH),
          value: "",
          isSaved: true,
          isMasked: true,
          isUpdated: false,
          originalName: String(value || "").substring(0, MAX_NAME_LENGTH),
          originalValue: "",
        }));
      }
      setRows(
        formatted.length
          ? formatted
          : role?.toUpperCase() !== "GUEST"
            ? [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]
            : [],
      );

      setLoading(false);
    };
    fetchVaultData();
  }, [activeTab]);
  /* eslint-enable react-hooks/exhaustive-deps */

  useEffect(() => {
    if (role?.toUpperCase() !== "GUEST" && rows.length === 0) {
      setRows([{ name: "", value: "", isSaved: false, isMasked: true }]);
    }
  }, [role, rows.length]);

  // Cleanup timer on unmount
  useEffect(() => {
    return () => {
      if (autoMaskTimer.current) {
        clearTimeout(autoMaskTimer.current);
      }
    };
  }, []);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (role && role?.toUpperCase() === "GUEST") {
      setActiveTab("Public");
    }
  }, [role]);

  useEffect(() => {
    if (showGroupDropdown && highlightedGroupIndex >= 0) {
      const element = document.querySelector(`[data-group-index="${highlightedGroupIndex}"]`);
      if (element) {
        element.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
          inline: "nearest",
        });
      }
    }
  }, [highlightedGroupIndex, showGroupDropdown]);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (showGroupDropdown && !event.target.closest("[data-group-dropdown]")) {
        setShowGroupDropdown(false);
        setHighlightedGroupIndex(-1);
      }
    };
    if (showGroupDropdown) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showGroupDropdown]);

  useEffect(() => {
    if (activeTab === "Group") {
      setSelectedGroup("");
      setSelectedGroupObj(null);
      setRows([]);
      fetchAvailableGroups();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  useEffect(() => {
    if (activeTab === "Group" && !selectedGroup) {
      setRows([]);
    }
  }, [activeTab, selectedGroup]);

  const pythonVaultExample = `# Example: Using user and public secrets to build a secure API request URL

def fetch_weather(city):
    api_key = get_user_secrets('weather_api_key', 'no_api_key_found')
    base_url = get_public_secrets('weather_api_base_url', 'https://default-weather-api.com')
    full_url = f"{base_url}/weather?city={city}&apikey={api_key}"
    return f"Ready to fetch data from: {full_url}"

print(fetch_weather("New York"))`;

  const groupPythonVaultExample = `# Example: Using group secrets to build a secure API request URL

def fetch_weather(city):
    api_key = get_group_secrets('Group_name', 'weather_api_key', 'no_api_key_found')
    base_url = get_group_secrets('Group_name', 'weather_api_base_url', 'https://default-weather-api.com')
    full_url = f"{base_url}/weather?city={city}&apikey={api_key}"
    return f"Ready to fetch data from: {full_url}"

print(fetch_weather("New York"))`;

  // Select the appropriate code example based on active tab
  const activeCodeExample = activeTab === LABELS.GROUP ? groupPythonVaultExample : pythonVaultExample;

  const isRowComplete = (row) => row.name.trim() !== "" && row.value.trim() !== "";

  const handleInputChange = (index, field, value) => {
    const updatedRows = [...rows];
    updatedRows[index][field] = value;
    if (updatedRows[index].isSaved) {
      updatedRows[index].isUpdated = true;
    }
    setRows(updatedRows);
  };

  const addRow = () => {
    setRows((prevRows) => {
      const newRows = [...prevRows, { name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }];
      return newRows;
    });
  };

  // Ensure rows are initialized for non-guest users if empty (side effect, not during render)
  useEffect(() => {
    if (role?.toUpperCase() !== "GUEST" && rows.length === 0) {
      setRows([{ name: "", value: "", isSaved: false, isMasked: true }]);
    }
  }, [role, rows.length]);
  const saveRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!row.name || !row.value) {
      addMessage("Both fields are required.", "error");
      setLoading(false);
      return;
    }

    const res = {
      user_email: Cookies.get("email"),
      key_name: row.name,
      key_value: row.value,
    };

    let response;
    try {
      response = await postData(APIs.ADD_SECRET, res);
      await response;
      updatedRows[index].isSaved = true;
      updatedRows[index].isMasked = true;
      updatedRows[index].originalName = row.name;
      updatedRows[index].originalValue = row.value;
      setRows(updatedRows);
      addMessage(response.message, "success");
    } catch (error) {
      console.error("Error saving secret:", error);
      addMessage("Error saving secret", "error");
    } finally {
      setLoading(false);
    }
  };

  const savePublicRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!row.name || !row.value) {
      addMessage("Both fields are required.", "error");
      setLoading(false);
      return;
    }

    const res = {
      key_name: row.name,
      key_value: row.value,
    };

    let response;
    try {
      response = await postData(APIs.PUBLIC_ADD_SECRET, res);
      await response;
      updatedRows[index].isSaved = true;
      updatedRows[index].isMasked = true;
      updatedRows[index].originalName = row.name;
      updatedRows[index].originalValue = row.value;
      setRows(updatedRows);
      addMessage(response.message, "success");
    } catch (error) {
      console.error("Error saving public secret:", error);
      addMessage("Error saving secret.", "error");
    } finally {
      setLoading(false);
    }
  };

  const saveGroupRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!selectedGroup) {
      addMessage("Please select a group first.", "error");
      setLoading(false);
      return;
    }

    if (!row.name || !row.value) {
      addMessage("Both fields are required.", "error");
      setLoading(false);
      return;
    }

    const payload = {
      key_name: row.name,
      secret_value: row.value,
    };

    try {
      // Use the group-specific vault items endpoint
      const apiUrl = APIs.GROUP_ADD_SECRET.replace("{group_name}", encodeURIComponent(selectedGroup));
      const response = await postData(apiUrl, payload);

      // 201 status means "Created" - this is successful for POST requests
      if (response) {
        updatedRows[index].isSaved = true;
        updatedRows[index].isMasked = true;
        updatedRows[index].originalName = row.name;
        updatedRows[index].originalValue = row.value;
        setRows(updatedRows);
        addMessage(`Secret added to group "${selectedGroup}" successfully`, "success");
      }
    } catch (error) {
      console.error("Error creating group secret:", error);
      const errorMessage = error?.response?.details || error?.details || error?.message || "Error creating group secret.";
      addMessage(errorMessage, "error");
    } finally {
      setLoading(false);
    }
  };

  const deleteRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const rowToDelete = updatedRows[index];

    if (!rowToDelete.isSaved) {
      updatedRows.splice(index, 1);
      setRows(updatedRows);
      setLoading(false);
      return;
    }

    const res = {
      user_email: Cookies.get("email"),
      key_name: rowToDelete.name,
    };

    let response;
    try {
      response = await deleteData(APIs.DELETE_SECRET, res);
      await response;
      updatedRows.splice(index, 1);
      setRows(updatedRows.length ? updatedRows : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
      addMessage(response.message, "success");
    } catch (error) {
      console.error("Error deleting secret:", error);
      addMessage("Error deleting secret.", "error");
    } finally {
      setLoading(false);
      setShowConfirmation(false);
      setDeleteIndex(null);
    }
  };

  const deletePublicRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const rowToDelete = updatedRows[index];

    if (!rowToDelete.isSaved) {
      updatedRows.splice(index, 1);
      setRows(updatedRows);
      setLoading(false);
      return;
    }

    const res = { key_name: rowToDelete.name };

    let response;
    try {
      response = await deleteData(APIs.PUBLIC_DELETE_SECRET, res);
      await response;
      updatedRows.splice(index, 1);
      setRows(updatedRows.length ? updatedRows : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
      addMessage(response.message, "success");
    } catch (error) {
      console.error("Error deleting secret:", error);
      addMessage("Error deleting secret.", "error");
    } finally {
      setLoading(false);
      setShowConfirmation(false);
      setDeleteIndex(null);
    }
  };

  const deleteGroupRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const rowToDelete = updatedRows[index];

    if (!rowToDelete.isSaved) {
      updatedRows.splice(index, 1);
      setRows(updatedRows);
      setLoading(false);
      return;
    }

    if (!selectedGroup) {
      addMessage("Please select a group first.", "error");
      setLoading(false);
      setShowConfirmation(false);
      setDeleteIndex(null);
      return;
    }

    try {
      // Use the group-specific endpoint for deleting
      const apiUrl = APIs.GROUP_DELETE_SECRET
        .replace("{group_name}", encodeURIComponent(selectedGroup))
        .replace("{key_name}", encodeURIComponent(rowToDelete.originalName || rowToDelete.name));
      const response = await deleteData(apiUrl);

      // Check for successful response - API might return different response formats
      if (response === true || response?.success === true || response?.status === "success" || (response && typeof response === "object" && Object.keys(response).length === 0)) {
        // Refresh the group to ensure UI is in sync with server
        await loadGroupData(selectedGroup);
        addMessage("Group secret deleted successfully", "success");
      } else {
        // Unexpected delete response format; still refresh in case the delete actually worked
        await loadGroupData(selectedGroup);
        addMessage("Delete operation completed", "success");
      }
    } catch (error) {
      console.error("Error deleting group secret:", error);
      const errorMessage = error?.response?.details || error?.details || error?.message || "Error deleting group secret.";
      addMessage(errorMessage, "error");
    } finally {
      setLoading(false);
      setShowConfirmation(false);
      setDeleteIndex(null);
    }
  };

  const handleDeleteClick = (index) => {
    const row = rows[index];
    if (!row.isSaved || (role && role?.toUpperCase() === "GUEST")) return;
    setDeleteIndex(index);
    setShowConfirmation(true);
  };

  const handleConfirmDelete = () => {
    if (deleteIndex !== null) {
      if (activeTab === "Private") {
        deleteRow(deleteIndex);
      } else if (activeTab === "Group") {
        deleteGroupRow(deleteIndex);
      } else {
        deletePublicRow(deleteIndex);
      }
    }
  };

  const cancelUpdate = (index) => {
    const updatedRows = [...rows];
    updatedRows[index].name = updatedRows[index].originalName;
    updatedRows[index].value = updatedRows[index].originalValue;
    updatedRows[index].isUpdated = false;
    updatedRows[index].isMasked = true;
    setRows(updatedRows);
  };

  const updateRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!row.name || !row.value) {
      addMessage("Both fields are required.", "error");
      setLoading(false);
      return;
    }

    const res = {
      user_email: Cookies.get("email"),
      key_name: row.name,
      key_value: row.value,
    };

    let response;
    try {
      response = await putData(APIs.UPDATE_SECRET, res);

      await response;
      updatedRows[index].isUpdated = false;
      updatedRows[index].isMasked = true;
      updatedRows[index].originalName = row.name;
      updatedRows[index].originalValue = row.value;
      setRows(updatedRows);
      addMessage(response.message, "success");
    } catch (error) {
      console.error("Error updating secret:", error);
      addMessage("Error updating secret.", "error");
    } finally {
      setLoading(false);
    }
  };

  const updatePublicRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!row.name || !row.value) {
      addMessage("Both fields are required.", "error");
      setLoading(false);
      return;
    }

    const res = {
      key_name: row.name,
      key_value: row.value,
    };

    let response;
    try {
      response = await putData(APIs.PUBLIC_UPDATE_SECRET, res);
      await response;
      updatedRows[index].isUpdated = false;
      updatedRows[index].isMasked = true;
      updatedRows[index].originalName = row.name;
      updatedRows[index].originalValue = row.value;
      setRows(updatedRows);
      addMessage(response.message, "success");
    } catch (error) {
      console.error("Error updating public secret:", error);
      addMessage("Error updating secret.", "error");
    } finally {
      setLoading(false);
    }
  };

  const updateGroupRow = async (index) => {
    setLoading(true);
    const updatedRows = [...rows];
    const row = updatedRows[index];

    if (!selectedGroup) {
      addMessage("Please select a group first.", "error");
      setLoading(false);
      return;
    }

    if (!row.name || !row.value) {
      addMessage("Both fields are required.", "error");
      setLoading(false);
      return;
    }

    const payload = {
      secret_value: row.value,
    };

    try {
      // Use the group-specific endpoint for updating
      const apiUrl = APIs.GROUP_UPDATE_SECRET
        .replace("{group_name}", encodeURIComponent(selectedGroup))
        .replace("{key_name}", encodeURIComponent(row.originalName));
      const response = await putData(apiUrl, payload);

      if (response) {
        updatedRows[index].isUpdated = false;
        updatedRows[index].isMasked = true;
        updatedRows[index].originalName = row.name;
        updatedRows[index].originalValue = row.value;
        setRows(updatedRows);
        addMessage("Group secret updated successfully", "success");
      }
    } catch (error) {
      console.error("Error updating group secret:", error);
      const errorMessage = error?.response?.details || error?.details || error?.message || "Error updating group secret.";
      addMessage(errorMessage, "error");
    } finally {
      setLoading(false);
    }
  };

  const getEyeVaultItems = async (name, index, copy) => {
    setLoading(true);
    try {
      // Hide any previously visible item first
      hideCurrentlyVisibleItem();

      const apiUrl = APIs.SECRETS_GET;
      const payload = {
        user_email: Cookies.get("email"),
        key_name: name,
      };

      const response = await postData(apiUrl, payload);

      if (response?.success) {
        const rawValue = sanitizeVaultValue(response["key_value"] || "");

        if (copy === "copy") {
          // For copy, don't store in state - just copy to clipboard
          const success = await copyToClipboard(rawValue);
          if (success) {
            addMessage("Secret value copied to clipboard!", "success");
          } else {
            addMessage("Failed to copy to clipboard", "error");
          }

          // Clear clipboard after timeout for security
          setTimeout(async () => {
            try {
              await copyToClipboard("");
            } catch (err) {
              console.warn("Could not clear clipboard");
            }
          }, AUTO_MASK_TIMEOUT);
        } else {
          // Store in tab-specific secure cache
          privateVaultCache.current[index] = rawValue;

          const updatedRows = [...rows];
          updatedRows[index].isMasked = false;
          updatedRows[index].value = rawValue; // Store value for editing
          updatedRows[index].originalValue = rawValue;
          setRows(updatedRows);

          // Schedule auto-mask after 30 seconds
          scheduleAutoMask(index, "Private");
        }
      } else {
        addMessage("Failed to retrieve secret value", "error");
      }
    } catch (error) {
      console.error("Error fetching secret value:", error);
      addMessage("Error fetching secret value.", "error");
    } finally {
      setLoading(false);
    }
  };

  const getPublicVaultList = async (name, index, copy) => {
    setLoading(true);
    try {
      // Hide any previously visible item first
      hideCurrentlyVisibleItem();

      const apiUrl = APIs.PUBLIC_SECRETS_GET;
      const payload = { key_name: name };

      const response = await postData(apiUrl, payload);

      if (response?.success) {
        const sanitizedValue = sanitizeVaultValue(response.key_value || "");

        if (copy === "copy") {
          // For copy, don't store in state - just copy to clipboard
          const success = await copyToClipboard(sanitizedValue);
          if (success) {
            addMessage("Secret value copied to clipboard!", "success");
          } else {
            addMessage("Failed to copy to clipboard", "error");
          }
        } else {
          // Store in tab-specific secure cache
          publicVaultCache.current[index] = sanitizedValue;

          const updatedRows = [...rows];
          updatedRows[index].isMasked = false;
          updatedRows[index].value = sanitizedValue; // Store value for editing
          updatedRows[index].originalValue = sanitizedValue;
          setRows(updatedRows);

          // Schedule auto-mask after 30 seconds
          scheduleAutoMask(index, "Public");
        }
      } else {
        addMessage("Failed to retrieve secret value", "error");
      }
    } catch (error) {
      console.error("Error fetching secret value:", error);
      addMessage("Error fetching secret value.", "error");
    } finally {
      setLoading(false);
    }
  };

  // Load secrets for the selected group
  const loadGroupData = async (groupName) => {
    if (!groupName || typeof groupName !== "string") {
      addMessage("Invalid group name provided.", "error");
      return;
    }

    setLoading(true);
    try {
      const apiUrl = APIs.GET_GROUP_SECRETS.replace("{group_name}", encodeURIComponent(groupName));
      const response = await fetchData(apiUrl);

      // Handle different possible response formats
      let secretsData = [];
      if (response) {
        // Check multiple possible response structures
        if (response.secrets && Array.isArray(response.secrets)) {
          secretsData = response.secrets;
        } else if (response.data && Array.isArray(response.data)) {
          secretsData = response.data;
        } else if (Array.isArray(response)) {
          secretsData = response;
        } else if (response.success === false) {
          // API returned an error response
          throw new Error(response.message || "Failed to load group secrets");
        }
      }

      if (secretsData.length > 0) {
        const dataRows = secretsData
          .map((secret, index) => {
            // Validate the object structure
            if (!secret || typeof secret !== "object") {
              console.warn(`Invalid object at index ${index}:`);
              return null;
            }

            return {
              name: secret.key_name || secret.name || secret.key || "",
              value: secret.secret_value || secret.key_value || secret.value || secret.secret || "",
              isSaved: true,
              isMasked: true,
              isUpdated: false,
              originalName: secret.key_name || secret.name || secret.key || "",
              originalValue: secret.secret_value || secret.key_value || secret.value || secret.secret || "",
            };
          })
          .filter(Boolean); // Remove any null entries

        setRows(dataRows.length > 0 ? dataRows : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
      } else {
        // No group secrets found, show empty row for adding new ones
        setRows([{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
      }
    } catch (error) {
      console.error("Error loading group secrets:", error);
      const errorMessage = error?.response?.data?.detail || error?.response?.data?.message || error?.message || "Error loading group secrets.";
      addMessage(errorMessage, "error");
      setRows([{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
    } finally {
      setLoading(false);
    }
  };

  const getGroupVaults = async (keyName, index, copy) => {
    if (!selectedGroup || !keyName) {
      addMessage("Please select a group and ensure key name is provided.", "error");
      return;
    }

    if (typeof keyName !== "string" || keyName.trim() === "") {
      addMessage("Invalid key name provided.", "error");
      return;
    }

    setLoading(true);
    try {
      // Hide any previously visible item first
      hideCurrentlyVisibleItem();

      // Use GET request with URL parameters
      const apiUrl = APIs.GROUP_SECRETS_GET
        .replace("{group_name}", encodeURIComponent(selectedGroup))
        .replace("{key_name}", encodeURIComponent(keyName));
      const response = await fetchData(apiUrl);

      if (response) {
        // Handle the response - could be direct value or object with secret_value/key_value
        let groupVaultData = "";
        if (typeof response === "string") {
          groupVaultData = response;
        } else if (response && typeof response === "object") {
          if ("secret_value" in response) {
            groupVaultData = response["secret_value"];
          } else if ("key_value" in response) {
            groupVaultData = response["key_value"];
          } else if ("value" in response) {
            groupVaultData = response.value;
          } else if (response.data && "secret_value" in response.data) {
            groupVaultData = response["data"]["secret_value"];
          } else if (response.data && "key_value" in response.data) {
            groupVaultData = response["data"]["key_value"];
          } else {
            groupVaultData = "No secret value found";
          }
        } else {
          groupVaultData = "No secret value found";
        }

        if (copy === "copy") {
          const success = await copyToClipboard(groupVaultData);
          if (success) {
            addMessage("Secret value copied to clipboard!", "success");
          } else {
            addMessage("Failed to copy to clipboard", "error");
          }
        } else {
          // Store in tab-specific secure cache
          groupVaultCache.current[index] = groupVaultData;

          const updatedRows = [...rows];
          updatedRows[index].isMasked = false;
          updatedRows[index].value = groupVaultData; // Store value for editing
          updatedRows[index].originalValue = groupVaultData;
          setRows(updatedRows);

          // Schedule auto-mask after 30 seconds
          scheduleAutoMask(index, "Group");
        }
      } else {
        addMessage("Failed to retrieve secret value", "error");
      }
    } catch (error) {
      console.error("Error fetching group secret:", error);
      const errorMessage = error?.response?.data?.detail || error?.response?.data?.message || error?.message || `Error fetching group secret value.`;
      addMessage(errorMessage, "error");
    } finally {
      setLoading(false);
    }
  };
  useEffect(() => {
    if (role && role?.toUpperCase() === "GUEST") {
      setActiveTab("Public");
    }
  }, [role]);

  // Auto-scroll when highlighted group index changes
  useEffect(() => {
    if (showGroupDropdown && highlightedGroupIndex >= 0) {
      const element = document.querySelector(`[data-group-index="${highlightedGroupIndex}"]`);
      if (element) {
        element.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
          inline: "nearest",
        });
      }
    }
  }, [highlightedGroupIndex, showGroupDropdown]);

  // Click outside handler to close dropdown
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (showGroupDropdown && !event.target.closest("[data-group-dropdown]")) {
        setShowGroupDropdown(false);
        setHighlightedGroupIndex(-1);
      }
    };

    if (showGroupDropdown) {
      document.addEventListener("mousedown", handleClickOutside);
      return () => document.removeEventListener("mousedown", handleClickOutside);
    }
  }, [showGroupDropdown]);

  // Load groups when Group tab is selected
  useEffect(() => {
    if (activeTab === "Group") {
      // Clear any previous selection when switching to Group tab
      setSelectedGroup("");
      setSelectedGroupObj(null);
      setRows([]);
      fetchAvailableGroups();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  // Reset rows when switching to Group tab without selection
  useEffect(() => {
    if (activeTab === "Group" && !selectedGroup) {
      setRows([]);
    }
  }, [activeTab, selectedGroup]);

  const toggleMask = (index) => {
    const updatedRows = [...rows];
    const wasMasked = updatedRows[index].isMasked;
    updatedRows[index].isMasked = !wasMasked;

    // Clear vault value from memory when masking
    if (!wasMasked) {
      updatedRows[index].value = "";
      // Reset isUpdated to restore Eye/Delete icons
      updatedRows[index].isUpdated = false;
      // Restore original name in case user made edits
      updatedRows[index].name = updatedRows[index].originalName;
      clearSctFromCache(index, activeTab);
    }

    setRows(updatedRows);
  };

  const getScripts = async () => {
    setLoading(true);
    try {
      const apiUrl = APIs.GET_SECRETS;
      const payload = {
        user_email: Cookies.get("email"),
      };
      const response = await postData(apiUrl, payload);

      if (response?.success) {
        setLoading(false);

        // Sanitize and validate names
        const sanitizedSctNames = Array.isArray(response.key_names) ? response.key_names.map((name) => sanitizeVaultValue(name)) : [];

        setRows(sanitizedSctNames.length ? sanitizedSctNames : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);

        return sanitizedSctNames;
      } else {
        return null;
      }
    } catch (error) {
      console.error("Error fetching VAULT values");
      return null;
    }
  };
  const getPublicScripts = async () => {
    setLoading(true);
    try {
      const apiUrl = APIs.GET_PUBLIC_SECRETS;

      const response = await postData(apiUrl);

      if (response.success) {
        setLoading(false);
        setRows(
          response.public_key_names.length
            ? response.public_key_names
            : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }],
        );

        // setRows(response.data.secrets)
        return response.public_key_names;
      } else {
        return null;
      }
    } catch (error) {
      console.error("Error fetching publicScripts:", error);
      return null;
    }
  };

  const fetchAvailableGroups = async () => {
    try {
      const userEmail = Cookies.get("email");
      const userRole = Cookies.get("role");

      if (!userEmail) {
        addMessage("User email not found. Please log in again.", "error");
        return [];
      }

      // Super admin gets all groups, regular users get their assigned groups
      const roleUpper = userRole ? userRole.toUpperCase().replace(/\s+/g, "") : "";
      const isSuperAdmin = roleUpper === "SUPERADMIN" || roleUpper === "SUPER_ADMIN";

      const apiUrl = isSuperAdmin
        ? `${APIs.GET_GROUPS}`
        : `${APIs.GET_GROUPS_BY_USER}${encodeURIComponent(userEmail)}`;

      const response = await fetchData(apiUrl);

      // Handle different response structures
      let groupsData = [];
      if (response) {
        if (Array.isArray(response.details)) {
          groupsData = response.details;
        } else if (Array.isArray(response.groups)) {
          groupsData = response.groups;
        } else if (Array.isArray(response.data)) {
          groupsData = response.data;
        } else if (Array.isArray(response)) {
          groupsData = response;
        } else if (response.success && Array.isArray(response.details)) {
          groupsData = response.details;
        } else if (response.success && Array.isArray(response.groups)) {
          groupsData = response.groups;
        }
      }

      // Validate group objects - check for both group_name and domain_name for backward compatibility
      const validGroups = groupsData.filter((group) => {
        if (!group || typeof group !== "object") return false;
        return group.group_name || group.domain_name;
      });

      setAvailableGroups(validGroups);

      if (validGroups.length === 0) {
        addMessage("No groups found. Create a group first.", "error");
      }

      return validGroups;
    } catch (error) {
      console.error("Error fetching available groups:", error);
      const errorMessage = error?.response?.data?.detail || error?.response?.data?.message || error?.message || "Error loading groups. Please try again.";
      addMessage(errorMessage, "error");
      setAvailableGroups([]);
      return [];
    }
  };

  // Filtered groups based on applied search term (search on Enter or button click)
  const filteredGroups = Array.isArray(availableGroups)
    ? availableGroups.filter((group) => {
      const name = group.group_name || group.domain_name || "";
      return name.toLowerCase().includes(appliedGroupSearchTerm.toLowerCase());
    })
    : [];

  // Group dropdown helper functions
  const handleGroupSelection = (group) => {
    const groupName = group?.group_name || group?.domain_name;
    if (!group || !groupName) {
      addMessage("Invalid group selection.", "error");
      return;
    }

    try {
      setSelectedGroup(groupName);
      setSelectedGroupObj(group);
      setGroupSearchTerm("");
      setAppliedGroupSearchTerm("");
      setShowGroupDropdown(false);
      setHighlightedGroupIndex(-1);

      // Load secrets for the selected group
      loadGroupData(groupName);
    } catch (error) {
      console.error("Error in handleGroupSelection:", error);
      const errorMessage = error?.response?.details || error?.details || error?.message || "Error selecting group.";
      addMessage(errorMessage, "error");
    }
  };

  const handleGroupDropdownToggle = () => {
    try {
      const newShowState = !showGroupDropdown;
      setShowGroupDropdown(newShowState);

      if (newShowState && selectedGroupObj) {
        const selectedName = selectedGroupObj.group_name || selectedGroupObj.domain_name;
        if (selectedName) {
          // Find the selected group in the filtered list and highlight it
          const selectedIndex = filteredGroups.findIndex((group) => {
            const gName = group?.group_name || group?.domain_name;
            return gName === selectedName;
          });
          if (selectedIndex !== -1) {
            setHighlightedGroupIndex(selectedIndex);
          }
        }
      } else if (!newShowState) {
        setHighlightedGroupIndex(-1);
      }
    } catch (error) {
      console.error("Error in handleGroupDropdownToggle:", error);
      setShowGroupDropdown(false);
      setHighlightedGroupIndex(-1);
    }
  };

  // Handle keyboard navigation for group dropdown
  const handleGroupKeyDown = (event) => {
    try {
      if (!showGroupDropdown) {
        if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
          event.preventDefault();
          setShowGroupDropdown(true);
          setHighlightedGroupIndex(0);
        }
        return;
      }

      const maxIndex = filteredGroups.length - 1;

      switch (event.key) {
        case "ArrowDown":
          event.preventDefault();
          setHighlightedGroupIndex((prev) => (prev < maxIndex ? prev + 1 : prev));
          break;
        case "ArrowUp":
          event.preventDefault();
          setHighlightedGroupIndex((prev) => (prev > 0 ? prev - 1 : prev));
          break;
        case "Enter":
          event.preventDefault();
          if (highlightedGroupIndex >= 0 && highlightedGroupIndex < filteredGroups.length && filteredGroups[highlightedGroupIndex]) {
            handleGroupSelection(filteredGroups[highlightedGroupIndex]);
          }
          break;
        case "Escape":
          event.preventDefault();
          setShowGroupDropdown(false);
          setHighlightedGroupIndex(-1);
          break;
        default:
          break;
      }
    } catch (error) {
      console.error("Error in handleGroupKeyDown:", error);
      setShowGroupDropdown(false);
      setHighlightedGroupIndex(-1);
    }
  };

  const getGroupScripts = async () => {
    setLoading(true);
    try {
      // First fetch available groups
      await fetchAvailableGroups();

      // If no group is selected, show empty rows
      if (!selectedGroup) {
        setLoading(false);
        setRows([{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
        return [];
      }

      // Fetch secrets for the selected group
      await loadGroupData(selectedGroup);
      setLoading(false);
      return [];
    } catch (error) {
      console.error("Error fetching group data:", error);
      setLoading(false);
      return null;
    }
  };

  // Permission checks (after all hooks and helper functions)
  if (permissionsLoading) {
    return <Loader />;
  }
  // Prefer using hasPermission helper if available
  const vaultAllowed =
    typeof hasPermission === "function"
      ? hasPermission("vault_access")
      : !((permissions && permissions.vault && permissions.vault.vault_access === false) || (permissions && permissions.vault_access === false));
  if (!vaultAllowed) {
    return <div className={styles.noPermissionMessage}>You do not have permission to access the vault.</div>;
  }

  // Handle search from SubHeader
  const handleSearch = (value) => {
    setSearchTerm(value);
  };

  // Handle clear search
  const clearSearch = () => {
    setSearchTerm("");
  };

  return (
    <>
      {loading && <Loader />}
      <div className={"pageContainer"}>
        <SubHeader
          heading={"Vault"}
          activeTab={"vault"}
          searchValue={searchTerm}
          onSearch={handleSearch}
          clearSearch={clearSearch}
          showRefreshButton={false}
          showPlusButton={false}
        />

        {/* Tabs Section */}
        <div className={styles.tabsContainer}>
          {role && role?.toUpperCase() !== "GUEST" && (
            <button className={activeTab === LABELS.PRIVATE ? styles.activeTab : styles.tab} onClick={() => setActiveTab(LABELS.PRIVATE)}>
              {LABELS.PRIVATE}
            </button>
          )}
          <button className={activeTab === LABELS.PUBLIC ? styles.activeTab : styles.tab} onClick={() => setActiveTab(LABELS.PUBLIC)}>
            {LABELS.PUBLIC}
          </button>
          {role && role?.toUpperCase() !== "GUEST" && (
            <button className={activeTab === LABELS.GROUP ? styles.activeTab : styles.tab} onClick={() => setActiveTab(LABELS.GROUP)}>
              {LABELS.GROUP}
            </button>
          )}
        </div>

        {/* Group Selection Dropdown - Show at top of Group tab */}
        {activeTab === LABELS.GROUP && (
          <div className={styles.groupSelectionContainer}>
            {availableGroups.length === 0 ? (
              <div className={styles.noGroupsMessage}>No groups available. Create a group first.</div>
            ) : (
              <div className={styles.groupDropdownContainer} data-group-dropdown>
                <div
                  className={`${styles.groupDropdownTrigger} ${showGroupDropdown ? styles.groupDropdownTriggerActive : ""}`}
                  onClick={handleGroupDropdownToggle}
                  onKeyDown={handleGroupKeyDown}
                  tabIndex={0}
                  role="combobox"
                  aria-expanded={showGroupDropdown}
                  aria-haspopup="listbox"
                  aria-controls="group-dropdown-list">
                  <span className={styles.groupDropdownText}>{selectedGroupObj ? (selectedGroupObj.group_name || selectedGroupObj.domain_name) : "Select Group..."}</span>
                  <span className={`${styles.dropdownChevron} ${showGroupDropdown ? styles.dropdownChevronRotated : ""}`}>
                    <SVGIcons icon="chevron-down" width={16} height={16} color="currentColor" />
                  </span>
                </div>

                {showGroupDropdown && (
                  <div className={styles.groupDropdownContent} onClick={(e) => e.stopPropagation()}>
                    <div className={styles.groupSearchWrapper}>
                      <TextField
                        placeholder="Search groups..."
                        value={groupSearchTerm}
                        onChange={(e) => setGroupSearchTerm(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            // If a group is highlighted, select it; otherwise trigger search
                            if (highlightedGroupIndex >= 0 && highlightedGroupIndex < filteredGroups.length) {
                              handleGroupSelection(filteredGroups[highlightedGroupIndex]);
                            } else {
                              setAppliedGroupSearchTerm(groupSearchTerm);
                            }
                          } else if (e.key === "ArrowDown") {
                            e.preventDefault();
                            setHighlightedGroupIndex((prev) => (prev < filteredGroups.length - 1 ? prev + 1 : prev));
                          } else if (e.key === "ArrowUp") {
                            e.preventDefault();
                            setHighlightedGroupIndex((prev) => (prev > 0 ? prev - 1 : 0));
                          } else if (e.key === "Escape") {
                            setShowGroupDropdown(false);
                            setHighlightedGroupIndex(-1);
                          }
                        }}
                        onClear={() => {
                          setGroupSearchTerm("");
                          setAppliedGroupSearchTerm("");
                        }}
                        showClearButton={true}
                        showSearchButton={true}
                        onSearch={() => setAppliedGroupSearchTerm(groupSearchTerm)}
                        autoComplete="off"
                      />
                    </div>
                    <div id="group-dropdown-list" className={styles.groupDropdownList}>
                      {filteredGroups.length > 0 ? (
                        filteredGroups.map((group, groupIndex) => {
                          const gName = group.group_name || group.domain_name;
                          const gDesc = group.description || group.group_description;
                          return (
                            <div
                              key={gName}
                              data-group-index={groupIndex}
                              className={`${styles.groupDropdownItem} ${groupIndex === highlightedGroupIndex ? styles.groupDropdownItemHighlighted : ""}`}
                              onClick={() => handleGroupSelection(group)}
                              onMouseEnter={() => setHighlightedGroupIndex(groupIndex)}
                              onMouseLeave={() => setHighlightedGroupIndex(-1)}
                              role="option"
                              aria-selected={selectedGroup === gName}>
                              <div className={styles.groupDropdownItemName}>{gName}</div>
                              {gDesc && <div className={styles.groupDropdownItemDesc}>{gDesc}</div>}
                            </div>
                          );
                        })
                      ) : (
                        <div className={styles.groupDropdownEmpty}>No groups found</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            )}
            {selectedGroupObj && (
              <div className={styles.selectedGroupInfo}>
                Selected Group: <strong>{selectedGroupObj.group_name || selectedGroupObj.domain_name}</strong>
              </div>
            )}
          </div>
        )}

        {/* Main Content - Two Column Grid */}
        <div className={styles.sctWrapper}>
          {/* Left Section - Secrets */}
          <div className={styles.secretsSection}>
            <label className="label-desc">Secrets</label>

            <div className={styles.addSctCard}>
              <div className={styles.secretsHeader}>
                <Button
                  type="primary"
                  icon={<SVGIcons icon="plus" width={16} height={16} color="currentColor" />}
                  onClick={() => {
                    if (role?.toUpperCase() === "GUEST") return;
                    if (activeTab === LABELS.GROUP && !selectedGroup) return;
                    // Only add new row if all existing rows are saved
                    if (!rows.some((row) => !row.isSaved)) addRow();
                  }}
                  disabled={role?.toUpperCase() === "GUEST" || rows.some((row) => !row.isSaved) || (activeTab === LABELS.GROUP && !selectedGroup)}
                  title={
                    activeTab === LABELS.GROUP && !selectedGroup
                      ? "Please select a group first."
                      : rows.some((row) => !row.isSaved)
                        ? "Please save the current secret before adding another."
                        : role?.toUpperCase() === "GUEST"
                          ? "Guests cannot add new values."
                          : "Add Secret"
                  }>
                  New Secret
                </Button>
              </div>

              <div className={styles.sctsContainer}>
                {activeTab === LABELS.GROUP && !selectedGroupObj ? (
                  <div className={styles.selectGroupMessage}>
                    <div className={styles.selectGroupContent}>
                      <div className={styles.selectGroupTitle}>Select a Group</div>
                      <div className={styles.selectGroupSubtitle}>Choose a group from the dropdown above to view and manage its secrets.</div>
                    </div>
                  </div>
                ) : rows.length === 0 && role?.toUpperCase() === "GUEST" ? (
                  <div className={styles.noSctsMessage}>There are no secrets to display.</div>
                ) : (
                  // Sort rows: unsaved items appear at TOP, saved ones below
                  // Filter rows by searchTerm (case-insensitive)
                  [...rows]
                    .map((row, originalIndex) => ({ row, originalIndex }))
                    .filter(({ row }) => {
                      if (!searchTerm.trim()) return true;
                      return row.name.toLowerCase().includes(searchTerm.toLowerCase());
                    })
                    .sort((a, b) => {
                      // Unsaved rows come first (at top)
                      if (!a.row.isSaved && b.row.isSaved) return -1;
                      if (a.row.isSaved && !b.row.isSaved) return 1;
                      return 0;
                    })
                    .map(({ row, originalIndex }, displayIndex) => {
                      const isLast = displayIndex === rows.length - 1;

                      if (row.isSaved && row.isMasked) {
                        // Collapsed view - shows name, masked value, and eye/delete buttons in one row
                        return (
                          <div className={styles.savedSctCard} key={originalIndex} ref={isLast ? lastRowRef : null}>
                            <div className={styles.savedSctRow}>
                              <span className={styles.savedSctName}>{row.name}</span>
                              <span className={styles.savedSctDivider}></span>
                              <span className={styles.savedSctValue}>
                                ••••••••••••••••••
                              </span>
                              <div className={styles.sctCardActions}>
                                {/* View Button */}
                                <button
                                  className={`${styles.actionBtn} ${styles.viewBtn}`}
                                  title={role && role?.toUpperCase() === "GUEST" ? "Guests are not allowed to view secrets." : "Show Secret"}
                                  onClick={
                                    role && role?.toUpperCase() === "GUEST"
                                      ? null
                                      : () => {
                                        if (activeTab === LABELS.PRIVATE) {
                                          getEyeVaultItems(row.name, originalIndex, "");
                                        } else if (activeTab === LABELS.GROUP) {
                                          getGroupVaults(row.name, originalIndex, "");
                                        } else {
                                          getPublicVaultList(row.name, originalIndex, "");
                                        }
                                      }
                                  }
                                  disabled={role && role?.toUpperCase() === "GUEST"}>
                                  <SVGIcons icon="eye" width={16} height={16} color="currentColor" />
                                </button>

                                {/* Delete Button */}
                                <button
                                  className={`${styles.actionBtn} ${styles.deleteBtn}`}
                                  title={role && role?.toUpperCase() === "GUEST" ? "Guests are not allowed to delete secrets." : "Delete"}
                                  onClick={() => handleDeleteClick(originalIndex)}
                                  disabled={role && role?.toUpperCase() === "GUEST"}>
                                  <SVGIcons icon="trash" width={16} height={16} color="currentColor" />
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      }

                      // Revealed saved secret - editable value with update/cancel when changed
                      if (row.isSaved && !row.isMasked) {
                        const revealedValue = getVaultCache(activeTab).current[originalIndex] || row.value || "";
                        return (
                          <div className={`${styles.savedSctCard} ${styles.revealedCard}`} key={originalIndex} ref={isLast ? lastRowRef : null}>
                            <div className={styles.savedSctRow}>
                              <span className={styles.savedSctName}>{row.name}</span>
                              <span className={styles.savedSctDivider}></span>
                              <input
                                type="text"
                                value={row.value || revealedValue}
                                onChange={(e) => {
                                  const newValue = e.target.value.substring(0, MAX_VALUE_LENGTH);
                                  handleInputChange(originalIndex, "value", newValue);
                                }}
                                className={`${styles.inlineInput} ${styles.valueInput}`}
                                placeholder="Secret value"
                                disabled={role?.toUpperCase() === "GUEST"}
                              />
                              <div className={styles.sctCardActions}>
                                {row.isUpdated ? (
                                  <>
                                    {/* Update Button */}
                                    <button
                                      className={`${styles.actionBtn} ${styles.saveBtn}`}
                                      title="Update"
                                      onClick={() => {
                                        if (activeTab === LABELS.PRIVATE) {
                                          updateRow(originalIndex);
                                        } else if (activeTab === LABELS.GROUP) {
                                          updateGroupRow(originalIndex);
                                        } else {
                                          updatePublicRow(originalIndex);
                                        }
                                      }}
                                      disabled={!row.value?.trim()}>
                                      <SVGIcons icon="save" width={16} height={16} color="currentColor" />
                                    </button>
                                    {/* Cancel Button */}
                                    <button
                                      className={`${styles.actionBtn} ${styles.deleteBtn}`}
                                      title="Cancel"
                                      onClick={() => cancelUpdate(originalIndex)}>
                                      <SVGIcons icon="x" width={16} height={16} color="currentColor" />
                                    </button>
                                  </>
                                ) : (
                                  <>
                                    {/* Hide Button */}
                                    <button
                                      className={`${styles.actionBtn} ${styles.viewBtn}`}
                                      title="Hide Secret"
                                      onClick={() => toggleMask(originalIndex)}>
                                      <SVGIcons icon="eye-slash" width={16} height={16} color="currentColor" />
                                    </button>

                                    {/* Delete Button */}
                                    <button
                                      className={`${styles.actionBtn} ${styles.deleteBtn}`}
                                      title={role && role?.toUpperCase() === "GUEST" ? "Guests are not allowed to delete secrets." : "Delete"}
                                      onClick={() => handleDeleteClick(originalIndex)}
                                      disabled={role && role?.toUpperCase() === "GUEST"}>
                                      <SVGIcons icon="trash" width={16} height={16} color="currentColor" />
                                    </button>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>
                        );
                      }

                      // Inline form - For new (unsaved) vault items
                      // Same row format as saved secrets

                      return (
                        <div className={`${styles.savedSctCard} ${styles.newSecretCard}`} key={originalIndex} ref={isLast ? lastRowRef : null}>
                          <div className={styles.savedSctRow}>
                            <input
                              type="text"
                              value={row.name}
                              placeholder="Secret name"
                              onChange={(e) => handleInputChange(originalIndex, "name", e.target.value)}
                              className={styles.inlineInput}
                            />
                            <span className={styles.savedSctDivider}></span>
                            <input
                              type="text"
                              value={row.value}
                              placeholder="Secret value"
                              onChange={(e) => {
                                const newValue = e.target.value.substring(0, MAX_VALUE_LENGTH);
                                handleInputChange(originalIndex, "value", newValue);
                              }}
                              className={`${styles.inlineInput} ${styles.valueInput}`}
                            />
                            <div className={styles.sctCardActions}>
                              {/* Save Button */}
                              {role?.toUpperCase() !== "GUEST" && (
                                <button
                                  className={`${styles.actionBtn} ${styles.saveBtn}`}
                                  title="Save"
                                  onClick={() => {
                                    if (activeTab === LABELS.PRIVATE) {
                                      saveRow(originalIndex);
                                    } else if (activeTab === LABELS.GROUP) {
                                      saveGroupRow(originalIndex);
                                    } else {
                                      savePublicRow(originalIndex);
                                    }
                                  }}
                                  disabled={!isRowComplete(row)}>
                                  <SVGIcons icon="save" width={16} height={16} color="currentColor" />
                                </button>
                              )}
                              {/* Remove Button */}
                              <button
                                className={`${styles.actionBtn} ${styles.deleteBtn}`}
                                title="Remove"
                                onClick={() => {
                                  const newRows = [...rows];
                                  newRows.splice(originalIndex, 1);
                                  setRows(newRows);
                                }}>
                                <SVGIcons icon="x" width={16} height={16} color="currentColor" />
                              </button>
                            </div>
                          </div>
                        </div>
                      );
                    })
                )}
              </div>
            </div>
          </div>

          {/* Right Section - Code Snippet */}
          {role?.toUpperCase() !== "GUEST" && (
            <div className={styles.codeSnippetSection}>
              <label className="label-desc">Access your secret keys in {LABELS.PYTHON} via:</label>
              <div className={codeEditorStyles.codeEditorContainer}>
                <CodeEditor codeToDisplay={activeCodeExample} readOnly={true} mode="python" />
                <button
                  type="button"
                  className={codeEditorStyles.copyIcon}
                  title="Copy code"
                  onClick={async () => {
                    const success = await copyToClipboard(activeCodeExample);
                    if (success) {
                      addMessage("Code copied to clipboard!", "success");
                    } else {
                      addMessage("Failed to copy to clipboard", "error");
                    }
                  }}>
                  <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="var(--icon-color)" />
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
      {showConfirmation && (
        <ConfirmationModal
          message={
            activeTab === "Group"
              ? "Are you sure you want to delete this domain? This action cannot be undone."
              : "Are you sure you want to delete this secret? This action cannot be undone."
          }
          onConfirm={handleConfirmDelete}
          setShowConfirmation={setShowConfirmation}
        />
      )}
    </>
  );
};

export default Vault;
