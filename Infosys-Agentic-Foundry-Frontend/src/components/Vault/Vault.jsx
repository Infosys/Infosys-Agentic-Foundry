import { useState, useEffect, useRef } from "react";
import { usePermissions } from "../../context/PermissionsContext";
import styles from "./Vault.module.css";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faEye, faTrash, faEyeSlash, faTimes } from "@fortawesome/free-solid-svg-icons";
import { APIs } from "../../constant";
import Cookies from "js-cookie";
import Loader from "../commonComponents/Loader";
import SVGIcons from "../../Icons/SVGIcons";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios";
import CodeEditor from "../commonComponents/CodeEditor.jsx";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";

const Vault = () => {
  const { permissions, loading: permissionsLoading, hasPermission } = usePermissions();
  const lastRowRef = useRef(null);
  const { postData, putData, deleteData, fetchData } = useFetch();
  const containerRef = useRef(null);
  const role = Cookies.get("role");
  const { addMessage } = useMessage();
  // Separate caches for each tab to prevent value interchange
  const privateVaultCache = useRef({});
  const publicVaultCache = useRef({});
  const groupVaultCache = useRef({});
  // Single timer for auto-masking (only one secret visible at a time)
  const autoMaskTimer = useRef(null);
  // Track which secret is currently visible (index and tab)
  const currentVisibleIndex = useRef(null);
  const currentVisibleTab = useRef(null);

  // Sanitize vault value to prevent XSS and limit length
  const sanitizeVaultValue = (value) => {
    if (!value) return "";
    // Convert to string and limit length to 10000 characters
    const sanitized = String(value).substring(0, 10000);
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

  // Clear all secrets from all caches and reset timer
  const clearAllSecretsFromCache = () => {
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

  // Clear specific secret from cache
  const clearSecretFromCache = (index, tab) => {
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

  // Hide the currently visible secret (used when showing a new one or changing tabs)
  const hideCurrentlyVisibleSecret = (newRows = null) => {
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

      // Update rows to mask the previously visible secret
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

  // Auto-mask after 30 seconds - only one secret visible at a time
  const scheduleAutoMask = (index, tab) => {
    // Clear any existing timer
    if (autoMaskTimer.current) {
      clearTimeout(autoMaskTimer.current);
    }

    // Track the currently visible secret
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
    }, 30000); // 30 seconds
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
  const [showGroupDropdown, setShowGroupDropdown] = useState(false);
  const [highlightedGroupIndex, setHighlightedGroupIndex] = useState(-1);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    // Clear all secrets and timers when tab changes
    clearAllSecretsFromCache();

    const fetchVaultData = async () => {
      let data;
      let formatted;
      if (activeTab === "Public") {
        data = await getPublicScripts();
        formatted = Array.isArray(data)
          ? data.map((item) => ({
              name: item.name || "",
              value: "", // Update this if you have actual vault values
              isSaved: true,
              isMasked: true,
              isUpdated: false,
              originalName: item.name || "",
              originalValue: "",
            }))
          : [];
      } else if (activeTab === "Group") {
        data = await getGroupScripts();
        formatted = Array.isArray(data)
          ? data.map((item) => ({
              name: item.name || "",
              value: "", // Update this if you have actual value
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
          name: String(value || "").substring(0, 255),
          value: "",
          isSaved: true,
          isMasked: true,
          isUpdated: false,
          originalName: String(value || "").substring(0, 255),
          originalValue: "",
        }));
      }
      setRows(
        formatted.length
          ? formatted
          : role?.toUpperCase() !== "GUEST"
          ? [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]
          : []
      );

      setLoading(false);
    };
    fetchVaultData();
  }, [activeTab]);

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

    const res = {
      key_name: row.name,
      key_value: row.value,
    };

    try {
      // Use the domain-specific secrets endpoint
      const apiUrl = `/domains/${encodeURIComponent(selectedGroup)}/secrets`;
      const response = await postData(apiUrl, res);

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
      // Use the domain-specific endpoint for deleting
      const apiUrl = `/domains/${encodeURIComponent(selectedGroup)}/secrets/${encodeURIComponent(rowToDelete.originalName || rowToDelete.name)}`;
      const response = await deleteData(apiUrl);

      // Check for successful response - API might return different response formats
      if (response === true || response?.success === true || response?.status === "success" || (response && typeof response === "object" && Object.keys(response).length === 0)) {
        // Refresh the domain to ensure UI is in sync with server
        await loadDomainData(selectedGroup);
        addMessage("Group secret deleted successfully", "success");
      } else {
        // Unexpected delete response format; still refresh in case the delete actually worked
        await loadDomainData(selectedGroup);
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

  // Tool toggle not used in Vault; removed to avoid undefined state

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

    const res = {
      key_name: row.name,
      key_value: row.value,
    };

    try {
      // Use the domain-specific endpoint for updating
      const apiUrl = `/domains/${encodeURIComponent(selectedGroup)}/secrets/${encodeURIComponent(row.originalName)}`;
      const response = await putData(apiUrl, res);

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
      // Hide any previously visible secret first
      hideCurrentlyVisibleSecret();

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
          await navigator.clipboard.writeText(rawValue);
          addMessage("Secret value copied to clipboard!", "success");

          // Clear clipboard after 30 seconds for security
          setTimeout(async () => {
            try {
              await navigator.clipboard.writeText("");
            } catch (err) {
              console.warn("Could not clear clipboard");
            }
          }, 30000);
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
      // Hide any previously visible secret first
      hideCurrentlyVisibleSecret();

      const apiUrl = APIs.PUBLIC_SECRETS_GET;
      const payload = { key_name: name };

      const response = await postData(apiUrl, payload);

      if (response?.success) {
        const sanitizedValue = sanitizeVaultValue(response.key_value || "");

        if (copy === "copy") {
          // For copy, don't store in state - just copy to clipboard
          await navigator.clipboard.writeText(sanitizedValue);
          addMessage("Secret value copied to clipboard!", "success");
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

  // Load values for the selected domain
  const loadDomainData = async (domainName) => {
    if (!domainName || typeof domainName !== "string") {
      addMessage("Invalid domain name provided.", "error");
      return;
    }

    setLoading(true);
    try {
      const apiUrl = `/domains/${encodeURIComponent(domainName)}/secrets`;
      const response = await fetchData(apiUrl);

      // Handle different possible response formats
      let domainData = [];
      if (response) {
        // Check multiple possible response structures
        if (response.domainData && Array.isArray(response.domainData)) {
          domainData = response.secrets;
        } else if (response.data && Array.isArray(response.data)) {
          domainData = response.data;
        } else if (Array.isArray(response)) {
          domainData = response;
        } else if (response.success === false) {
          // API returned an error response
          throw new Error(response.message || "Failed to load domain domainData");
        }
      }

      if (domainData.length > 0) {
        const dataRows = domainData
          .map((secret, index) => {
            // Validate the object structure
            if (!secret || typeof secret !== "object") {
              console.warn(`Invalid object at index ${index}:`);
              return null;
            }

            return {
              name: secret.key_name || secret.name || secret.key || "",
              value: secret.key_value || secret.value || secret.secret || "",
              isSaved: true,
              isMasked: true,
              isUpdated: false,
              originalName: secret.key_name || secret.name || secret.key || "",
              originalValue: secret.key_value || secret.value || secret.secret || "",
            };
          })
          .filter(Boolean); // Remove any null entries

        setRows(dataRows.length > 0 ? dataRows : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
      } else {
        // No domainData found, show empty row for adding new ones
        setRows([{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
      }
    } catch (error) {
      console.error("Error loading domainData:", error);
      const errorMessage = error?.response?.details || error?.details || error?.message || "Error loading domainData.";
      addMessage(errorMessage, "error");
      setRows([{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
    } finally {
      setLoading(false);
    }
  };

  const getGroupVaults = async (keyName, index, copy) => {
    if (!selectedGroup || !keyName) {
      addMessage("Please select a domain and ensure key name is provided.", "error");
      return;
    }

    if (typeof keyName !== "string" || keyName.trim() === "") {
      addMessage("Invalid key name provided.", "error");
      return;
    }

    setLoading(true);
    try {
      // Hide any previously visible secret first
      hideCurrentlyVisibleSecret();

      // Use the specific endpoint to get the  value
      const apiUrl = `/domains/${encodeURIComponent(selectedGroup)}/secrets/${encodeURIComponent(keyName)}`;
      const response = await fetchData(apiUrl);

      if (response) {
        // Handle the response - could be direct value or object with key_value
        let groupVaultData = "";
        if (typeof response === "string") {
          groupVaultData = response;
        } else if (response && typeof response === "object") {
          if ("key_value" in response) {
            groupVaultData = response["key_value"];
          } else if ("value" in response) {
            groupVaultData = response.value;
          } else if (response.data && "key_value" in response.data) {
            groupVaultData = response["data"]["key_value"];
          } else {
            groupVaultData = "No secret value found";
          }
        } else {
          groupVaultData = "No secret value found";
        }

        if (copy === "copy") {
          await navigator.clipboard.writeText(groupVaultData);
          addMessage("Secret value copied to clipboard!", "success");
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
      const errorMessage = error?.response?.details || error?.details || error?.message || `Error fetching secret "${keyName}" from domain "${selectedGroup}".`;
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
      clearSecretFromCache(index, activeTab);
    }

    setRows(updatedRows);
  };

  // copyValue not used in this component

  const DISABLED_OPACITY = 0.5;

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
        const sanitizedSecretNames = Array.isArray(response.key_names) ? response.key_names.map((name) => sanitizeVaultValue(name)) : [];

        setRows(
          sanitizedSecretNames.length ? sanitizedSecretNames : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]
        );

        return sanitizedSecretNames;
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
            : [{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]
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
      if (!userEmail) {
        addMessage("User email not found. Please log in again.", "error");
        return [];
      }

      const apiUrl = `${APIs.GET_DOMAINS_BY_USER}${encodeURIComponent(userEmail)}`;
      const response = await fetchData(apiUrl);

      if (response && response.success) {
        const domainsData = response.domains || [];

        // Validate domain objects
        const validDomains = domainsData.filter((domain) => domain && typeof domain === "object" && domain.domain_name);

        setAvailableGroups(validDomains);

        if (validDomains.length === 0) {
          addMessage("No domains found. Create a domain first.", "error");
        }

        return validDomains;
      } else {
        addMessage(response?.message || "Failed to load domains.", "error");
        return [];
      }
    } catch (error) {
      console.error("Error fetching available groups:", error);
      const errorMessage = error?.response?.details || error?.details || error?.message || "Error loading domains. Please try again.";
      addMessage(errorMessage, "error");
      setAvailableGroups([]);
      return [];
    }
  };

  // Filtered groups based on search term
  const filteredGroups = Array.isArray(availableGroups)
    ? availableGroups.filter((group) => group && group.domain_name && group.domain_name.toLowerCase().includes(groupSearchTerm.toLowerCase()))
    : [];

  // Group dropdown helper functions
  const handleGroupSelection = (group) => {
    if (!group || !group.domain_name) {
      addMessage("Invalid domain selection.", "error");
      return;
    }

    try {
      setSelectedGroup(group.domain_name);
      setSelectedGroupObj(group);
      setGroupSearchTerm("");
      setShowGroupDropdown(false);
      setHighlightedGroupIndex(-1);

      // Load groupselection for the selected domain
      loadDomainData(group.domain_name);
    } catch (error) {
      console.error("Error in handleGroupSelection:", error);
      const errorMessage = error?.response?.details || error?.details || error?.message || "Error selecting domain.";
      addMessage(errorMessage, "error");
    }
  };

  const handleGroupDropdownToggle = () => {
    try {
      const newShowState = !showGroupDropdown;
      setShowGroupDropdown(newShowState);

      if (newShowState && selectedGroupObj && selectedGroupObj.domain_name) {
        // Find the selected group in the filtered list and highlight it
        const selectedIndex = filteredGroups.findIndex((group) => group && group.domain_name === selectedGroupObj.domain_name);
        if (selectedIndex !== -1) {
          setHighlightedGroupIndex(selectedIndex);
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

      // For now, we'll show empty rows for group scripts - this can be extended to fetch group-specific
      setLoading(false);
      setRows([{ name: "", value: "", isSaved: false, isMasked: false, isUpdated: false, originalName: "", originalValue: "" }]);
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
    return <div style={{ padding: 24, color: "#b91c1c", fontWeight: 600 }}>You do not have permission to access the vault.</div>;
  }

  return (
    <div>
      {loading && <Loader />}
      <div className={styles.container}>
        <div className={styles.plusIcons}>
          <h6 className={styles.titleCss}>LIST OF VAULT SECRET</h6>
          <span
            className={styles.addIcon}
            onClick={() => {
              if (role?.toUpperCase() === "GUEST") return;
              if (activeTab === "Group" && !selectedGroup) return;
              if (!rows.some((row) => !row.isSaved)) addRow();
            }}
            style={{
              opacity: role?.toUpperCase() === "GUEST" || rows.some((row) => !row.isSaved) || (activeTab === "Group" && !selectedGroup) ? DISABLED_OPACITY : 1,
              cursor: role?.toUpperCase() === "GUEST" || rows.some((row) => !row.isSaved) || (activeTab === "Group" && !selectedGroup) ? "not-allowed" : "pointer",
            }}
            title={
              activeTab === "Group" && !selectedGroup
                ? "Please select a group first."
                : rows.some((row) => !row.isSaved)
                ? "Please save the current secret before adding another."
                : role?.toUpperCase() === "GUEST"
                ? "Guests cannot add new values."
                : "Add Secret"
            }>
            <button className={styles.plus} disabled={role?.toUpperCase() === "GUEST"}>
              <SVGIcons icon="fa-plus" fill="#007CC3" width={16} height={16} />
            </button>
          </span>
        </div>
        <div className={styles.vaultWrapper}>
          <div>
            <div style={{ marginLeft: 10 }}>
              {role && role?.toUpperCase() !== "GUEST" && (
                <button className={activeTab === "Private" ? styles.activeTab : styles.tab} onClick={() => setActiveTab("Private")}>
                  Private
                </button>
              )}

              <button className={activeTab === "Public" ? styles.activeTab : styles.tab} onClick={() => setActiveTab("Public")}>
                Public
              </button>

              {/* <button className={activeTab === "Group" ? styles.activeTab : styles.tab} onClick={() => setActiveTab("Group")}>
                Group
              </button> */}
            </div>

            {/* Group Selection Dropdown - Show at top of Group tab */}
            {activeTab === "Group" && (
              <div style={{ marginLeft: 20, marginTop: 15, marginBottom: 15 }}>
                {availableGroups.length === 0 ? (
                  <div style={{ color: "#666", fontSize: "12px" }}>No groups available. Create a domain first.</div>
                ) : (
                  <div className={styles.groupDropdownContainer} data-group-dropdown>
                    <div
                      style={{
                        background: "white",
                        border: "1px solid #ddd",
                        borderRadius: "4px",
                        padding: "8px 12px",
                        fontSize: "14px",
                        color: "#374151",
                        cursor: "pointer",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "space-between",
                        transition: "all 0.2s ease",
                        minHeight: "36px",
                        borderColor: showGroupDropdown ? "#0078d4" : "#ddd",
                        boxShadow: showGroupDropdown ? "0 0 0 2px rgba(0, 120, 212, 0.1)" : "none",
                        maxWidth: "300px",
                      }}
                      onClick={handleGroupDropdownToggle}
                      onKeyDown={handleGroupKeyDown}
                      tabIndex={0}
                      role="combobox"
                      aria-expanded={showGroupDropdown}
                      aria-haspopup="listbox"
                      aria-controls="group-dropdown-list">
                      <span style={{ fontSize: "13px" }}>{selectedGroupObj ? selectedGroupObj.domain_name : "Select Group..."}</span>
                      <svg
                        width="16"
                        height="16"
                        viewBox="0 0 20 20"
                        fill="none"
                        xmlns="http://www.w3.org/2000/svg"
                        style={{
                          transition: "transform 0.2s ease",
                          marginLeft: "8px",
                          transform: showGroupDropdown ? "rotate(180deg)" : "rotate(0deg)",
                        }}>
                        <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </div>

                    {showGroupDropdown && (
                      <div className={styles.groupDropdownContent} onClick={(e) => e.stopPropagation()}>
                        <div style={{ position: "relative", padding: "8px" }}>
                          <svg
                            width="16"
                            height="16"
                            viewBox="0 0 20 20"
                            fill="none"
                            xmlns="http://www.w3.org/2000/svg"
                            style={{
                              position: "absolute",
                              left: "16px",
                              top: "50%",
                              transform: "translateY(-50%)",
                              color: "#64748b",
                              fontSize: "14px",
                            }}>
                            <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                            <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                          </svg>
                          <input
                            type="text"
                            placeholder="Search domains..."
                            value={groupSearchTerm}
                            onChange={(e) => setGroupSearchTerm(e.target.value)}
                            style={{
                              width: "100%",
                              background: "#f8fafc",
                              border: "1px solid #ddd",
                              borderRadius: "4px",
                              padding: "8px 12px 8px 32px",
                              fontSize: "13px",
                              color: "#374151",
                              outline: "none",
                            }}
                            autoComplete="off"
                          />
                        </div>
                        <div
                          id="group-dropdown-list"
                          style={{
                            maxHeight: "150px",
                            overflowY: "auto",
                            padding: "4px 0",
                          }}>
                          {filteredGroups.length > 0 ? (
                            filteredGroups.map((group, groupIndex) => (
                              <div
                                key={group.domain_name}
                                data-group-index={groupIndex}
                                style={{
                                  padding: "8px 12px",
                                  cursor: "pointer",
                                  borderBottom: "1px solid #f5f5f5",
                                  transition: "all 0.2s ease",
                                  borderLeft: "3px solid transparent",
                                  background: groupIndex === highlightedGroupIndex ? "#e0f2fe" : "transparent",
                                  borderLeftColor: groupIndex === highlightedGroupIndex ? "#0078d4" : "transparent",
                                }}
                                onClick={() => handleGroupSelection(group)}
                                onMouseEnter={() => setHighlightedGroupIndex(groupIndex)}
                                onMouseLeave={() => setHighlightedGroupIndex(-1)}
                                role="option"
                                aria-selected={selectedGroup === group.domain_name}>
                                <div
                                  style={{
                                    fontSize: "13px",
                                    fontWeight: "500",
                                    color: groupIndex === highlightedGroupIndex ? "#0078d4" : "#374151",
                                  }}>
                                  {group.domain_name}
                                </div>
                                {group.description && (
                                  <div
                                    style={{
                                      fontSize: "11px",
                                      color: groupIndex === highlightedGroupIndex ? "#0078d4" : "#64748b",
                                      fontWeight: "400",
                                      marginTop: "2px",
                                      lineHeight: "1.3",
                                    }}>
                                    {group.description}
                                  </div>
                                )}
                              </div>
                            ))
                          ) : (
                            <div
                              style={{
                                padding: "20px",
                                textAlign: "center",
                                color: "#64748b",
                                fontSize: "12px",
                              }}>
                              No domains found
                            </div>
                          )}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {selectedGroupObj && (
                  <div style={{ marginTop: "10px", fontSize: "14px", color: "#666" }}>
                    Selected Group: <strong>{selectedGroupObj.domain_name}</strong>
                  </div>
                )}
              </div>
            )}

            <div className={styles.secretCss} ref={containerRef}>
              {activeTab === "Group" && !selectedGroupObj ? (
                <div className={styles.selectGroupMessage}>
                  <div className={styles.selectGroupContent}>
                    <div className={styles.selectGroupTitle}>Select a Group</div>
                    <div className={styles.selectGroupSubtitle}>Choose a group from the dropdown above to view and manage its secrets.</div>
                  </div>
                </div>
              ) : rows.length === 0 && role?.toUpperCase() === "GUEST" ? (
                <div className={styles.noSecretsMessage}>There are no secrets to display.</div>
              ) : (
                <>
                  {rows.map((row, index) => {
                    const canShowIcons = isRowComplete(row);
                    const isLast = index === rows.length - 1;
                    return (
                      <div className={styles.row} key={index} ref={isLast ? lastRowRef : null}>
                        <input
                          type="text"
                          value={row.name}
                          placeholder={activeTab === "Group" ? "Enter Key Name" : "Enter Name"}
                          onChange={(e) => handleInputChange(index, "name", e.target.value)}
                          className={styles.input}
                          disabled={row.isSaved}
                        />

                        <textarea
                          value={row.isSaved && row.isMasked ? "......." : row.isUpdated ? row.value : getVaultCache(activeTab).current[index] || row.value}
                          placeholder="Enter Value"
                          onChange={(e) => {
                            // When user starts editing, copy cache value to row.value first if not already editing
                            if (row.isSaved && !row.isUpdated && !row.isMasked) {
                              const cacheValue = getVaultCache(activeTab).current[index];
                              if (cacheValue && row.value !== cacheValue) {
                                const updatedRows = [...rows];
                                updatedRows[index].value = cacheValue;
                                setRows(updatedRows);
                              }
                            }
                            handleInputChange(index, "value", e.target.value);
                          }}
                          className={`${styles.input} ${styles.valueTextarea}`}
                          disabled={row.isSaved && row.isMasked}
                        />

                        {canShowIcons && !row.isSaved && role?.toUpperCase() !== "GUEST" && (
                          <span
                            className={styles.iconCss}
                            title="Save"
                            onClick={() => {
                              if (activeTab === "Private") {
                                saveRow(index);
                              } else if (activeTab === "Group") {
                                saveGroupRow(index);
                              } else {
                                savePublicRow(index);
                              }
                            }}>
                            <SVGIcons icon="save" color="#007CC3" width={18} height={18} />
                          </span>
                        )}

                        {row.isSaved && row.isUpdated && role?.toUpperCase() !== "GUEST" && (
                          <>
                            <span
                              className={styles.iconCss}
                              title="Update"
                              onClick={() => {
                                if (activeTab === "Private") {
                                  updateRow(index);
                                } else if (activeTab === "Group") {
                                  updateGroupRow(index);
                                } else {
                                  updatePublicRow(index);
                                }
                              }}>
                              <SVGIcons icon="save" color="#007CC3" width={18} height={18} />
                            </span>
                            <span
                              className={styles.iconClose}
                              title="Cancel changes and return to view mode"
                              onClick={() => cancelUpdate(index)}
                              style={{ cursor: "pointer", color: "#333", marginLeft: "10px" }}>
                              <FontAwesomeIcon icon={faTimes} />
                            </span>
                          </>
                        )}

                        <>
                          {row.isSaved && !row.isUpdated && (
                            <>
                              {/* Mask / UnMask values */}
                              <span
                                className={`${styles.iconCss} ${styles.iconEye}`}
                                title={
                                  !row.isSaved
                                    ? activeTab === "Group"
                                      ? "Save the secret first to view it."
                                      : "Save the secret first to view it."
                                    : role && role?.toUpperCase() === "GUEST"
                                    ? activeTab === "Group"
                                      ? "Guests are not allowed to view secrets."
                                      : "Guests are not allowed to view secrets."
                                    : row.isMasked
                                    ? activeTab === "Group"
                                      ? "Show Secret Value"
                                      : "Show Secret"
                                    : activeTab === "Group"
                                    ? "Hide Secret Value"
                                    : "Hide Secret"
                                }
                                onClick={
                                  !row.isSaved || (role && role?.toUpperCase() === "GUEST")
                                    ? null
                                    : () => {
                                        if (row.isMasked) {
                                          if (activeTab === "Private") {
                                            getEyeVaultItems(row.name, index, "");
                                          } else if (activeTab === "Group") {
                                            getGroupVaults(row.name, index, "");
                                          } else {
                                            getPublicVaultList(row.name, index, "");
                                          }
                                        } else {
                                          toggleMask(index);
                                        }
                                      }
                                }
                                style={{
                                  opacity: !row.isSaved || (role && role?.toUpperCase() === "GUEST") ? DISABLED_OPACITY : 1,
                                  cursor: !row.isSaved || (role && role?.toUpperCase() === "GUEST") ? "not-allowed" : "pointer",
                                }}>
                                <FontAwesomeIcon icon={row.isMasked ? faEye : faEyeSlash} />
                              </span>

                              <span
                                className={`${styles.iconCss} ${styles.iconDelete}`}
                                title={
                                  !row.isSaved
                                    ? activeTab === "Group"
                                      ? "Save the domain before you can delete it."
                                      : "Save the secret before you can delete it."
                                    : role && role?.toUpperCase() === "GUEST"
                                    ? activeTab === "Group"
                                      ? "Guests are not allowed to delete domains."
                                      : "Guests are not allowed to delete secrets."
                                    : "Delete"
                                }
                                onClick={() => handleDeleteClick(index)}
                                style={{
                                  opacity: !row.isSaved || (role && role?.toUpperCase() === "GUEST") ? DISABLED_OPACITY : 1,
                                  cursor: !row.isSaved || (role && role?.toUpperCase() === "GUEST") ? "not-allowed" : "pointer",
                                }}>
                                <FontAwesomeIcon icon={faTrash} />
                              </span>
                            </>
                          )}
                          {!row.isSaved && rows.length > 1 && (
                            <span
                              className={styles.iconClose}
                              title="Remove this secret"
                              onClick={() => {
                                const newRows = [...rows];
                                newRows.splice(index, 1);
                                setRows(newRows);
                              }}
                              style={{ cursor: "pointer", color: "#333", marginLeft: "10px" }}>
                              <FontAwesomeIcon icon={faTimes} />
                            </span>
                          )}
                        </>
                      </div>
                    );
                  })}
                </>
              )}
            </div>
          </div>
          {role?.toUpperCase() !== "GUEST" && (
            <div style={{ width: "100%" }}>
              <div className={styles?.cssForText}>Access your secret keys in Python via:</div>
              <div className={styles?.cssForcode}>
                <CodeEditor
                  mode="python"
                  theme="monokai"
                  isDarkTheme={true}
                  value={pythonVaultExample}
                  width="100%"
                  height="300px"
                  fontSize={14}
                  readOnly={true}
                  setOptions={{
                    enableBasicAutocompletion: false,
                    enableLiveAutocompletion: false,
                    enableSnippets: false,
                    showLineNumbers: true,
                    tabSize: 4,
                    useWorker: false,
                    wrap: true,
                  }}
                  style={{
                    fontFamily: "Consolas, Monaco, 'Courier New', monospace",
                    border: "1px solid #e0e0e0",
                    borderRadius: "8px",
                  }}
                />
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
    </div>
  );
};

export default Vault;
