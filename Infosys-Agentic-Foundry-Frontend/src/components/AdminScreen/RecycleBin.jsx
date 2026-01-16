import React, { useState, useEffect } from "react";
import styles from "./RecycleBin.module.css";
import Cookies from "js-cookie";
import AgentCard from "../ListOfAgents/AgentCard";
import style from "../../css_modules/ListOfAgents.module.css";
import { APIs, REACT_AGENT } from "../../constant";
import style2 from "../../css_modules/AvailableTools.module.css";
import ToolsCard from "../AvailableTools/ToolsCard";
import UpdateAgent from "../ListOfAgents/UpdateAgent.jsx";
import ToolOnBoarding from "../AvailableTools/ToolOnBoarding.jsx";
import useFetch from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import { useMessage } from "../../Hooks/MessageContext";

const RecycleBin = ({ initialType = "agents" }) => {
  const [selectedType, setSelectedType] = useState(initialType); // for data fetching
  const [activeTab, setActiveTab] = useState(initialType); // for tab highlight
  const [lastTab, setLastTab] = useState(initialType); // to restore tab highlight after modal
  const [data, setData] = useState([]);
  const [error, setError] = useState(null);
  const { fetchData, postData, deleteData } = useFetch();
  const [editAgentData, setEditAgentData] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [isAddTool, setIsAddTool] = useState(true);
  const [editTool, setEditTool] = useState({});
  const [restoreData, setRestoreData] = useState();
  const { addMessage } = useMessage();
  const [loader, setLoader] = useState(false);
  const onAgentEdit = (data) => {
    setEditAgentData(data);
  };
  const handleUpdateAgentClose = () => {
    setEditAgentData(null);
  };
  const RestoreAgent = async (e) => {
    setLoader(true);
    let url = "";
    if (selectedType === "agents") {
      url = `${APIs.RESTORE_AGENTS}${editAgentData?.agentic_application_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    }
    const response = await postData(url);
    if (response?.is_restored) {
      setLoader(false);
      addMessage(response?.status_message, "success");
      setEditAgentData(false);
      setRestoreData(response);
    } else {
      setLoader(false);
      setEditAgentData(false);
      addMessage(response.status_message, "error");
    }
  };
  const deleteAgent = async (e) => {
    setLoader(true);
    let url = "";
    if (selectedType === "agents") {
      url = `${APIs.DELETE_AGENTS_PERMANENTLY}${editAgentData?.agentic_application_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    } else if (selectedType === "tools") {
      url = `${APIs.DELETE_TOOLS_PERMANENTLY}${editAgentData?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
    }
    const response = await deleteData(url);
    if (response?.is_delete) {
      setLoader(false);
      addMessage(response.status_message, "success");
      setEditAgentData(false);
      setRestoreData(response);
    } else {
      setLoader(false);
      setEditAgentData(false);
      addMessage(response.status_message, "error");
    }
  };
  useEffect(() => {
    if (!selectedType) return;
    const fetchRecycleData = async () => {
      setLoader(true);
      setError(null);
      try {
        let url = "";
        if (selectedType === "agents") {
          url = `${APIs.AGENTS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
        } else if (selectedType === "tools") {
          url = `${APIs.TOOLS_RECYCLE_BIN}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
        }
        const json = await fetchData(url);
        setData(json);
      } catch (err) {
        setError(err.response.data.detail);
        setData([]);
      } finally {
        setLoader(false);
      }
    };
    fetchRecycleData();
  }, [selectedType, restoreData]);

  return (
    <>
      {showForm && (
        <ToolOnBoarding
          setShowForm={(show) => {
            if (!show) setActiveTab(lastTab);
            setShowForm(show);
          }}
          isAddTool={isAddTool}
          editTool={editTool}
          setIsAddTool={setIsAddTool}
          tags={""}
          fetchPaginatedTools={""}
          recycle={true}
          selectedType={selectedType}
          setRestoreData={setRestoreData}
        />
      )}
      <div className={style.containerCss}>
        {/* <div className={styles.recycleBinContainer}> */}
        {!initialType && (
          <div className={styles.toggleWrapper}>
            <button
              type="button"
              className={`iafTabsBtn ${activeTab === "agents" ? " active" : ""}`}
              onClick={() => {
                setActiveTab("agents");
                setSelectedType("agents");
              }}>
              Agents
            </button>
            <button
              type="button"
              className={`iafTabsBtn ${activeTab === "tools" ? " active" : ""}`}
              onClick={() => {
                setActiveTab("tools");
                setSelectedType("tools");
              }}>
              Tools
            </button>
          </div>
        )}

        <div className={styles.listArea}>
          {loader && <Loader />}
          {error && <p className={styles.error}>{error}</p>}
          {!loader && !error && selectedType === "agents" && (
            <>
              <div className={styles.visibleAgentsContainer}>
                {!data.length > 0 ? (
                  <>
                    <div className={style.agentsList}>
                      <div className={styles.cardNoData}>
                        <div className={styles.discriptionNoData}>{"No Deleted Agents To Display"}</div>
                      </div>
                    </div>
                  </>
                ) : (
                  <>
                    <div className={style.agentsList}>
                      {data.length > 0 &&
                        data?.map((data1) => (
                          <AgentCard
                            recycle={"recycle"}
                            key={`agent-${data1.agentic_application_id}`}
                            styles={style}
                            data={data1}
                            onAgentEdit={(agent) => {
                              setLastTab(activeTab);
                              setActiveTab("");
                              onAgentEdit(agent);
                            }}
                            deleteAgent={""}
                            fetchAgents={""}
                          />
                        ))}
                    </div>
                  </>
                )}
              </div>
            </>
          )}
          {!loader && !error && selectedType === "tools" && (
            <>
              {!data.length > 0 ? (
                <>
                  <div className={style.agentsList}>
                    <div className={styles.cardNoData}>
                      <div className={styles.discriptionNoData}>{"No Deleted Tools To Display"}</div>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className={style2.toolsList}>
                    {data.length > 0 &&
                      data?.map((item, index) => (
                        <ToolsCard
                          tool={item}
                          setShowForm={(show) => {
                            if (show) setLastTab("tools");
                            if (!show) setActiveTab(lastTab);
                            setShowForm(show);
                          }}
                          isAddTool={isAddTool}
                          setIsAddTool={setIsAddTool}
                          key={`tool-card-${item.tool_id}`}
                          style={style2}
                          setEditTool={setEditTool}
                          loading={loader}
                          fetchPaginatedTools={""}
                          recycle={true}
                        />
                      ))}
                  </div>
                </>
              )}
            </>
          )}
        </div>

        {editAgentData && (
          <div className={style.EditAgentContainer}>
            <UpdateAgent
              onClose={() => {
                setActiveTab(lastTab);
                handleUpdateAgentClose();
              }}
              agentData={editAgentData}
              setEditAgentData={setEditAgentData}
              tags={""}
              agentsListData={data?.filter((agent) => agent?.agentic_application_type === REACT_AGENT)}
              styles={style}
              fetchAgents={""}
              searchTerm={""}
              selectedType={selectedType}
              recycleBin={true}
              setRestoreData={setRestoreData}
              RestoreAgent={RestoreAgent}
              deleteAgent={deleteAgent}
            />
          </div>
        )}
      </div>
    </>
  );
};

export default RecycleBin;
