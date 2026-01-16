import React, { useState, useEffect } from "react";
import styles from "./AgentAssignment.module.css";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import { APIs } from "../../constant";
import Loader from "../commonComponents/Loader";

import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import Modal from "./commonComponents/Modal";

import Table from "./commonComponents/Table";
import ActionButton from "./commonComponents/ActionButton";

const IndividualAgentAssignment = () => {
  const [users, setUsers] = useState([]);
  const [agents, setAgents] = useState([]);
  const [assignments, setAssignments] = useState([]);
  const [selectedUser, setSelectedUser] = useState("");
  const [selectedAgent, setSelectedAgent] = useState("");
  const [selectedUserObj, setSelectedUserObj] = useState(null);
  const [selectedAgentObj, setSelectedAgentObj] = useState(null);
  const [loading, setLoading] = useState(false);

  // Pagination states
  const [currentPage, setCurrentPage] = useState(1);
  const ITEMS_PER_PAGE = 10;
  const [itemsPerPage] = useState(ITEMS_PER_PAGE);
  const [totalItems, setTotalItems] = useState(0);
  const SCROLL_DELAY = 50;

  // Search and dropdown states
  const [userSearchTerm, setUserSearchTerm] = useState("");
  const [agentSearchTerm, setAgentSearchTerm] = useState("");
  // Table level search for assignments
  const [assignmentTableSearch, setAssignmentTableSearch] = useState("");
  // Applied search used for fetching/filtering only when user clicks icon
  const [assignmentAppliedSearch, setAssignmentAppliedSearch] = useState("");
  const [showUserDropdown, setShowUserDropdown] = useState(false);
  const [showAgentDropdown, setShowAgentDropdown] = useState(false);
  const [highlightedUserIndex, setHighlightedUserIndex] = useState(-1);
  const [highlightedAgentIndex, setHighlightedAgentIndex] = useState(-1);

  // Modal state
  const [showCreateAssignment, setShowCreateAssignment] = useState(false);

  // Confirmation dialog states
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [assignmentToDelete, setAssignmentToDelete] = useState(null);
  // No agents modal required per UI request

  const { addMessage } = useMessage();
  const { fetchData, postData } = useFetch();

  // Filtered data based on search terms
  const filteredUsers = users.filter((user) => (user.name || user.username || user.email || "").toLowerCase().includes(userSearchTerm.toLowerCase()));

  const filteredAgents = agents.filter((agent) => (agent.agentic_application_name || agent.agent_name || agent.name || "").toLowerCase().includes(agentSearchTerm.toLowerCase()));

  // Auto-scroll when highlighted user index changes
  useEffect(() => {
    if (showUserDropdown && highlightedUserIndex >= 0) {
      const element = document.querySelector(`[data-user-index="${highlightedUserIndex}"]`);
      if (element) {
        element.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
          inline: "nearest",
        });
      }
    }
  }, [highlightedUserIndex, showUserDropdown]);

  // Auto-scroll when highlighted agent index changes
  useEffect(() => {
    if (showAgentDropdown && highlightedAgentIndex >= 0) {
      const element = document.querySelector(`[data-agent-index="${highlightedAgentIndex}"]`);
      if (element) {
        element.scrollIntoView({
          behavior: "smooth",
          block: "nearest",
          inline: "nearest",
        });
      }
    }
  }, [highlightedAgentIndex, showAgentDropdown]);

  // Reset form function
  const resetForm = () => {
    setSelectedUser("");
    setSelectedUserObj(null);
    setSelectedAgent("");
    setSelectedAgentObj(null);
    setUserSearchTerm("");
    setAgentSearchTerm("");
    setShowUserDropdown(false);
    setShowAgentDropdown(false);
    setHighlightedUserIndex(-1);
    setHighlightedAgentIndex(-1);
  };

  // Helper functions for dropdown handling
  const handleUserSelection = (user) => {
    setSelectedUser(user.id);
    setSelectedUserObj(user);
    setUserSearchTerm("");
    setShowUserDropdown(false);
    setHighlightedUserIndex(-1);
  };

  const handleAgentSelection = (agent) => {
    setSelectedAgent(agent.agentic_application_id || agent.id);
    setSelectedAgentObj(agent);
    setAgentSearchTerm("");
    setShowAgentDropdown(false);
    setHighlightedAgentIndex(-1);
  };

  const handleUserDropdownToggle = () => {
    const newShowState = !showUserDropdown;
    setShowUserDropdown(newShowState);
    setShowAgentDropdown(false);

    if (newShowState && selectedUserObj) {
      // Find the selected user in the filtered list and highlight it
      const selectedIndex = filteredUsers.findIndex((user) => user.id === selectedUserObj.id);
      if (selectedIndex !== -1) {
        setHighlightedUserIndex(selectedIndex);
        // Scroll to selected item after a small delay to ensure DOM is updated
        setTimeout(() => {
          const selectedElement = document.querySelector(`[data-user-index="${selectedIndex}"]`);
          if (selectedElement) {
            selectedElement.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
        }, SCROLL_DELAY);
      }
    } else if (!newShowState) {
      setHighlightedUserIndex(-1);
    }
  };

  const handleAgentDropdownToggle = () => {
    const newShowState = !showAgentDropdown;
    setShowAgentDropdown(newShowState);
    setShowUserDropdown(false);

    if (newShowState && selectedAgentObj) {
      // Find the selected agent in the filtered list and highlight it
      const selectedIndex = filteredAgents.findIndex((agent) => (agent.agentic_application_id || agent.id) === (selectedAgentObj.agentic_application_id || selectedAgentObj.id));
      if (selectedIndex !== -1) {
        setHighlightedAgentIndex(selectedIndex);
        // Scroll to selected item after a small delay to ensure DOM is updated
        setTimeout(() => {
          const selectedElement = document.querySelector(`[data-agent-index="${selectedIndex}"]`);
          if (selectedElement) {
            selectedElement.scrollIntoView({ behavior: "smooth", block: "nearest" });
          }
        }, SCROLL_DELAY);
      }
    } else if (!newShowState) {
      setHighlightedAgentIndex(-1);
    }
  };

  // Handle keyboard navigation for dropdowns
  const handleUserKeyDown = (event) => {
    if (!showUserDropdown) {
      if (event.key === "Enter" || event.key === " " || event.key === "ArrowDown") {
        event.preventDefault();
        setShowUserDropdown(true);
        setHighlightedUserIndex(0);
      }
      return;
    }

    switch (event.key) {
      case "ArrowDown":
        event.preventDefault();
        setHighlightedUserIndex((prev) => (prev < filteredUsers.length - 1 ? prev + 1 : prev));
        break;
      case "ArrowUp":
        event.preventDefault();
        setHighlightedUserIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case "Enter":
        event.preventDefault();
        if (highlightedUserIndex >= 0 && filteredUsers[highlightedUserIndex]) {
          handleUserSelection(filteredUsers[highlightedUserIndex]);
        }
        break;
      case "Escape":
        event.preventDefault();
        setShowUserDropdown(false);
        setHighlightedUserIndex(-1);
        break;
      default:
        break;
    }
  };

  const handleAgentKeyDown = (event) => {
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
        setHighlightedAgentIndex((prev) => (prev < filteredAgents.length - 1 ? prev + 1 : prev));
        break;
      case "ArrowUp":
        event.preventDefault();
        setHighlightedAgentIndex((prev) => (prev > 0 ? prev - 1 : prev));
        break;
      case "Enter":
        event.preventDefault();
        if (highlightedAgentIndex >= 0 && filteredAgents[highlightedAgentIndex]) {
          handleAgentSelection(filteredAgents[highlightedAgentIndex]);
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

  // Fetch users, agents, and assignments on component mount
  useEffect(() => {
    loadInitialData();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Fetch paginated assignments from backend when page changes
  // Fetch paginated assignments when page or applied search changes
  useEffect(() => {
    fetchPaginatedAssignments(currentPage, itemsPerPage, assignmentAppliedSearch);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentPage, itemsPerPage, assignmentAppliedSearch]);

  // Close dropdowns when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (!event.target.closest(`.${styles.searchableDropdown}`)) {
        setShowUserDropdown(false);
        setShowAgentDropdown(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  const loadInitialData = async () => {
    setLoading(true);
    let loadedUsers = [];

    try {
      // Fetch users from user-agent-access/all endpoint
      try {
        const usersResponse = await fetchData(APIs.GET_USERS);
        if (usersResponse && usersResponse.access_records) {
          // Transform the response to match our user structure
          loadedUsers = usersResponse.access_records.map((record, index) => ({
            id: record.user_email, // Use email as ID since it's unique
            email: record.user_email,
            name: record.user_email.split("@")[0].replace(/[._]/g, " "), // Extract and format name from email
            username: record.user_email.split("@")[0],
            agent_ids: record.agent_ids || [],
            given_access_by: record.given_access_by,
          }));
          setUsers(loadedUsers);
        } else {
          setUsers([]);
          loadedUsers = [];
        }
      } catch (error) {
        console.warn("Users API not available, using mock data");
        loadedUsers = [
          { id: 1, name: "Admin User", email: "admin@example.com" },
          { id: 2, name: "John Doe", email: "john@example.com" },
          { id: 3, name: "Jane Smith", email: "jane@example.com" },
        ];
        setUsers(loadedUsers);
      }

      // Fetch agents using details-for-chat-interface endpoint
      let loadedAgents = [];
      try {
        const agentsData = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        loadedAgents = agentsData || [];
        setAgents(loadedAgents);
      } catch (error) {
        console.error("Failed to fetch agents:", error);
        // Fallback to mock data if API fails
        loadedAgents = [
          { agentic_application_id: "mock-agent-1", agentic_application_name: "Customer Support Agent" },
          { agentic_application_id: "mock-agent-2", agentic_application_name: "Sales Agent" },
          { agentic_application_id: "mock-agent-3", agentic_application_name: "Technical Agent" },
        ];
        setAgents(loadedAgents);
      }

      // Instead of fetching assignments per-user (which can cause duplicates and race conditions),
      // rely on the paginated endpoint to provide assignment listing. We still fetch users
      // and agents above for dropdowns, then call paginated fetch for page 1 below.
      setAssignments([]);
      setTotalItems(0);
    } catch (error) {
      console.error("Error loading data:", error);
      addMessage("Failed to load some data. Using fallback data where possible.", "error");
    } finally {
      setLoading(false);
    }

    // Load the first page of assignments using the paginated endpoint
    try {
      await fetchPaginatedAssignments(1, itemsPerPage);
    } catch (_) {}
  };

  // Fetch paginated assignments from backend endpoint
  const fetchPaginatedAssignments = async (pageNumber = 1, pageSize = ITEMS_PER_PAGE, searchTerm = "") => {
    try {
      setLoading(true);
      const params = [];
      params.push(`page_number=${pageNumber}`);
      params.push(`page_size=${pageSize}`);
      if (searchTerm && String(searchTerm).trim() !== "") {
        params.push(`search=${encodeURIComponent(String(searchTerm).trim())}`);
      }
      const apiUrl = `${APIs.GET_USERS_SEARCH_PAGINATED || "/user-agent-access/get/search-paginated/"}?${params.join("&")}`;
      const response = await fetchData(apiUrl);

      if (!response) return;

      // Handle 'details' or 'access_records' where each record is a user with agent_ids
      const sourceArray = Array.isArray(response.details) ? response.details : Array.isArray(response.access_records) ? response.access_records : null;
      if (sourceArray) {
        // Build user-level rows: one row per user, with agent_count and preserved agent_ids
        const userRows = sourceArray.map((record) => ({
          id: record.user_email || record.email || `${record.user_email}-${Date.now()}`,
          user_email: record.user_email || record.email || "",
          userName: record.user_email ? record.user_email.split("@")[0].replace(/[._]/g, " ") : record.name || "",
          agent_ids: Array.isArray(record.agent_ids) ? record.agent_ids : [],
          agent_count: Array.isArray(record.agent_ids) ? record.agent_ids.length : 0,
          given_access_by: record.given_access_by,
          created_at: record.created_at,
          type: "user",
        }));

        setAssignments(userRows);
        // Use backend-provided user-level total_count (fallback to userRows length)
        setTotalItems(response.total_count || response.total || userRows.length);
        return;
      }

      // Handle typical paginated structures like { results: [], total: n } or { items: [], total: n }
      const records = Array.isArray(response.results) ? response.results : Array.isArray(response.items) ? response.items : Array.isArray(response) ? response : [];
      const total = response.total || response.count || records.length;

      if (records.length === 0) {
        setAssignments([]);
        setTotalItems(0);
        return;
      }

      // If records look like user objects with agent_ids, flatten them
      if (records[0] && (records[0].user_email || records[0].agent_ids)) {
        const flattened = [];
        records.forEach((rec) => {
          const userEmail = rec.user_email || rec.email || "";
          const userName = userEmail ? userEmail.split("@")[0].replace(/[._]/g, " ") : rec.name || "";
          const agentIds = Array.isArray(rec.agent_ids) ? rec.agent_ids : [];
          agentIds.forEach((agentId) => {
            const agentDetails = agents.find((agent) => agent.agentic_application_id === agentId || agent.agent_id === agentId || agent.id === agentId);
            flattened.push({
              id: `${userEmail}-${agentId}`,
              userId: userEmail,
              agentId,
              userEmail,
              userName: userName || userEmail,
              agentName: agentDetails?.agentic_application_name || agentDetails?.agent_name || agentDetails?.name || "Unknown Agent",
              type: "individual",
              createdAt: rec.created_at || new Date().toISOString(),
              givenAccessBy: rec.given_access_by,
              hasAccess: rec.has_access ?? true,
            });
          });
        });
        setAssignments(flattened);
        setTotalItems(flattened.length);
        return;
      }

      // Otherwise assume records are already assignment rows
      setAssignments(records);
      setTotalItems(total || records.length);
    } catch (err) {
      // If paginated endpoint not available or fails, silently keep local assignments
    } finally {
      setLoading(false);
    }
  };

  // Function to refresh assignments for a specific user
  const refreshUserAssignments = async (userEmail) => {
    try {
      const userAgentAccess = await fetchData(`${APIs.GET_USER_AGENT_ACCESS}${encodeURIComponent(userEmail)}`);
      if (userAgentAccess) {
        // Find user object to get name
        const userObj = users.find((u) => u.email === userEmail);
        let userAssignments = [];

        if (Array.isArray(userAgentAccess)) {
          // If response is an array of access objects
          userAssignments = userAgentAccess.map((access) => ({
            id: `${userEmail}-${access.agent_id || access.agentic_application_id || Date.now()}`,
            userId: userObj?.id || userEmail,
            agentId: access.agent_id || access.agentic_application_id,
            userEmail: userEmail,
            userName: userObj?.name || userObj?.username || userEmail,
            agentName: access.agent_name || access.agentic_application_name || "Unknown Agent",
            type: "individual",
            createdAt: access.created_at || new Date().toISOString(),
            givenAccessBy: access.given_access_by,
            hasAccess: typeof access.has_access === "boolean" ? access.has_access : true,
          }));
        } else if (userAgentAccess.agent_ids && Array.isArray(userAgentAccess.agent_ids)) {
          // If response is an object with agent_ids array (like in the screenshot)
          userAssignments = userAgentAccess.agent_ids.map((agentId) => {
            // Find agent details from loaded agents
            const agentDetails = agents.find((agent) => agent.agentic_application_id === agentId || agent.agent_id === agentId || agent.id === agentId);

            return {
              id: `${userEmail}-${agentId}`,
              userId: userObj?.id || userEmail,
              agentId: agentId,
              userEmail: userEmail,
              userName: userObj?.name || userObj?.username || userEmail,
              agentName: agentDetails?.agentic_application_name || agentDetails?.agent_name || agentDetails?.name || "Unknown Agent",
              type: "individual",
              createdAt: userAgentAccess.created_at || new Date().toISOString(),
              givenAccessBy: userAgentAccess.given_access_by,
              hasAccess: userAgentAccess.has_access,
            };
          });
        }

        // Update assignments by removing old ones for this user and adding new ones
        setAssignments((prev) => {
          const filtered = prev.filter((a) => a.userEmail !== userEmail);
          return [...filtered, ...userAssignments];
        });

        return userAssignments;
      }
    } catch (error) {
      console.warn(`Failed to refresh assignments for user ${userEmail}:`, error);
      return [];
    }
    return [];
  };

  const handleAssignAgent = async (e) => {
    e.preventDefault();

    if (!selectedUser || !selectedAgent) {
      addMessage("Please select both user and agent", "error");
      return;
    }

    // Check if assignment already exists
    const existingAssignment = assignments.find((assignment) => assignment.userId === selectedUser && assignment.agentId === selectedAgent);

    if (existingAssignment) {
      addMessage("This assignment already exists", "error");
      return;
    }

    setLoading(true);
    try {
      // Get user email from selected user object
      const userEmail = selectedUserObj?.email || selectedUser;

      if (!userEmail) {
        addMessage("User email is required for granting access", "error");
        setLoading(false);
        return;
      }

      const payload = {
        user_email: userEmail,
        agent_id: selectedAgent,
      };

      // Use the grant endpoint as specified
      try {
        await postData(APIs.GRANT_USER_AGENT_ACCESS, payload);
        addMessage("Agent access granted successfully!", "success");

        // Refresh user assignments using the new function
        const refreshedAssignments = await refreshUserAssignments(userEmail);

        // If refresh didn't return any assignments, add a fallback entry
        if (refreshedAssignments.length === 0) {
          const fallbackAssignment = {
            id: `${userEmail}-${selectedAgent}-${Date.now()}`,
            userId: selectedUser,
            agentId: selectedAgent,
            userEmail: userEmail,
            userName: selectedUserObj?.name || selectedUserObj?.username || userEmail,
            agentName: selectedAgentObj?.agentic_application_name || "Unknown Agent",
            type: "individual",
            createdAt: new Date().toISOString(),
            hasAccess: true,
          };
          setAssignments((prev) => [...prev, fallbackAssignment]);
        }
      } catch (grantError) {
        throw grantError; // Re-throw to be caught by outer catch
      }

      // Reset form and close modal
      resetForm();
      setShowCreateAssignment(false);

      // Reset pagination to first page
      setCurrentPage(1);
    } catch (error) {
      addMessage("Failed to assign agent. Please check console for details.", "error");
    } finally {
      setLoading(false);
    }
  };

  const handleDeleteClick = (assignment) => {
    setAssignmentToDelete(assignment);
    setShowDeleteConfirmation(true);
  };

  // (Removed unused direct revoke helper; revocation is handled via modal actions)

  const handleConfirmDelete = async () => {
    if (!assignmentToDelete) {
      setShowDeleteConfirmation(false);
      setAssignmentToDelete(null);
      return;
    }

    setLoading(true);
    try {
      // Support bulk revoke when assignmentToDelete.agentIds is an array
      const userEmail = assignmentToDelete.userEmail || assignmentToDelete.user_email;
      const agentIds =
        assignmentToDelete.agentIds || (assignmentToDelete.agent_ids ? assignmentToDelete.agent_ids : assignmentToDelete.agentId ? [assignmentToDelete.agentId] : []);

      if (!userEmail || !agentIds || agentIds.length === 0) {
        addMessage("Missing user email or agent ID(s) for revocation", "error");
        setLoading(false);
        return;
      }

      // Revoke each agent sequentially (could batch if backend supports it)
      for (const aid of agentIds) {
        const payload = { user_email: userEmail, agent_id: aid };
        try {
          await postData(APIs.REVOKE_USER_AGENT_ACCESS, payload);
        } catch (e) {
          console.error(`Failed to revoke ${aid} for ${userEmail}:`, e);
        }
      }
      addMessage("Agent access revoked successfully!", "success");

      // Remove all assignments for this user & those specific agentIds from local state
      setAssignments((prev) => {
        const newAssignments = prev.filter((a) => {
          // If row is user-level, remove it entirely when user matches
          if (a.type === "user" && (a.user_email === userEmail || a.userEmail === userEmail)) return false;
          // If row is flattened assignment, remove if matches userEmail and agentId
          if ((a.userEmail === userEmail || a.user_email === userEmail || a.userId === userEmail) && (agentIds.includes(a.agentId) || agentIds.includes(a.agent_id))) return false;
          return true;
        });
        const totalPages = Math.ceil(newAssignments.length / itemsPerPage);
        if (currentPage > totalPages && totalPages > 0) {
          setCurrentPage(totalPages);
        }
        return newAssignments;
      });
    } catch (error) {
      console.error("Error removing assignment:", error);
      addMessage("Failed to revoke agent access. Please check console for details.", "error");
    } finally {
      setLoading(false);
      setShowDeleteConfirmation(false);
      setAssignmentToDelete(null);
    }
  };

  const getUserName = (assignment) => {
    // Try to use stored name first, then lookup in users array
    if (assignment.userName) {
      return assignment.userName;
    }
    const user = users.find((u) => u.id === assignment.userId || u.id === parseInt(assignment.userId));
    return user ? user.name || user.username || user.email : assignment.userEmail || "Unknown User";
  };

  const getAgentName = (assignment) => {
    // Try to use stored name first, then lookup in agents array
    if (assignment.agentName) {
      return assignment.agentName;
    }
    const agent = agents.find((a) => a.agentic_application_id === assignment.agentId || a.id === assignment.agentId || a.id === parseInt(assignment.agentId));
    return agent ? agent.agentic_application_name || agent.agent_name || agent.name : "Unknown Agent";
  };

  // Helper function to get access status
  const getAccessStatus = (assignment) => {
    // If hasAccess is explicitly false, return false
    if (assignment.hasAccess === false) {
      return false;
    }
    // If hasAccess is true or undefined/null, assume true (default for existing records)
    return true;
  };

  // Calculate stats
  const totalUsers = users.length;
  const totalAgents = agents.length;
  const totalAssignments = assignments.length;

  // Show all assignments (no filtering) - client-side filtering handled when rendering

  return (
    <div className={styles.agentAssignmentContainer}>
      {loading && <Loader />}

      {/* Stats Cards */}
      <div className={styles.statsCards}>
        <div className={styles.statCard}>
          <h4>Total Users</h4>
          <p>{totalUsers}</p>
        </div>
        <div className={styles.statCard}>
          <h4>Available Agents</h4>
          <p>{totalAgents}</p>
        </div>
        <div className={styles.statCard}>
          <h4>Total Assignments</h4>
          <p>{totalAssignments}</p>
        </div>
      </div>

      {/* Create Assignment Button */}
      <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 16 }}>
        <button onClick={() => setShowCreateAssignment(true)} className="iafButton iafButtonPrimary">
          Create Assignment
        </button>
      </div>

      {/* Assignment Modal */}
      <Modal isOpen={showCreateAssignment} onClose={() => setShowCreateAssignment(false)} onResetForm={resetForm} title="Create New Assignment">
        <form onSubmit={handleAssignAgent} className={styles.topControls}>
          <div className={styles.controlGroup}>
            <label className={styles.controlLabel}>Select User</label>
            <div className={styles.searchableDropdown}>
              <div
                className={`${styles.dropdownTrigger} ${showUserDropdown ? styles.active : ""}`}
                onClick={handleUserDropdownToggle}
                onKeyDown={handleUserKeyDown}
                tabIndex={0}
                role="combobox"
                aria-expanded={showUserDropdown}
                aria-haspopup="listbox"
                aria-controls="user-dropdown-list">
                <span>{selectedUserObj ? selectedUserObj.name || selectedUserObj.username || selectedUserObj.email : "Select User"}</span>
                <svg
                  width="18"
                  height="18"
                  viewBox="0 0 20 20"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  className={`${styles.chevronIcon} ${showUserDropdown ? styles.rotated : ""}`}>
                  <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              </div>

              {showUserDropdown && (
                <div className={styles.dropdownContent} onClick={(e) => e.stopPropagation()} id="user-dropdown-list" role="listbox">
                  <div className={styles.searchContainer}>
                    <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                      <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                      <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                    <input
                      type="text"
                      placeholder="Search users..."
                      value={userSearchTerm}
                      onChange={(e) => setUserSearchTerm(e.target.value)}
                      className={styles.searchInput}
                      autoComplete="off"
                    />
                  </div>
                  <div className={styles.agentsList}>
                    {filteredUsers.length > 0 ? (
                      filteredUsers.map((user, index) => (
                        <div
                          key={user.id}
                          data-user-index={index}
                          className={`${styles.agentItem} ${index === highlightedUserIndex ? styles.highlighted : ""}`}
                          onClick={() => handleUserSelection(user)}
                          onMouseEnter={() => setHighlightedUserIndex(index)}
                          onMouseLeave={() => setHighlightedUserIndex(-1)}
                          role="option"
                          aria-selected={index === highlightedUserIndex}>
                          <div className={styles.agentName}>{user.name || user.username || user.email}</div>
                        </div>
                      ))
                    ) : (
                      <div className={styles.noAgents}>No users found</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className={styles.controlGroup}>
            <label className={styles.controlLabel}>Select Agent</label>
            <div className={styles.searchableDropdown}>
              <div
                className={`${styles.dropdownTrigger} ${showAgentDropdown ? styles.active : ""}`}
                onClick={handleAgentDropdownToggle}
                onKeyDown={handleAgentKeyDown}
                tabIndex={0}
                role="combobox"
                aria-expanded={showAgentDropdown}
                aria-haspopup="listbox"
                aria-controls="agent-dropdown-list">
                <span>{selectedAgentObj ? selectedAgentObj.agentic_application_name || selectedAgentObj.agent_name || selectedAgentObj.name : "Select Agent"}</span>
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
                    {filteredAgents.length > 0 ? (
                      filteredAgents.map((agent, index) => (
                        <div
                          key={agent.agentic_application_id || agent.id}
                          data-agent-index={index}
                          className={`${styles.agentItem} ${index === highlightedAgentIndex ? styles.highlighted : ""}`}
                          onClick={() => handleAgentSelection(agent)}
                          onMouseEnter={() => setHighlightedAgentIndex(index)}
                          onMouseLeave={() => setHighlightedAgentIndex(-1)}
                          role="option"
                          aria-selected={index === highlightedAgentIndex}>
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
              <button
                type="button"
                onClick={() => {
                  resetForm();
                  setShowCreateAssignment(false);
                }}
                className="iafButton iafButtonSecondary">
                Cancel
              </button>
            </div>
          </div>
        </form>
      </Modal>

      {/* Current Assignments */}
      <div className={styles.assignmentsSection}>
        <div style={{ display: "flex", justifyContent: "flex-end", marginBottom: 12 }}>
          <div className={styles.searchContainer} style={{ maxWidth: 320, width: "100%", position: "relative" }}>
            <input
              type="text"
              placeholder="Search assignments..."
              value={assignmentTableSearch}
              onChange={(e) => {
                const v = e.target.value;
                setAssignmentTableSearch(v);
                if (v.trim() === "") {
                  setAssignmentAppliedSearch("");
                  setCurrentPage(1);
                  fetchPaginatedAssignments(1, itemsPerPage, "");
                }
              }}
              onKeyDown={(e) => {
                /* don't trigger search on Enter; click the icon to apply */
              }}
              className={styles.searchInput}
              autoComplete="off"
              aria-label="Search assignments"
            />
            <button
              type="button"
              onClick={() => {
                setAssignmentAppliedSearch(assignmentTableSearch);
                setCurrentPage(1);
                fetchPaginatedAssignments(1, itemsPerPage, assignmentTableSearch);
              }}
              aria-label="Search assignments"
              title="Search"
              style={{ position: "absolute", right: 8, top: "50%", transform: "translateY(-50%)", background: "transparent", border: "none", cursor: "pointer", padding: 4 }}>
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
            </button>
          </div>
        </div>

        {(() => {
          const s = String(assignmentAppliedSearch || "")
            .toLowerCase()
            .trim();
          const displayedAssignments = s
            ? assignments.filter((a) => {
                const combined = `${a.userName || a.name || a.user_email || a.userEmail || ""} ${a.agentName || a.agent_name || ""}`;
                return combined.toLowerCase().includes(s);
              })
            : assignments;

          if (displayedAssignments.length === 0) {
            return (
              <div className={styles.noAssignments}>
                <h4>No Assignments Found</h4>
                <p>Start by creating your first individual agent assignment above.</p>
              </div>
            );
          }

          return (
            <Table
              headers={["User", "Agent", "Access", "Actions"]}
              data={displayedAssignments}
              renderRow={(assignment, index) => {
                if (assignment && Array.isArray(assignment.agent_ids)) {
                  return (
                    <tr key={assignment.id || assignment.user_email || index}>
                      <td>{assignment.userName || assignment.name || assignment.user_email || assignment.email}</td>
                      <td>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span>{assignment.agent_count} agents</span>
                        </div>
                      </td>
                      <td>{"TRUE"}</td>
                      <td>
                        {/* Try to use 'icon="recycle-bin"' instead of 'fa-user-xmark' for consistency with other components */}
                        <ActionButton
                          icon="fa-solid fa-user-xmark"
                          onClick={() => {
                            setAssignmentToDelete({ userEmail: assignment.user_email, agentIds: assignment.agent_ids, id: assignment.id });
                            setShowDeleteConfirmation(true);
                          }}
                          disabled={loading}
                          title="Revoke All Access"
                          variant="danger"
                        />
                      </td>
                    </tr>
                  );
                }

                return (
                  <tr key={assignment.id}>
                    <td>{getUserName(assignment)}</td>
                    <td>{getAgentName(assignment)}</td>
                    <td>{getAccessStatus(assignment) ? "TRUE" : "FALSE"}</td>
                    <td>
                      {/* Try to use 'icon="recycle-bin"' instead of 'fa-user-xmark' for consistency with other components */}
                      <ActionButton icon="fa-solid fa-user-xmark" onClick={() => handleDeleteClick(assignment)} disabled={loading} title="Revoke Access" variant="danger" />
                    </td>
                  </tr>
                );
              }}
              loading={loading}
              emptyMessage="No individual assignments found"
              pagination={{
                currentPage,
                itemsPerPage,
                totalItems: totalItems || displayedAssignments.length,
                onPageChange: setCurrentPage,
              }}
            />
          );
        })()}
      </div>

      {/* Delete Confirmation Modal */}
      {showDeleteConfirmation && (
        <ConfirmationModal
          message="Are you sure you want to revoke this user's agent access? This action cannot be undone."
          onConfirm={handleConfirmDelete}
          setShowConfirmation={setShowDeleteConfirmation}
        />
      )}

      {/* Agents modal removed per UI request; actions now revoke all agents for a user */}
    </div>
  );
};

export default IndividualAgentAssignment;
