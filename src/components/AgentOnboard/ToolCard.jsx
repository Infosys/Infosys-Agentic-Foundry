import React from "react";
import SVGIcons from "../../Icons/SVGIcons";

const ToolCard = (props) => {
  const { tool, styles, setSelectedTool, tool_id, agent, agent_id, setSelectedAgents, selectedTool, selectedAgents, server, setSelectedServers, selectedServers } = props;

  const serverToolId = server?.tool_id;

  const isSelected = tool
    ? selectedTool?.some((t) => t.tool_id === tool_id)
    : agent
    ? selectedAgents?.some((a) => a.agentic_application_id === agent_id)
    : server
    ? selectedServers?.some((s) => s.tool_id === serverToolId)
    : false;

  const handleAdd = () => {
    if (tool) {
      if (isSelected) {
        setSelectedTool((prev) => prev.filter((t) => t.tool_id !== tool_id));
      } else {
        setSelectedTool((prev) => [...prev, tool]);
      }
    } else if (agent) {
      if (isSelected) {
        setSelectedAgents((prev) => prev.filter((a) => a.agentic_application_id !== agent_id));
      } else {
        setSelectedAgents((prev) => [...prev, agent]);
      }
    } else if (server) {
      if (isSelected) {
        setSelectedServers((prev) => prev.filter((s) => s.tool_id !== serverToolId));
      } else {
        setSelectedServers((prev) => [...prev, server]);
      }
    }
  };


  return (
    <div className={styles.toolContainer} data-isclicked={isSelected}>
      <p>{tool?.tool_name || agent?.agentic_application_name || server?.name}</p>
      <div className={styles.line} />
      <button className={styles.addToolBtn} onClick={handleAdd} data-selected={isSelected} aria-label={isSelected ? "Remove" : "Add"}>
        {isSelected ? <SVGIcons icon="fa-user-check" width={20} height={16} /> : <SVGIcons icon="fa-user-plus" width={20} height={16} />}
      </button>
    </div>
  );
};

export default ToolCard;
