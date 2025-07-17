import React from "react";
import SVGIcons from "../../Icons/SVGIcons";

const ToolCard = (props) => {
  const {
    tool,
    styles,
    setSelectedTool,
    tool_id,
    agent,
    agent_id,
    setSelectedAgents,
    selectedTool,
    selectedAgents,
  } = props;

  const isSelected = tool
    ? selectedTool?.some((t) => t.tool_id === tool_id)
    : selectedAgents?.some((a) => a.agentic_application_id === agent_id);

    const handleAdd = () => {
      if (tool) {
        if (isSelected) {
          setSelectedTool((prev) => prev.filter((t) => t.tool_id !== tool_id));
        } else {
          setSelectedTool((prev) => [...prev, tool]);
        }
      } else {
        if (isSelected) {
          setSelectedAgents((prev) =>
            prev.filter((a) => a.agentic_application_id !== agent_id)
          );
        } else {
          setSelectedAgents((prev) => [...prev, agent]);
        }
      }
    };

  return (
    <div className={styles.toolContainer} data-isclicked={isSelected}>
      <p>{tool?.tool_name || agent?.agentic_application_name}</p>
      <div className={styles.line} />
      <button
        className={styles.addToolBtn}
        onClick={handleAdd}
        data-selected={isSelected}
      >
        {isSelected ? (
          <SVGIcons icon="fa-user-check" width={20} height={16} />
        ) : (
          <SVGIcons icon="fa-user-plus" width={20} height={16} />
        )}
      </button>
    </div>
  );
};

export default ToolCard;
