import React, { useState } from "react";
import ThreeColumnLayout from "../commonComponents/ThreeColumnLayout";
import Register from "../Register/Index";
import UpdatePwd from "./UpdatePassword";
import AgentList from "./AgentsList";
import ResponsesList from "./ResponseList";
import ResponseDetail from "./ResponseDetail";
import RecycleBin from "./RecycleBin";
import Unused from "./Unused";
import { APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import useFetch from "../../Hooks/useAxios";
import Loader from "../commonComponents/Loader";
import IndividualAgentAssignment from "./IndividualAgentAssignment.jsx";
import GroupAgentAssignment from "./GroupAgentAssignment.jsx";
import RoleAgentAssignment from "./RoleAgentAssignment.jsx";

// Wrapper for Register with header
import PageWithHeader from "./PageWithHeader";

/**
 * AdminScreenNew - Redesigned Admin screen using ThreeColumnLayout component
 *
 * STRUCTURE:
 * - User Section: Register, Update
 * - Learning (standalone with 3-level navigation: AgentList → ResponsesList → ResponseDetail)
 * - Recycle Bin Section: Agents, Tools
 * - Unused Section: Agents, Tools
 *
 * ROUTE: /admin-new
 */

// Wrapper component for Learning to handle 3-level navigation
const LearningContent = () => {
  const [agents, setAgents] = useState([]);
  const [responses, setResponses] = useState([]);
  const [selectedAgentId, setSelectedAgentId] = useState(null);
  const [selectedAgentName, setSelectedAgentName] = useState(null);
  const [responseDetail, setResponseDetail] = useState(null);
  const [form, setForm] = useState({});
  const [loadingAgents, setLoadingAgents] = useState(false);
  const { addMessage, setShowPopup } = useMessage();
  const { fetchData, putData } = useFetch();

  React.useEffect(() => {
    setShowPopup(!loadingAgents);
  }, [loadingAgents, setShowPopup]);

  React.useEffect(() => {
    loadAgents();
  }, []);

  const extractErrorMessage = (error) => {
    const responseError = { message: null };
    if (error.response?.data?.detail) {
      responseError.message = error.response.data.detail;
    }
    if (error.response?.data?.message) {
      responseError.message = error.response.data.message;
    }
    return responseError.message ? responseError : null;
  };

  const loadAgents = async () => {
    setLoadingAgents(true);
    try {
      setAgents([]);
      const agentsData = await fetchData(APIs.GET_APPROVALS_LIST);
      setAgents(agentsData);
    } catch (err) {
      addMessage(extractErrorMessage(err).message, "error");
    } finally {
      setLoadingAgents(false);
    }
  };

  const loadResponses = async (agentId, agentName) => {
    setSelectedAgentId(agentId);
    setSelectedAgentName(agentName);
    try {
      const responsesData = await fetchData(`${APIs.GET_APPROVALS_BY_ID}${agentId}`);
      setResponses(responsesData);
    } catch (err) {
      addMessage(extractErrorMessage(err).message, "error");
    }
  };

  const loadResponseDetail = async (responseId) => {
    try {
      const data = await fetchData(`${APIs.GET_RESPONSES_DATA}${responseId}`);
      const response = data[0] || {};
      setResponseDetail(response);
      setForm({
        agent_name: response.agent_name || "--",
        response_id: response.response_id || "",
        query: response.query || "",
        old_final_response: response.old_final_response || "",
        old_steps: response.old_steps || "",
        old_response: response.old_response || "",
        feedback: response.feedback || "",
        new_final_response: response.new_final_response || "",
        new_steps: response.new_steps || "",
        approved: response.approved,
        lesson: response.lesson || "",
      });
    } catch (err) {
      addMessage(extractErrorMessage(err).message, "error");
    }
  };

  const handleFormChange = (e) => {
    const { name, value, type, checked } = e.target;
    setForm((prevForm) => ({ ...prevForm, [name]: type === "checkbox" ? checked : value }));
  };

  const handleFormSubmit = async (e) => {
    setLoadingAgents(true);
    e.preventDefault();
    const payload = { ...form };
    try {
      const response = await putData(APIs.UPDATE_APPROVAL_RESPONSE, payload);
      setLoadingAgents(false);
      if (response.is_update) {
        addMessage("Updated successfully!", "success");
        loadResponses(selectedAgentId, selectedAgentName);
      } else {
        addMessage("Update failed!", "error");
      }
    } catch (err) {
      setLoadingAgents(false);
      addMessage("Update failed!", "error");
    }
  };

  return (
    <div style={{ padding: "24px", background: "#fff", minHeight: "calc(100vh - 45px)" }}>
      {loadingAgents && <Loader />}
      {!selectedAgentId ? (
        <AgentList agents={agents} onSelect={loadResponses} />
      ) : responseDetail ? (
        <ResponseDetail
          form={form}
          onChange={handleFormChange}
          onSubmit={handleFormSubmit}
          onBack={() => {
            setResponseDetail(null);
          }}
        />
      ) : (
        <ResponsesList
          responses={responses}
          onSelect={loadResponseDetail}
          onBack={() => {
            setSelectedAgentId(null);
            setSelectedAgentName(null);
            loadAgents();
          }}
          agentName={selectedAgentName}
        />
      )}
    </div>
  );
};

// Wrapper for RecycleBin with type prop
const RecycleBinAgents = () => (
  <PageWithHeader heading="Agents">
    <RecycleBin initialType="agents" />
  </PageWithHeader>
);

const RecycleBinTools = () => (
  <PageWithHeader heading="Tools">
    <RecycleBin initialType="tools" />
  </PageWithHeader>
);

const UnusedAgents = () => (
  <PageWithHeader heading="Agents">
    <Unused initialType="agents" />
  </PageWithHeader>
);

const UnusedTools = () => (
  <PageWithHeader heading="Tools">
    <Unused initialType="tools" />
  </PageWithHeader>
);

const RegisterWithHeader = () => (
  <PageWithHeader heading="Register User">
    <Register isAdminScreen={true} />
  </PageWithHeader>
);

// Wrapper for Update with header
const UpdateWithHeader = () => (
  <PageWithHeader heading="Update Password">
    <UpdatePwd />
  </PageWithHeader>
);

const AdminScreenNew = () => {
  const navigationConfig = [
    {
      type: "section",
      key: "learning",
      label: "Learning",
      component: LearningContent,
    },
    {
      type: "section",
      key: "user",
      label: "User",
      children: [
        {
          type: "item",
          key: "register",
          label: "Register",
          component: RegisterWithHeader,
        },
        {
          type: "item",
          key: "update",
          label: "Update",
          component: UpdateWithHeader,
        },
      ],
    },
    {
      type: "section",
      key: "recycleBin",
      label: "Recycle Bin",
      children: [
        {
          type: "item",
          key: "recycleBinAgents",
          label: "Agents",
          component: RecycleBinAgents,
        },
        {
          type: "item",
          key: "recycleBinTools",
          label: "Tools",
          component: RecycleBinTools,
        },
      ],
    },
    {
      type: "section",
      key: "unused",
      label: "Unused",
      children: [
        {
          type: "item",
          key: "unusedAgents",
          label: "Agents",
          component: UnusedAgents,
        },
        {
          type: "item",
          key: "unusedTools",
          label: "Tools",
          component: UnusedTools,
        },
      ],
    },
    // {
    //   type: "section",
    //   key: "control",
    //   label: "Control",
    //   children: [
    //     {
    //       type: "item",
    //       key: "Individual",
    //       label: "Individual",
    //       component: () => (
    //         <PageWithHeader heading="Individual Agent Assignment">
    //           <IndividualAgentAssignment />
    //         </PageWithHeader>
    //       ),
    //     },
    //     {
    //       type: "item",
    //       key: "Group",
    //       label: "Group",
    //       component: () => (
    //         <PageWithHeader heading="Group Agent Assignment">
    //           <GroupAgentAssignment />
    //         </PageWithHeader>
    //       ),
    //     },
    //     {
    //       type: "item",
    //       key: "Role",
    //       label: "Role",
    //       component: () => (
    //         <PageWithHeader heading="Role Agent Assignment">
    //           <RoleAgentAssignment />
    //         </PageWithHeader>
    //       ),
    //     },
    //   ],
    // },
  ];

  return <ThreeColumnLayout navigationConfig={navigationConfig} defaultActiveTab="learning" />;
};

export default AdminScreenNew;
