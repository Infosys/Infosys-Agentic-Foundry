import React, { useState, useEffect } from "react";
import styles from "./RecycleBin.module.css";
import Cookies from "js-cookie";
import AgentCard from "../ListOfAgents/AgentCard";
import AgentOnboard from "../AgentOnboard";
import style from "../../css_modules/ListOfAgents.module.css";
import {APIs, BASE_URL,REACT_AGENT,RECYCLE_BIN} from "../../constant";
import style2 from "../../css_modules/AvailableTools.module.css";
import ToolsCard from "../AvailableTools/ToolsCard";
import UpdateAgent from "../ListOfAgents/UpdateAgent.jsx";
import ToolOnBoarding from "../AvailableTools/ToolOnBoarding.jsx";
import useAxios from "../../Hooks/useAxios.js";
import Loader from "../commonComponents/Loader.jsx";
import {RecycleTools,deletedTools } from "../../services/toolService";
import { useMessage } from "../../Hooks/MessageContext";
const RecycleBin = ({ loggedInUserEmail }) => {
  const [selectedType, setSelectedType] = useState("agents");
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
    const [tags, setTags] = useState([]);  
   const { fetchData } = useAxios()
    const [editAgentData, setEditAgentData] = useState("");
    const [showForm, setShowForm] = useState(false);
   const [isAddTool, setIsAddTool] = useState(true);
    const [editTool, setEditTool] = useState({});
    const[restoreData,setRestoreData]=useState()
     const { addMessage, setShowPopup } = useMessage()
      const[loader,setLoader] = useState(false);
const onAgentEdit = (data) => {    
    setEditAgentData(data);
  };
   const handleUpdateAgentClose = () => {
    setEditAgentData(null);
  };
 const RestoreAgent=async(e)=>{
   setLoader(true)
       let response = await RecycleTools("",editAgentData?.agentic_application_id,selectedType);
       if(response?.is_delete){
          setLoader(false)
         addMessage("Agent Restored Successfully", "success");
         setEditAgentData(false)
         setRestoreData(response)
 
       }else{
          setLoader(false)
           setEditAgentData(false)
           addMessage(response.status_message, "error");
       }
   
 }
 const deleteAgent=async(e)=>{
   setLoader(true)
       let response = await deletedTools("", editAgentData?.agentic_application_id,selectedType);
       if(response?.is_delete){
          setLoader(false)
         addMessage(response.status_message, "success");
         setEditAgentData(false)
         setRestoreData(response)
 
       }else{
          setLoader(false)
           setEditAgentData(false)
           addMessage(response.status_message, "error");
       }
   
 }
  useEffect(() => {
    const fetchData = async () => {
      setLoading(true);
      setError(null);
      try {
       const url = `${BASE_URL}${APIs.RECYCLE_BIN}/${selectedType}?user_email_id=${encodeURIComponent(
  Cookies?.get("email")
)}`;
        const response = await fetch(url, {
          headers: {
            accept: "application/json"
          }
        });
        if (!response.ok) throw new Error("Failed to fetch data");
        const json = await response.json();
        setData(json);
      } catch (err) {
        setError(err.message);
        setData([]);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [selectedType,restoreData]);

  return (
    <>
    {showForm && (
        <ToolOnBoarding
          setShowForm={setShowForm}
          isAddTool={isAddTool}
          editTool={editTool}
          setIsAddTool={setIsAddTool}
          tags={""}
          fetchPaginatedTools={""}
          recycle={"recycle"}
          selectedType={selectedType}
          setRestoreData={setRestoreData}
        />
      )}
       <div className={style.container}>
    {/* <div className={styles.recycleBinContainer}> */}
      <div className={styles.toggleWrapper}>
        <label className={styles.switch}>
          <input
            type="radio"
            name="recycleToggle"
            value="agents"
            checked={selectedType === "agents"}
            onChange={() => setSelectedType("agents")}
          />
          <span className={styles.slider}>Agents</span>
        </label>

        <label className={styles.switch}>
          <input
            type="radio"
            name="recycleToggle"
            value="tools"
            checked={selectedType === "tools"}
            onChange={() => setSelectedType("tools")}
          />
          <span className={styles.slider}>Tools</span>
        </label>
      </div>

      <div className={styles.listArea}>
        {loading && <Loader/>}
        {error && <p className={styles.error}>{error}</p>}
        {!loading && !error && selectedType === "agents" && <>
         <div
        className={styles.visibleAgentsContainer}
       
      >
        <div className={style.agentsList} >
       {data.length >0 && data?.map((data1) => (
          <AgentCard
            recycle={"recycle"}
            key={`agent-${Math.random()}`}
            styles={style}
            data={data1}
            onAgentEdit={onAgentEdit}
            deleteAgent={""}
            fetchAgents={""}
          />
       ))}
       </div>
       </div>
        </>}
        {!loading && !error && selectedType === "tools" && <>
        <div className={style2.toolsList}>
              {data.length>0 &&data?.map((item,index) => (
                  <ToolsCard
                    tool={item}
                    setShowForm={setShowForm}
                    isAddTool={isAddTool}
                   setIsAddTool={setIsAddTool}
                    key={`tools-card-${index}`}
                    style={style2}
                    setEditTool={setEditTool}
                    loading={loading}
                    fetchPaginatedTools={""}
                    recycle={"recycle"}
                  />
                ))}
            </div>
        </>}
      </div>
       
      {editAgentData && (
        <div className={style.EditAgentContainer}>
          <UpdateAgent
            onClose={handleUpdateAgentClose}
            agentData={editAgentData}
            setEditAgentData={setEditAgentData}
            tags={""}
            agentsListData={data?.filter(
              (agent) => agent?.agentic_application_type === REACT_AGENT
            )}
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
      {/* </div> */}
    </div>
    </>
  );
};

export default RecycleBin;
