import React, { useState, useEffect } from "react";
import Cookies from "js-cookie";
import styles from "./AgentAssignment.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import Loader from "../commonComponents/Loader";

import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import Modal from "./commonComponents/Modal";
import SearchableDropdown from "./commonComponents/SearchableDropdown";
import FormInput from "./commonComponents/FormInput";
import Table from "./commonComponents/Table";
import ActionButton from "./commonComponents/ActionButton";

const GroupAgentAssignment = () => {
  const [groups, setGroups] = useState([]);
  const [agents, setAgents] = useState([]);
  const [users, setUsers] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Pagination states
  const [currentPage, setCurrentPage] = useState(1);
  const ITEMS_PER_PAGE = 10;
  const [itemsPerPage] = useState(ITEMS_PER_PAGE);
  const [totalItems, setTotalItems] = useState(0);

  // Search and dropdown states
  const [agentSearchTerm, setAgentSearchTerm] = useState("");
  const [userSearchTerm, setUserSearchTerm] = useState("");
  // Table search term for groups
  const [groupTableSearch, setGroupTableSearch] = useState("");
  // Search value that was actually applied (used for fetch and filtering)
  const [groupAppliedSearch, setGroupAppliedSearch] = useState("");

  // Email input states for user selection
  const [emailInput, setEmailInput] = useState("");
  const [emailError, setEmailError] = useState("");

  // Create group states
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [newGroupName, setNewGroupName] = useState("");
  const [newGroupDescription, setNewGroupDescription] = useState("");

  const [selectedUsersForGroup, setSelectedUsersForGroup] = useState([]);
  const [selectedAgentsForGroup, setSelectedAgentsForGroup] = useState([]);

  // Update assignment states (simplified for edit mode)

  // Edit group states (for editing existing groups)
  const [isEditMode, setIsEditMode] = useState(false);
  const [editingGroupData, setEditingGroupData] = useState(null);
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const [highlightedAgentIndex, setHighlightedAgentIndex] = useState(-1);
  const [highlightedUserIndex, setHighlightedUserIndex] = useState(-1);

  // Confirmation dialog states
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [domainToDelete, setDomainToDelete] = useState(null);

  const { addMessage } = useMessage();
  const { fetchData, postData, putData, deleteData } = useFetch();

  // Check if current user is admin (moved to top for consistent use)
  const userRole = Cookies.get("role");
  const isAdmin = userRole === "ADMIN" || userRole === "admin";

  // Filtered data based on search terms with safety checks
  const filteredAgents =
    Array.isArray(agents) && agents.length > 0
      ? agents.filter((agent) => agent && (agent.agentic_application_name || agent.agent_name || agent.name || "").toLowerCase().includes(agentSearchTerm.toLowerCase()))
      : [];

  const filteredUsers =
    Array.isArray(users) && users.length > 0
      ? users.filter((user) => {
          if (!user) return false;

          // Check if user is already selected to avoid duplicates
          const isAlreadySelected = selectedUsersForGroup.some((selected) => selected.email === user.email || selected.id === user.id);

          if (isAlreadySelected) return false;

          // Filter by search term
          const searchableText = `${user.name || ""} ${user.username || ""} ${user.email || ""}`.toLowerCase();
          return searchableText.includes(userSearchTerm.toLowerCase());
        })
      : [];

  const handleAgentDropdownToggle = () => {
    setShowAgentDropdown(!showAgentDropdown);
  };

  // Handle keyboard navigation for create group agent dropdown
  const handleCreateGroupAgentKeyDown = (event) => {
    const availableAgents = filteredAgents.filter((agent) => !selectedAgentsForGroup.find((selected) => selected.agentic_application_id === agent.agentic_application_id));

    if (!showAgentDropdown) {
      if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
        event.preventDefault();
        setShowAgentDropdown(true);
        setHighlightedAgentIndex(0);
      }
      return;
    }

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setHighlightedAgentIndex((prev) => (prev < availableAgents.length - 1 ? prev + 1 : prev));
        break;
      case "ArrowUp":
        event.preventDefault();
        setHighlightedAgentIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case "Enter":
        event.preventDefault();
        if (highlightedAgentIndex >= 0 && availableAgents[highlightedAgentIndex]) {
          addAgentToGroupFromDropdown(availableAgents[highlightedAgentIndex]);
        }
        break;
      case "Escape":
        event.preventDefault();
        setShowAgentDropdown(false);
        setHighlightedAgentIndex(-1);
        break;
      default:
        break;
    }
  };

  // Fetch groups, agents, and assignments on component mount
  useEffect(() => {
    try {
      loadInitialData();
    } catch (err) {
      setError(err.message || "Failed to initialize component");
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch paginated groups when page or applied search changes
  useEffect(() => {
    fetchPaginatedGroups(currentPage, itemsPerPage, groupAppliedSearch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, itemsPerPage, groupAppliedSearch]);

  // Auto-scroll when highlighted agent index changes in create group dropdown
  useEffect(() => {
    if (showAgentDropdown && highlightedAgentIndex >= 0) {
      const element = document.querySelector(`[data-create-agent-index="${highlightedAgentIndex}"]`);
      if (element) {
        element.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
          inline: "nearest",
        });
      }
    }
  }, [highlightedAgentIndex, showAgentDropdown]);

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (!event.target.closest(`.${styles.searchableDropdown}`) && !event.target.closest(`.${styles.agentSelectionArea}`)) {
        setShowAgentDropdown(false);
        setShowUserDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const loadInitialData = async () => {
    setLoading(true);
    try {
      // Get logged-in user's email and role
      const currentUserEmail = Cookies.get("email");
      const userRole = Cookies.get("role");

      if (!currentUserEmail) {
        addMessage("User email not found. Please log in again.", "error");
        setLoading(false);
        return;
      }

      const isAdmin = userRole === "ADMIN" || userRole === "admin";

      // Fetch groups based on user role
      let domainsData = [];
      try {
        // Always use /domains/ endpoint for both admin and regular users
        const allDomainsResponse = await fetchData(APIs.GET_DOMAINS);
        console.log("RAW API Response:", allDomainsResponse);
        console.log("Domains array:", allDomainsResponse?.domains);
        console.log("Domains count:", allDomainsResponse?.domains?.length);
        if (allDomainsResponse && allDomainsResponse.domains && Array.isArray(allDomainsResponse.domains)) {
          // Temporarily show ALL domains for both admin and regular users
          domainsData = allDomainsResponse.domains;
          console.log("domainsData set to:", domainsData);
          console.log("domainsData length:", domainsData.length);
          const transformedGroups = allDomainsResponse.domains.map((domain) => ({
            id: domain.domain_name,
            name: domain.domain_name,
            description: domain.domain_description,
            user_emails: domain.user_emails || [],
            agent_ids: domain.agent_ids || [],
            created_by: domain.created_by,
            created_at: domain.created_at,
            updated_at: domain.updated_at,
          }));
          setGroups(transformedGroups);
        } else {
          setGroups([]);
        }
      } catch (error) {
        console.warn("Domains API not available, using mock data");
        const mockData = [{ domain_name: "Application Developer", domain_description: "Web designing", user_emails: [currentUserEmail], agent_ids: [] }];
        domainsData = mockData;
        setGroups([{ id: "Application Developer", name: "Application Developer", description: "Web designing", user_emails: [currentUserEmail], agent_ids: [] }]);
      }

      // Fetch agents using details-for-chat-interface endpoint
      try {
        const agentsData = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        // Ensure agentsData is always an array
        if (Array.isArray(agentsData)) {
          setAgents(agentsData);
        } else if (agentsData && agentsData.agents && Array.isArray(agentsData.agents)) {
          setAgents(agentsData.agents);
        } else {
          setAgents([]);
        }
      } catch (error) {
        console.error("Failed to fetch agents:", error);
        // Fallback to mock data if API fails
        setAgents([
          { agentic_application_id: "mock-agent-1", agentic_application_name: "Customer Support Agent" },
          { agentic_application_id: "mock-agent-2", agentic_application_name: "Sales Agent" },
          { agentic_application_id: "mock-agent-3", agentic_application_name: "Technical Agent" },
          { agentic_application_id: "mock-agent-4", agentic_application_name: "Admin Agent" },
        ]);
      }

      // Fetch users for user selection dropdown
      try {
        const usersData = await fetchData(APIs.GET_USERS);
        // Handle the API response structure: { total_records, access_records: [{user_email, ...}] }
        if (usersData && usersData.access_records && Array.isArray(usersData.access_records)) {
          // Transform access_records to user format
          const transformedUsers = usersData.access_records.map((record, index) => ({
            id: record.user_email || `user-${index}`,
            email: record.user_email,
            name: record.user_email ? record.user_email.split("@")[0].replace(/[._]/g, " ") : `User ${index + 1}`,
            username: record.user_email ? record.user_email.split("@")[0] : `user${index + 1}`,
            given_access_by: record.given_access_by,
            agent_ids: record.agent_ids || [],
          }));
          setUsers(transformedUsers);
        } else if (Array.isArray(usersData)) {
          // Fallback: if it's directly an array
          setUsers(usersData);
        } else if (usersData && usersData.users && Array.isArray(usersData.users)) {
          // Fallback: if nested under 'users' key
          setUsers(usersData.users);
        } else {
          setUsers([]);
        }
      } catch (error) {
        console.error("Failed to fetch users:", error);
        // Fallback to mock data if API fails
        setUsers([
          { id: "mock-user-1", name: "John Doe", email: "john.doe@example.com" },
          { id: "mock-user-2", name: "Jane Smith", email: "jane.smith@example.com" },
        ]);
      }

      // We'll rely on the paginated domains endpoint for the table data.
      // Do not clear assignments here — paginated endpoint will populate the table.
      // Previously this forcibly cleared paginated results causing the table to be empty.
    } catch (error) {
      console.error("Error loading data:", error);
      setError(error.message || "Failed to load data");
      addMessage("Failed to load some data. Using fallback data where possible.", "error");
    } finally {
      setLoading(false);
    }
  };

  // Fetch paginated groups from backend
  const fetchPaginatedGroups = async (pageNumber = 1, pageSize = ITEMS_PER_PAGE, searchTerm = "") => {
    setLoading(true);
    try {
      const params = [];
      params.push(`page_number=${pageNumber}`);
      params.push(`page_size=${pageSize}`);
      if (searchTerm && String(searchTerm).trim() !== "") {
        params.push(`search=${encodeURIComponent(String(searchTerm).trim())}`);
      }
      const apiUrl = `${APIs.GET_DOMAINS_SEARCH_PAGINATED || "/domains/get/search-paginated/"}?${params.join("&")}`;
      const response = await fetchData(apiUrl);
      if (!response) return;

      // Expected response: { details: [...], total_count, total_pages }
      const source = Array.isArray(response.details) ? response.details : Array.isArray(response.domains) ? response.domains : Array.isArray(response) ? response : [];

      if (source && source.length > 0) {
        // Map domains to assignment rows for table
        const rows = source.map((domain) => ({
          id: domain.domain_name,
          groupId: domain.domain_name,
          groupName: domain.domain_name,
          groupDescription: domain.domain_description,
          user_emails: domain.user_emails || [],
          agent_ids: domain.agent_ids || [],
          created_at: domain.created_at,
          created_by: domain.created_by,
          type: "group",
        }));
        setAssignments(rows);
        setTotalItems(response.total_count || response.total || rows.length);
      } else {
        setAssignments([]);
        setTotalItems(0);
      }
    } catch (err) {
      console.error("Failed to fetch paginated groups:", err);
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateAssignment = (assignment) => {
    // Find the group for this assignment
    const group = groups.find((g) => g.name === assignment.groupName || g.id === assignment.groupId);

    if (group) {
      // Set edit mode and populate the create form with group data
      setIsEditMode(true);
      setEditingGroupData(assignment);
      setShowCreateGroup(true);

      // Pre-populate the form fields with group data
      setNewGroupName(group.name || "");
      setNewGroupDescription(group.description || "");

      // For editing, show all user emails in the domain
      const allEmails = group.user_emails || [];

      // Pre-populate selected users (find users that match the emails in this group)
      const groupUsers = users.filter((u) => allEmails.includes(u.email));

      // Also include users that are in the group but not in the users API response
      const missingUsers = allEmails
        .filter((email) => !groupUsers.some((user) => user.email === email))
        .map((email) => ({
          id: email,
          email: email,
          name: email.split("@")[0].replace(/[._]/g, " "),
          username: email.split("@")[0],
        }));

      setSelectedUsersForGroup([...groupUsers, ...missingUsers]);

      // Pre-populate selected agents (find agents that are assigned to this group)
      const groupAgents = agents.filter((a) => group.agent_ids && group.agent_ids.includes(a.agentic_application_id));
      setSelectedAgentsForGroup(groupAgents);

      // Store update assignment data for later use
    } else {
      addMessage("Group data not found for this assignment", "error");
    }
  };

  const handleDeleteClick = (assignmentId) => {
    // Find the assignment to get the domain name
    const assignment = assignments.find((a) => a.id === assignmentId);
    if (!assignment) {
      addMessage("Group assignment not found", "error");
      return;
    }

    const domainName = assignment.groupName;
    if (!domainName) {
      addMessage("Domain name not found", "error");
      return;
    }

    setDomainToDelete(assignment);
    setShowDeleteConfirmation(true);
  };

  const handleConfirmDelete = async () => {
    if (!domainToDelete?.groupName) {
      setShowDeleteConfirmation(false);
      setDomainToDelete(null);
      return;
    }

    const domainName = domainToDelete.groupName;

    setLoading(true);
    try {
      // Use DELETE request to /domains/{domain_name} endpoint with authentication
      const deleteUrl = APIs.DELETE_DOMAIN.replace("{domain_name}", encodeURIComponent(domainName));
      const result = await deleteData(deleteUrl);

      if (result && result.success !== false) {
        addMessage(`Domain "${domainName}" deleted successfully!`, "success");

        // Refresh the domains list to remove deleted domain
        await loadInitialData();
      } else {
        throw new Error(result?.message || "Failed to delete domain");
      }
    } catch (error) {
      console.error("Error deleting domain:", error);
      if (error.message && error.message.includes("401")) {
        addMessage("Authentication failed. Please log in again.", "error");
      } else if (error.message && error.message.includes("403")) {
        addMessage("Only super-admins can delete domains. Please contact your administrator.", "error");
      } else if (error.message && error.message.includes("super-admin")) {
        addMessage(error.message, "error");
      } else {
        addMessage("Failed to delete domain. Please try again.", "error");
      }
    } finally {
      setLoading(false);
      setShowDeleteConfirmation(false);
      setDomainToDelete(null);
    }
  };

  const handleCreateGroup = async (e) => {
    e.preventDefault();

    if (!newGroupName.trim()) {
      addMessage("Please enter a group name", "error");
      return;
    }

    if (!newGroupDescription.trim()) {
      addMessage("Please enter a group description", "error");
      return;
    }

    if (selectedUsersForGroup.length === 0) {
      addMessage("Please add at least one user email to the group", "error");
      return;
    }

    const currentUserEmail = Cookies.get("email");
    if (!currentUserEmail) {
      addMessage("User email not found. Please log in again.", "error");
      return;
    }

    setLoading(true);
    try {
      // Get user emails from selected users
      const emailList = selectedUsersForGroup.map((user) => user.email);

      const payload = {
        domain_name: newGroupName.trim(),
        domain_description: newGroupDescription.trim(),
        user_emails: emailList,
        agent_ids: selectedAgentsForGroup.map((agent) => agent.agentic_application_id),
      };

      await postData(APIs.CREATE_DOMAIN, payload);
      addMessage("Group created successfully!", "success");

      // Refresh the domains list
      await loadInitialData();

      // Reset to first page after creation
      setCurrentPage(1);

      // Reset form
      resetForm();
      setShowCreateGroup(false);
    } catch (error) {
      console.error("Error creating group:", error);
      addMessage("Failed to create group. Please try again.", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleUpdateGroup = async (e) => {
    e.preventDefault();

    if (!newGroupName.trim()) {
      addMessage("Please enter a group name", "error");
      return;
    }

    if (!newGroupDescription.trim()) {
      addMessage("Please enter a group description", "error");
      return;
    }

    if (selectedUsersForGroup.length === 0) {
      addMessage("Please add at least one user email to the group", "error");
      return;
    }

    const currentUserEmail = Cookies.get("email");
    if (!currentUserEmail) {
      addMessage("User email not found. Please log in again.", "error");
      return;
    }

    if (!editingGroupData) {
      addMessage("No group data found for editing", "error");
      return;
    }

    // Check if user is trying to change the domain name
    const group = groups.find((g) => g.name === editingGroupData.groupName || g.id === editingGroupData.groupId);
    const originalDomainName = group?.name || editingGroupData.groupName;

    if (newGroupName.trim() !== originalDomainName) {
      addMessage("Domain name cannot be changed through update. Please create a new domain if you need a different name.", "error");
      return;
    }

    setLoading(true);
    try {
      // Get user emails from selected users
      const newEmailList = selectedUsersForGroup.map((user) => user.email).filter((email) => email); // Filter out any undefined/null emails

      // Remove duplicates
      const uniqueNewEmailList = [...new Set(newEmailList)];

      // Get current users and agents from the group
      const currentUsers = group?.user_emails || [];
      const currentAgents = group?.agent_ids || [];
      const newAgents = selectedAgentsForGroup.map((agent) => agent.agentic_application_id);

      // Calculate user changes: add and remove operations
      const usersToAdd = uniqueNewEmailList.filter((email) => !currentUsers.includes(email));
      const usersToRemove = currentUsers.filter((email) => !uniqueNewEmailList.includes(email));

      console.log("User change detection:");
      console.log("Current users:", currentUsers);
      console.log("Selected users (new list):", uniqueNewEmailList);
      console.log("Users to add:", usersToAdd);
      console.log("Users to remove:", usersToRemove);

      // Calculate add/remove operations for agents
      const agentsToAdd = newAgents.filter((agentId) => !currentAgents.includes(agentId));
      const agentsToRemove = currentAgents.filter((agentId) => !newAgents.includes(agentId));

      const payload = {
        domain_description: newGroupDescription.trim(),
        add_users: usersToAdd,
        remove_users: usersToRemove,
        add_agents: agentsToAdd,
        remove_agents: agentsToRemove,
      };

      console.log("Update payload:", payload);

      // Use the domain update endpoint with authentication
      const updateUrl = APIs.UPDATE_DOMAIN.replace("{domain_name}", encodeURIComponent(originalDomainName));
      const result = await putData(updateUrl, payload);

      if (result && result.success !== false) {
        addMessage("Group updated successfully!", "success");

        // Refresh the domains list to show updated data
        await loadInitialData();
      } else {
        throw new Error(result?.message || "Failed to update domain");
      }

      // Reset form and exit edit mode
      resetForm();
      setShowCreateGroup(false);
    } catch (error) {
      console.error("Error updating group:", error);
      if (error.message && error.message.includes("401")) {
        addMessage("Authentication failed. Please log in again.", "error");
      } else if (error.message && error.message.includes("403")) {
        addMessage("You don't have permission to update this domain.", "error");
      } else if (error.message && error.message.includes("404")) {
        addMessage("Domain not found. It may have been deleted during the update process.", "error");
      } else if (error.message && error.message.includes("domain") && error.message.includes("delete")) {
        addMessage("The domain was deleted during the update. This can happen when removing all users or the domain creator.", "error");
      } else {
        addMessage(`Failed to update group: ${error.message || "Please try again."}`, "error");
      }
    } finally {
      setLoading(false);
    }
  };

  const addAgentToGroupFromDropdown = (agent) => {
    if (agent && !selectedAgentsForGroup.find((selected) => selected.agentic_application_id === agent.agentic_application_id)) {
      setSelectedAgentsForGroup([...selectedAgentsForGroup, agent]);
      setShowAgentDropdown(false);
      setAgentSearchTerm("");
      setHighlightedAgentIndex(-1);
    }
  };

  const removeAgentFromGroup = (agentToRemove) => {
    setSelectedAgentsForGroup(selectedAgentsForGroup.filter((agent) => agent.agentic_application_id !== agentToRemove.agentic_application_id));
  };

  const addUserToGroupFromDropdown = (user) => {
    if (user && !selectedUsersForGroup.find((selected) => selected.id === user.id || selected.email === user.email)) {
      setSelectedUsersForGroup([...selectedUsersForGroup, user]);
      setShowUserDropdown(false);
      setUserSearchTerm("");
      setHighlightedUserIndex(-1);
    }
  };

  const removeUserFromGroup = (indexToRemove) => {
    setSelectedUsersForGroup((prev) => prev.filter((_, index) => index !== indexToRemove));
  };

  // Reset form function to clear all form state
  const resetForm = () => {
    setIsEditMode(false);
    setEditingGroupData(null);
    setNewGroupName("");
    setNewGroupDescription("");
    setSelectedUsersForGroup([]);
    setSelectedAgentsForGroup([]);
    setUserSearchTerm("");
    setAgentSearchTerm("");
    setShowUserDropdown(false);
    setShowAgentDropdown(false);
    setEmailInput("");
    setEmailError("");
    setHighlightedUserIndex(-1);
    setHighlightedAgentIndex(-1);
  };

  // Email validation function
  const validateEmail = (email) => {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
  };

  // Add user by email input
  const addUserByEmail = (email) => {
    const trimmedEmail = email.trim();

    // Clear any previous errors
    setEmailError("");

    if (!trimmedEmail) {
      setEmailError("Please enter an email address");
      return false;
    }

    if (!validateEmail(trimmedEmail)) {
      setEmailError("Please enter a valid email address");
      return false;
    }

    // Check if email already exists
    if (selectedUsersForGroup.find((user) => user.email === trimmedEmail)) {
      setEmailError("This email is already added");
      return false;
    }

    // Add the email as a user object
    const newUser = {
      id: `email-${Date.now()}`,
      email: trimmedEmail,
      name: trimmedEmail.split("@")[0] || trimmedEmail,
      username: trimmedEmail.split("@")[0] || trimmedEmail,
    };

    setSelectedUsersForGroup((prev) => [...prev, newUser]);
    setEmailInput("");
    setEmailError("");
    return true;
  };

  // Handle Enter key press in email input
  const handleEmailInputKeyDown = (e) => {
    if (e.key === "Enter") {
      e.preventDefault();
      addUserByEmail(emailInput);
    }
  };

  const handleUserSearchKeyDown = (e) => {
    if (!showUserDropdown) return;

    switch (e.key) {
      case "ArrowDown":
        e.preventDefault();
        if (filteredUsers.length > 0) {
          setHighlightedUserIndex((prev) => (prev < filteredUsers.length - 1 ? prev + 1 : 0));
        }
        break;
      case "ArrowUp":
        e.preventDefault();
        if (filteredUsers.length > 0) {
          setHighlightedUserIndex((prev) => (prev > 0 ? prev - 1 : filteredUsers.length - 1));
        }
        break;
      case "Enter":
        e.preventDefault();
        if (highlightedUserIndex >= 0 && highlightedUserIndex < filteredUsers.length) {
          addUserToGroupFromDropdown(filteredUsers[highlightedUserIndex]);
        }
        break;
      case "Escape":
        setShowUserDropdown(false);
        setUserSearchTerm("");
        setHighlightedUserIndex(-1);
        break;
      default:
        break;
    }
  };

  const handleUserDropdownToggle = () => {
    setShowUserDropdown(!showUserDropdown);
    if (!showUserDropdown) {
      setHighlightedUserIndex(0);
    } else {
      setUserSearchTerm("");
      setHighlightedUserIndex(-1);
    }
  };

  // Calculate stats with safety checks
  const totalAgents = Array.isArray(agents) ? agents.length : 0;
  const totalGroups = Array.isArray(groups) ? groups.length : 0;
  const totalUsers = Array.isArray(assignments) ? [...new Set(assignments.map((a) => a.userEmail))].length : 0;

  // Get groups with agents assigned
  const groupsWithAgents = Array.isArray(groups) ? groups.filter((group) => group && group.agent_ids && Array.isArray(group.agent_ids) && group.agent_ids.length > 0).length : 0;

  return (
    <div className={styles.agentAssignmentContainer}>
      {loading && <Loader />}

      {/* Error Display */}
      {error && (
        <div className={styles.errorContainer}>
          <div className={styles.errorMessage}>
            <h3>⚠️ Error Loading Group Assignments</h3>
            <p>{error}</p>
            <button
              onClick={() => {
                setError(null);
                loadInitialData();
              }}
              className={styles.retryButton}>
              Retry Loading
            </button>
          </div>
        </div>
      )}

      {/* Role Indicator */}
      {isAdmin && (
        <div className={styles.roleIndicator}>
          <span className={styles.adminBadge}>👑 Admin View - Showing All Groups & Assignments</span>
        </div>
      )}

      {/* Stats Cards */}
      <div className={styles.statsCards}>
        <div className={styles.statCard}>
          <h4>Total Groups</h4>
          <p>{totalGroups}</p>
        </div>
        <div className={styles.statCard}>
          <h4>Available Agents</h4>
          <p>{totalAgents}</p>
        </div>
        <div className={styles.statCard}>
          <h4>Groups with Agents</h4>
          <p>{groupsWithAgents}</p>
        </div>
      </div>

      {/* Create Group Button */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        {!showCreateGroup ? (
          <button onClick={() => setShowCreateGroup(true)} className="iafButton iafButtonPrimary">
            Create Group Assignment
          </button>
        ) : (
          <button
            onClick={() => {
              resetForm();
              setShowCreateGroup(false);
            }}
            className={styles.closeIcon}
            title="Close">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
              <path d="M18 6L6 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M6 6L18 18" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        )}
      </div>

      <Modal isOpen={showCreateGroup} onClose={() => setShowCreateGroup(false)} onResetForm={resetForm} title={isEditMode ? "Edit Group" : "Create New Group"}>
        <form onSubmit={isEditMode ? handleUpdateGroup : handleCreateGroup} className={styles.topControls}>
          <FormInput label="Group Name" value={newGroupName} onChange={(e) => setNewGroupName(e.target.value)} placeholder="Enter group name" required={true} />

          <FormInput
            label="Group Description"
            value={newGroupDescription}
            onChange={(e) => setNewGroupDescription(e.target.value)}
            placeholder="Enter group description"
            required={true}
          />

          <FormInput
            label="Add Member"
            type="email"
            value={emailInput}
            onChange={(e) => {
              setEmailInput(e.target.value);
              if (emailError) setEmailError(""); // Clear error on typing
            }}
            onKeyDown={handleEmailInputKeyDown}
            placeholder="Enter member email and press Enter"
            error={emailError}
            required={false}
            autoComplete="off"
          />

          {/* Selected Users Chips - Below Input */}
          {selectedUsersForGroup.length > 0 && (
            <div className={styles.selectedUsersContainer}>
              <div className={styles.selectedUsersList}>
                {selectedUsersForGroup.map((user, index) => (
                  <span key={index} className={styles.selectedUserTag}>
                    {user.email}
                    <button type="button" onClick={() => removeUserFromGroup(index)} className={styles.removeSelectedUser} title="Remove user">
                      ×
                    </button>
                  </span>
                ))}
              </div>
            </div>
          )}

          <div className={styles.controlGroup}>
            <label className={styles.controlLabel}>Assign Agents (optional)</label>
            <div className={styles.agentSelectionArea}>
              <div className={styles.searchableDropdown}>
                <div
                  className={`${styles.dropdownTrigger} ${showAgentDropdown ? styles.active : ""}`}
                  onClick={handleAgentDropdownToggle}
                  onKeyDown={handleCreateGroupAgentKeyDown}
                  tabIndex={0}
                  role="combobox"
                  aria-expanded={showAgentDropdown}
                  aria-haspopup="listbox"
                  aria-controls="agent-dropdown-list">
                  <span>Select agents to assign...</span>
                  <svg
                    width="18"
                    height="18"
                    viewBox="0 0 20 20"
                    fill="none"
                    xmlns="http://www.w3.org/2000/svg"
                    className={`${styles.chevronIcon} ${showAgentDropdown ? styles.rotated : ""}`}>
                    <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                </div>

                {showAgentDropdown && (
                  <div className={styles.dropdownContent} onClick={(e) => e.stopPropagation()} id="agent-dropdown-list" role="listbox">
                    <div className={styles.searchContainer}>
                      <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                        <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                        <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                      </svg>
                      <input
                        type="text"
                        placeholder="Search agents..."
                        value={agentSearchTerm}
                        onChange={(e) => setAgentSearchTerm(e.target.value)}
                        className={styles.searchInput}
                        autoComplete="off"
                      />
                    </div>
                    <div className={styles.agentsList}>
                      {filteredAgents.filter((agent) => !selectedAgentsForGroup.find((selected) => selected.agentic_application_id === agent.agentic_application_id)).length > 0 ? (
                        filteredAgents
                          .filter((agent) => !selectedAgentsForGroup.find((selected) => selected.agentic_application_id === agent.agentic_application_id))
                          .map((agent, index) => (
                            <div
                              key={agent.agentic_application_id || agent.id}
                              data-create-agent-index={index}
                              className={`${styles.agentItem} ${index === highlightedAgentIndex ? styles.highlighted : ""}`}
                              onClick={() => addAgentToGroupFromDropdown(agent)}
                              onMouseEnter={() => setHighlightedAgentIndex(index)}
                              onMouseLeave={() => setHighlightedAgentIndex(-1)}
                              role="option"
                              aria-selected={index === highlightedAgentIndex}>
                              <div className={styles.agentName}>{agent.agentic_application_name || agent.agent_name || agent.name}</div>
                            </div>
                          ))
                      ) : (
                        <div className={styles.noAgents}>No available agents found</div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              {/* Selected Agents Chips - Below Dropdown */}
              {selectedAgentsForGroup.length > 0 && (
                <div className={styles.selectedAgentsContainer}>
                  <div className={styles.selectedAgentsList}>
                    {selectedAgentsForGroup.map((agent) => (
                      <span key={agent.agentic_application_id} className={styles.selectedUserTag}>
                        {agent.agentic_application_name}
                        <button type="button" onClick={() => removeAgentFromGroup(agent)} className={styles.removeSelectedUser} title="Remove agent">
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className={styles.modalFooter}>
            <div className={styles.buttonClass}>
              <button type="submit" className="iafButton iafButtonPrimary" disabled={loading}>
                {loading ? (isEditMode ? "Updating..." : "Creating...") : isEditMode ? "Update Group" : "Create Group"}
              </button>
              <button
                type="button"
                onClick={() => {
                  resetForm();
                  setShowCreateGroup(false);
                }}
                className="iafButton iafButtonSecondary">
                Cancel
              </button>
            </div>
          </div>
        </form>
      </Modal>

      {/* Assignment Form */}
      {/* <div className={styles.assignmentForm}>
        <form onSubmit={handleAssignAgent} className={styles.topControls}>
          <div className={styles.controlGroup}>
            <label className={styles.controlLabel}>Select Group:</label>
            <div className={styles.searchableDropdown}>
              <div
                className={`${styles.dropdownTrigger} ${showGroupDropdown ? styles.active : ""}`}
                onClick={handleGroupDropdownToggle}
                role="combobox"
                aria-expanded={showGroupDropdown}
                aria-haspopup="listbox">
                <span>{selectedGroupObj ? selectedGroupObj.name : "Select Group"}</span>
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 20 20"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className={`${styles.chevronIcon} ${showGroupDropdown ? styles.rotated : ""}`}>
                  <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>

              {showGroupDropdown && (
                <div 
                  className={styles.dropdownContent} 
                  onClick={(e) => e.stopPropagation()}>
                  <div className={styles.searchContainer}>
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                      <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                      <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                    <input
                      type="text"
                      placeholder="Search groups..."
                      value={groupSearchTerm}
                      onChange={(e) => setGroupSearchTerm(e.target.value)}
                      className={styles.searchInput}
                      autoComplete="off"
                    />
                  </div>
                  <div className={styles.agentsList}>
                    {filteredGroups.length > 0 ? (
                      filteredGroups.map((group, index) => (
                        <div
                          key={group.id}
                          data-group-index={index}
                          className={`${styles.agentItem} ${index === highlightedGroupIndex ? styles.highlighted : ""}`}
                          onClick={() => handleGroupSelection(group)}
                          onMouseEnter={() => setHighlightedGroupIndex(index)}
                          onMouseLeave={() => setHighlightedGroupIndex(-1)}
                          role="option">
                          <div className={styles.agentName}>
                            {group.name}
                            {group.description && (
                              <div className={styles.agentDescription}>{group.description}</div>
                            )}
                          </div>
                        </div>
                      ))
                    ) : (
                      <div className={styles.noAgents}>No groups found</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className={styles.controlGroup}>
            <label className={styles.controlLabel}>Select Agent:</label>
            <div className={styles.searchableDropdown}>
              <div
                className={`${styles.dropdownTrigger} ${showAgentDropdown ? styles.active : ""}`}
                onClick={handleAgentDropdownToggle}
                role="combobox"
                aria-expanded={showAgentDropdown}
                aria-haspopup="listbox">
                <span>{selectedAgentObj ? (selectedAgentObj.agentic_application_name || selectedAgentObj.agent_name || selectedAgentObj.name) : "Select Agent"}</span>
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 20 20"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className={`${styles.chevronIcon} ${showAgentDropdown ? styles.rotated : ""}`}>
                  <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>

              {showAgentDropdown && (
                <div 
                  className={styles.dropdownContent} 
                  onClick={(e) => e.stopPropagation()}>
                  <div className={styles.searchContainer}>
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                      <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                      <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                    <input
                      type="text"
                      placeholder="Search agents..."
                      value={agentSearchTerm}
                      onChange={(e) => setAgentSearchTerm(e.target.value)}
                      className={styles.searchInput}
                      autoComplete="off"
                    />
                  </div>
                  <div className={styles.agentsList}>
                    {filteredAgents.length > 0 ? (
                      filteredAgents.map((agent, index) => (
                        <div
                          key={agent.agentic_application_id || agent.id}
                          data-group-agent-index={index}
                          className={`${styles.agentItem} ${index === highlightedAgentIndex ? styles.highlighted : ""}`}
                          onClick={() => handleAgentSelection(agent)}
                          onMouseEnter={() => setHighlightedAgentIndex(index)}
                          onMouseLeave={() => setHighlightedAgentIndex(-1)}
                          role="option">
                          <div className={styles.agentName}>{agent.agentic_application_name || agent.agent_name || agent.name}</div>
                        </div>
                      ))
                    ) : (
                      <div className={styles.noAgents}>No agents found</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className={styles.modalFooter}>
            <div className={styles.buttonClass}>
              <button type="submit" className="iafButton iafButtonPrimary" disabled={loading}>
                {loading ? "Assigning..." : "Assign Agent"}
              </button>
            </div>
          </div>
        </form>
      </div> */}

      {/* Groups List */}
      <div className={styles.assignmentsSection}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
          <div className={styles.searchContainer} style={{ maxWidth: 320, width: "100%", position: "relative" }}>
            <input
              type="text"
              placeholder="Search groups..."
              value={groupTableSearch}
              onChange={(e) => {
                const v = e.target.value;
                setGroupTableSearch(v);
                if (v.trim() === "") {
                  // Clear applied search and reload full list
                  setGroupAppliedSearch("");
                  setCurrentPage(1);
                  fetchPaginatedGroups(1, itemsPerPage, "");
                }
              }}
              onKeyDown={(e) => {
                /* intentionally do not trigger search on Enter; click the icon to apply */
              }}
              className={styles.searchInput}
              autoComplete="off"
              aria-label="Search groups"
            />
            <button
              type="button"
              onClick={() => {
                setGroupAppliedSearch(groupTableSearch);
                setCurrentPage(1);
                fetchPaginatedGroups(1, itemsPerPage, groupTableSearch);
              }}
              aria-label="Search groups"
              title="Search"
              style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "transparent", border: "none", cursor: "pointer", padding: 4 }}>
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>
        {/* <div className={styles.sectionHeader}>
          <h3>Groups Overview ({assignments.length} {assignments.length === 1 ? 'group' : 'groups'})</h3>
        </div> */}
        {assignments.length === 0 ? (
          <div className={styles.noAssignments}>
            <h4>No Groups Found</h4>
            <p>Start by creating your first group above.</p>
          </div>
        ) : (
          (() => {
            // Client-side fallback filtering uses the applied search so filtering only occurs after clicking the icon
            const searchTerm = String(groupAppliedSearch || "")
              .toLowerCase()
              .trim();
            const displayed = searchTerm ? assignments.filter((a) => ((a.groupName || "") + " " + (a.groupDescription || "")).toLowerCase().includes(searchTerm)) : assignments;

            return (
              <Table
                headers={["Group Name", "Member Count", "Agent Count", "Actions"]}
                data={displayed}
                renderRow={(assignment) => (
                  <tr key={assignment.id}>
                    <td>
                      <strong>{assignment.groupName || "Unknown Group"}</strong>
                    </td>
                    <td>
                      {(() => {
                        // Prefer member count from the paginated assignment row (response.details)
                        const memberCount = Array.isArray(assignment.user_emails) ? assignment.user_emails.length : null;
                        if (typeof memberCount === "number") {
                          return memberCount > 0 ? `${memberCount} member${memberCount > 1 ? "s" : ""}` : "No members";
                        }

                        // Fallback to groups state if paginated row doesn't include user_emails
                        const group = groups.find((g) => g.name === assignment.groupName);
                        const fallbackMemberCount = group?.user_emails?.length || 0;
                        return fallbackMemberCount > 0 ? `${fallbackMemberCount} member${fallbackMemberCount > 1 ? "s" : ""}` : "No members";
                      })()}
                    </td>
                    <td>
                      {(() => {
                        // Prefer agent count from the paginated assignment row (response.details)
                        const agentCount = Array.isArray(assignment.agent_ids) ? assignment.agent_ids.length : null;
                        if (typeof agentCount === "number") {
                          return agentCount > 0 ? `${agentCount} agent${agentCount > 1 ? "s" : ""}` : "No agents";
                        }

                        // Fallback to groups state if paginated row doesn't include agent_ids
                        const group = groups.find((g) => g.name === assignment.groupName);
                        const fallbackAgentCount = group?.agent_ids?.length || 0;
                        return fallbackAgentCount > 0 ? `${fallbackAgentCount} agent${fallbackAgentCount > 1 ? "s" : ""}` : "No agents";
                      })()}
                    </td>
                    <td>
                      <div className={styles.actionButtons}>
                        <ActionButton
                          icon="fa-solid fa-pen"
                          onClick={() => handleUpdateAssignment(assignment)}
                          disabled={loading}
                          title="Edit Group"
                          variant="secondary"
                          width="10"
                          height="10"
                        />
                        {/* Try to use 'icon="recycle-bin"' instead of 'fa-user-xmark' for consistency with other components */}
                        <ActionButton
                          icon="fa-solid fa-user-xmark"
                          onClick={() => handleDeleteClick(assignment.id)}
                          disabled={loading}
                          title="Delete Domain (Super-admin only)"
                          variant="danger"
                          width="20"
                          height="16"
                        />
                      </div>
                    </td>
                  </tr>
                )}
                loading={loading}
                emptyMessage="No groups found"
                pagination={{
                  currentPage,
                  itemsPerPage,
                  totalItems: totalItems || displayed.length,
                  onPageChange: setCurrentPage,
                  serverSide: true, // assignments are provided as current-page rows by the backend
                }}
              />
            );
          })()
        )}
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteConfirmation && (
        <ConfirmationModal
          message={`Are you sure you want to delete the entire "${domainToDelete?.groupName}" domain? This action cannot be undone and will remove all data associated with this domain.`}
          onConfirm={handleConfirmDelete}
          setShowConfirmation={setShowDeleteConfirmation}
        />
      )}
    </div>
  );
};

export default GroupAgentAssignment;
