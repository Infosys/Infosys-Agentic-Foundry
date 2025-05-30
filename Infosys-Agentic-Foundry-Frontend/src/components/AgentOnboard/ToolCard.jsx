import React, { useState } from "react";
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
  } = props;

  const [addToolClicked, setAddToolClicked] = useState(false);

  const handleAdd = () => {
    if (addToolClicked) {
      setAddToolClicked(false);
      if (tool) {
        setSelectedTool((prevProp) =>
          prevProp.filter((data) => data?.tool_id !== tool_id)
        );
      } else {
        setSelectedAgents((prevProp) =>
          prevProp.filter((data) => data?.agentic_application_id !== agent_id)
        );
      }
    } else {
      setAddToolClicked(true);
      if (tool) setSelectedTool((prevProp) => [...prevProp, tool]);
      else setSelectedAgents((prevProp) => [...prevProp, agent]);
    }
  };

  return (
    <div className={styles.toolContainer} data-isClicked={addToolClicked}>
      <p>{tool?.tool_name || agent?.agentic_application_name}</p>
      <div className={styles.line} />
      <button
        className={styles.addToolBtn}
        onClick={handleAdd}
        data-selected={addToolClicked}
      >
        {addToolClicked ? (
          <SVGIcons icon="fa-user-check" width={20} height={16} />
        ) : (
          <SVGIcons icon="fa-user-plus" width={20} height={16} />
        )}
      </button>
    </div>
  );
};

export default ToolCard;
