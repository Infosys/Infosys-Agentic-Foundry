import React, { useEffect, useState } from "react";
import styles from "./GroupOnBoarding.module.css";
import Loader from "../commonComponents/Loader.jsx";
import { APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios.js";
import Cookies from "js-cookie";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import SVGIcons from "../../Icons/SVGIcons";
import TextareaWithActions from "../commonComponents/TextareaWithActions";

function GroupOnBoarding(props) {
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const userDepartment = Cookies.get("department");

  const formObject = {
    name: "",
    description: "",
    createdBy: userName === "Guest" ? userName : loggedInUserEmail,
  };

  const { isAddGroup, setShowForm, editGroup, fetchGroupsAfterFormClose } = props;

  const [formData, setFormData] = useState(formObject);
  const [loading, setLoading] = useState(false);
  const [agents, setAgents] = useState([]);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [selectedUsers, setSelectedUsers] = useState([]);
  const [departmentUsers, setDepartmentUsers] = useState([]);

  const { addMessage, setShowPopup } = useMessage();
  const { fetchData, postData, putData } = useFetch();

  // Control global popup visibility on loading change
  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loading]);

  // State to store full group details for edit mode
  const [fullGroupData, setFullGroupData] = useState(null);
  // Store the original data at the time of loading (for diff calculation)
  const [originalGroupData, setOriginalGroupData] = useState(null);

  // Load agents and department users on mount and fetch full group details for edit mode
  useEffect(() => {
    const loadData = async () => {
      try {
        // Load agents
        const agentsData = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
        if (Array.isArray(agentsData)) {
          setAgents(agentsData);
        } else if (agentsData?.agents && Array.isArray(agentsData.agents)) {
          setAgents(agentsData.agents);
        }

        // Load department users
        if (userDepartment) {
          try {
            const endpoint = APIs.GET_DEPARTMENT_USERS.replace("{department_name}", encodeURIComponent(userDepartment));
            const usersResponse = await fetchData(endpoint);
            if (usersResponse?.users && Array.isArray(usersResponse.users)) {
              setDepartmentUsers(usersResponse.users);
            } else if (Array.isArray(usersResponse)) {
              setDepartmentUsers(usersResponse);
            }
          } catch (usersError) {
            console.warn("Could not fetch department users:", usersError);
          }
        }

        // For edit mode, fetch full group details to ensure we have all data
        if (!isAddGroup && editGroup && (editGroup.group_name || editGroup.name)) {
          const groupName = editGroup.group_name || editGroup.name;
          try {
            const groupDetails = await fetchData(`${APIs.GET_GROUP_BY_NAME}${encodeURIComponent(groupName)}`);
            console.log("Fetched full group details:", groupDetails);
            if (groupDetails) {
              setFullGroupData(groupDetails);
              // Store original data for diff calculation - this won't change during editing
              setOriginalGroupData({
                user_emails: groupDetails.user_emails || editGroup.user_emails || [],
                agent_ids: groupDetails.agent_ids || editGroup.agent_ids || [],
              });
            }
          } catch (groupError) {
            console.warn("Could not fetch full group details, using partial data:", groupError);
            setFullGroupData(editGroup);
            // Store original data from editGroup
            setOriginalGroupData({
              user_emails: editGroup.user_emails || [],
              agent_ids: editGroup.agent_ids || [],
            });
          }
        }
      } catch (error) {
        console.error("Error loading data:", error);
      }
    };

    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAddGroup, editGroup]);

  // Populate form for edit mode - use fullGroupData when available, fallback to editGroup
  useEffect(() => {
    // Use fullGroupData if available (has complete details), otherwise use editGroup
    const groupData = fullGroupData || editGroup;
    // Check if groupData has valid data (not empty object)
    const hasValidGroupData = groupData && Object.keys(groupData).length > 0 && (groupData.group_name || groupData.name);

    if (!isAddGroup && hasValidGroupData) {
      setFormData({
        name: groupData.group_name || groupData.name || "",
        description: groupData.group_description || groupData.description || "",
        createdBy: groupData.created_by || loggedInUserEmail,
      });

      // Pre-select agents (only when agents are loaded)
      if (groupData.agent_ids && Array.isArray(groupData.agent_ids) && agents.length > 0) {
        const preSelectedAgents = agents.filter((a) => groupData.agent_ids.includes(a.agentic_application_id));
        setSelectedAgents(preSelectedAgents);
      } else if (groupData.agent_ids && Array.isArray(groupData.agent_ids)) {
        // If agents not loaded yet, clear selection - it will be set when agents load
        setSelectedAgents([]);
      }

      // Pre-select users
      if (groupData.user_emails && Array.isArray(groupData.user_emails)) {
        const preSelectedUsers = groupData.user_emails.map((email) => ({
          id: email,
          email: email,
          name: email.split("@")[0].replace(/[._]/g, " "),
        }));
        setSelectedUsers(preSelectedUsers);
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAddGroup, editGroup, fullGroupData, agents]);

  const handleClose = () => {
    setShowForm(false);
  };

  const handleChange = (e) => {
    const { name, value } = e.target;
    setFormData((prev) => ({ ...prev, [name]: value }));
  };

  const handleUserSelect = (userEmail) => {
    if (!userEmail) return;

    if (selectedUsers.some((u) => u.email === userEmail)) {
      addMessage("User already added", "error");
      return;
    }

    const user = departmentUsers.find((u) => u.email === userEmail);
    const newUser = {
      id: userEmail,
      email: userEmail,
      name: user?.user_name || userEmail.split("@")[0].replace(/[._]/g, " "),
    };

    setSelectedUsers((prev) => [...prev, newUser]);
  };

  const handleRemoveUser = (email) => {
    setSelectedUsers((prev) => prev.filter((u) => u.email !== email));
  };

  const handleAgentSelect = (agent) => {
    if (!selectedAgents.find((a) => a.agentic_application_id === agent.agentic_application_id)) {
      setSelectedAgents((prev) => [...prev, agent]);
    }
  };

  const handleRemoveAgent = (agentId) => {
    setSelectedAgents((prev) => prev.filter((a) => a.agentic_application_id !== agentId));
  };

  const filteredAgents = agents.filter(
    (agent) => !selectedAgents.find((a) => a.agentic_application_id === agent.agentic_application_id)
  );

  // Filter out already selected users from dropdown options
  const filteredUsers = departmentUsers.filter(
    (user) => !selectedUsers.find((u) => u.email === user.email)
  );

  const handleSubmit = async (e) => {
    if (e) e.preventDefault();

    if (!formData.name.trim()) {
      addMessage("Group name is required", "error");
      return;
    }

    setLoading(true);
    try {
      let result;

      if (isAddGroup) {
        // For creating a new group, send the full payload
        const payload = {
          group_name: formData.name.trim(),
          group_description: formData.description.trim(),
          user_emails: selectedUsers.map((u) => u.email),
          agent_ids: selectedAgents.map((a) => a.agentic_application_id),
          created_by: formData.createdBy,
        };
        result = await postData(APIs.CREATE_GROUP, payload);
      } else {
        // For updating, we need to call separate endpoints for users and agents
        const groupName = editGroup.group_name || editGroup.name;
        if (!groupName) {
          throw new Error("Group name is missing for update");
        }

        // Use originalGroupData for diff calculation (captured at load time, doesn't change during editing)
        const currentUsers = originalGroupData?.user_emails || [];
        const currentAgents = originalGroupData?.agent_ids || [];

        // Get new selections from the UI
        const newUsers = selectedUsers.map((u) => u.email);
        const newAgents = selectedAgents.map((a) => a.agentic_application_id);

        // Calculate differential changes
        const usersToAdd = newUsers.filter((email) => !currentUsers.includes(email));
        const usersToRemove = currentUsers.filter((email) => !newUsers.includes(email));
        const agentsToAdd = newAgents.filter((agentId) => !currentAgents.includes(agentId));
        const agentsToRemove = currentAgents.filter((agentId) => !newAgents.includes(agentId));

        console.log("=== UPDATE GROUP DEBUG ===");
        console.log("Original users (from server):", currentUsers);
        console.log("Selected users (current UI):", newUsers);
        console.log("Users to ADD:", usersToAdd);
        console.log("Users to REMOVE:", usersToRemove);
        console.log("Original agents (from server):", currentAgents);
        console.log("Selected agents (current UI):", newAgents);
        console.log("Agents to ADD:", agentsToAdd);
        console.log("Agents to REMOVE:", agentsToRemove);

        const encodedGroupName = encodeURIComponent(groupName);

        // Single PUT request with combined payload (description + user/agent changes)
        const updateUrl = `${APIs.UPDATE_GROUP}${encodedGroupName}`;
        const updatePayload = {
          group_description: formData.description.trim(),
          add_users: usersToAdd,
          remove_users: usersToRemove,
          add_agents: agentsToAdd,
          remove_agents: agentsToRemove,
        };

        console.log("Update group URL:", updateUrl);
        console.log("Update group payload:", updatePayload);

        result = await putData(updateUrl, updatePayload);
        console.log("Update group result:", result);
      }

      // Check for successful response - handle various API response formats
      const isSuccess = result &&
        (result.success === true ||
          result.status === "success" ||
          result.message?.toLowerCase().includes("success") ||
          (result.group_name && !result.error) ||
          (!result.error && !result.detail && result.success !== false));

      if (isSuccess) {
        addMessage(`Group "${formData.name}" ${isAddGroup ? "created" : "updated"} successfully!`, "success");
        if (fetchGroupsAfterFormClose) {
          fetchGroupsAfterFormClose();
        }
        handleClose();
      } else {
        throw new Error(result?.message || result?.detail || result?.error || `Failed to ${isAddGroup ? "create" : "update"} group`);
      }
    } catch (error) {
      console.error("Error saving group:", error);
      const errorMessage = error.response?.data?.detail || error.response?.data?.message || error.message || `Failed to ${isAddGroup ? "create" : "update"} group`;
      addMessage(errorMessage, "error");
    } finally {
      setLoading(false);
    }
  };

  // Footer buttons
  const renderFooter = () => (
    <div className={styles.footerButtons}>
      <IAFButton type="secondary" onClick={handleClose}>
        Cancel
      </IAFButton>
      <IAFButton type="primary" onClick={handleSubmit} disabled={loading || !formData.name.trim()}>
        {loading ? "Saving..." : isAddGroup ? "Create Group" : "Update Group"}
      </IAFButton>
    </div>
  );

  return (
    <>
      {loading && <Loader />}
      <FullModal
        isOpen={true}
        title={isAddGroup ? "Create Group" : "Edit Group"}
        onClose={handleClose}
        footer={renderFooter()}
      >
        <form onSubmit={handleSubmit} className="form-section">
          <div className="formContent">
            <div className="form">
              {/* Group Name */}
              <div className="formGroup">
                <label className="label-desc">
                  Group Name <span className="required">*</span>
                </label>
                <input
                  type="text"
                  name="name"
                  value={formData.name}
                  onChange={handleChange}
                  placeholder="Enter group name"
                  className="input"
                  disabled={!isAddGroup}
                  required
                />
              </div>

              {/* Description */}
              <div className="formGroup">
                <TextareaWithActions
                  name="description"
                  value={formData.description}
                  onChange={handleChange}
                  label="Description"
                  placeholder="Describe the purpose of this group..."
                  rows={3}
                  showCopy={true}
                  showExpand={true}
                  zoomType="text"
                />
              </div>

              {/* Add Users */}
              <div className="formGroup">
                <label className="label-desc">Add Members</label>
                <NewCommonDropdown
                  options={filteredUsers.map((u) => u.email)}
                  selected=""
                  onSelect={(val) => {
                    if (val) handleUserSelect(val);
                  }}
                  placeholder="Search and select users"
                  showSearch={true}
                />

                {/* Selected Users Tags */}
                {selectedUsers.length > 0 && (
                  <div className={styles.tagsContainer}>
                    {selectedUsers.map((user) => (
                      <div key={user.email} className={styles.tag}>
                        <SVGIcons icon="user" width={14} height={14} color="var(--content-color)" />
                        <span className={styles.tagText}>{user.email}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveUser(user.email)}
                          className={styles.tagRemove}
                          title="Remove user"
                        >
                          <SVGIcons icon="x" width={12} height={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {/* Assign Agents */}
              <div className="formGroup">
                <label className="label-desc">Assign Agents</label>
                <NewCommonDropdown
                  options={filteredAgents.map((a) => a.agentic_application_name || a.agent_name || a.name)}
                  selected=""
                  onSelect={(val) => {
                    const agent = agents.find((a) => (a.agentic_application_name || a.agent_name || a.name) === val);
                    if (agent) handleAgentSelect(agent);
                  }}
                  placeholder="Search and select agents"
                  showSearch={true}
                />

                {/* Selected Agents Tags */}
                {selectedAgents.length > 0 && (
                  <div className={styles.tagsContainer}>
                    {selectedAgents.map((agent) => (
                      <div key={agent.agentic_application_id} className={styles.tag}>
                        <SVGIcons icon="cpu" width={14} height={14} color="var(--content-color)" />
                        <span className={styles.tagText}>
                          {agent.agentic_application_name || agent.agent_name || agent.name}
                        </span>
                        <button
                          type="button"
                          onClick={() => handleRemoveAgent(agent.agentic_application_id)}
                          className={styles.tagRemove}
                          title="Remove agent"
                        >
                          <SVGIcons icon="x" width={12} height={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </form>
      </FullModal>
    </>
  );
}

export default GroupOnBoarding;
