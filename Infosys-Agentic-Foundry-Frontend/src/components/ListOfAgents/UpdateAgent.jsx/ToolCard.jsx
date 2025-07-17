import React, { useMemo, useState } from "react";
import SVGIcons from "../../../Icons/SVGIcons";
import { META_AGENT, PLANNER_META_AGENT } from "../../../constant";
import ToolDetailModal from "../../ToolDetailModal/ToolDetailModal";

const ToolCard = (props) => {
  const {
    styles,
    isMappedTool = false,
    tool,
    addedToolsId,
    addedAgentsId,
    setAddedToolsId,
    removedToolsId,
    removedAgentsId,
    setremovedToolsId,
    setRemovedAgentsId,
    setAddedAgentsId,
    agentType,
    tagsList,
    setShowForm,
    setEditTool,
  } = props;

  const [open,setOpen]=useState(false);

  const updateAddToolsId = (e, toolId) => {
    e.preventDefault();
    const index = addedToolsId.findIndex((id) => id === toolId);
    if (index === -1) {
      setAddedToolsId([...addedToolsId, toolId]);
    } else {
      const temp = [...addedToolsId];
      temp.splice(index, 1);
      setAddedToolsId([...temp]);
    }
  };

  const updateAddAgentsId = (e, agentId) => {
    e.preventDefault();
    const index = addedAgentsId.findIndex((id) => id === agentId);
    if (index === -1) {
      setAddedAgentsId([...addedAgentsId, agentId]);
    } else {
      const temp = [...addedAgentsId];
      temp.splice(index, 1);
      setAddedAgentsId([...temp]);
    }
  };

  const updateRemoveToolsId = (e, toolId) => {
    e.preventDefault();
    const index = removedToolsId.findIndex((id) => id === toolId);
    if (index === -1) {
      setremovedToolsId([...removedToolsId, toolId]);
    } else {
      const temp = [...removedToolsId];
      temp.splice(index, 1);
      setremovedToolsId([...temp]);
    }
  };

  const updateRemoveAgentsId = (e, agentId) => {
    e.preventDefault();
    const index = removedAgentsId.findIndex((id) => id === agentId);
    if (index === -1) {
      setRemovedAgentsId([...removedAgentsId, agentId]);
    } else {
      const temp = [...removedAgentsId];
      temp.splice(index, 1);
      setRemovedAgentsId([...temp]);
    }
  };

  const isSelected = useMemo(
    () =>
      [...addedToolsId, ...removedToolsId].find((id) => id === tool?.tool_id),
    [tool?.tool_id, addedToolsId, removedToolsId]
  );

  const isAgentSelected = useMemo(
    () =>
      [...addedAgentsId, ...removedAgentsId].find(
        (id) => id === tool?.agentic_application_id
      ),
    [tool?.agentic_application_id, addedAgentsId, removedAgentsId]
  );

  const showDetail = (e) => {
    e.preventDefault();
    setOpen(true);
    setEditTool(tool);
  };

  return (
    <div className={styles.toolContainer}>
      <p>
        {(agentType === META_AGENT || agentType === PLANNER_META_AGENT)
          ? tool?.agentic_application_name
          : tool?.tool_name}
      </p>
      <div className={styles.line} />
      <button
        className={styles.toolBtn}
        onClick={
          isMappedTool
            ? (e) =>
                (agentType === META_AGENT || agentType === PLANNER_META_AGENT)
                  ? updateRemoveAgentsId(e, tool?.agentic_application_id)
                  : updateRemoveToolsId(e, tool.tool_id)
            : (e) =>
                (agentType === META_AGENT || agentType === PLANNER_META_AGENT)
                  ? updateAddAgentsId(e, tool?.agentic_application_id)
                  : updateAddToolsId(e, tool.tool_id)
        }
        data-mapped={!!isMappedTool}
        data-selected={
         (agentType === META_AGENT || agentType === PLANNER_META_AGENT) ? !!isAgentSelected : !!isSelected
        }
      >
        {isMappedTool ? (
          isSelected ? (
            <SVGIcons icon="fa-user-check" width={20} height={16} />
          ) : (
            <SVGIcons icon="fa-solid fa-user-xmark" width={20} height={16} />
          )
        ) : isSelected ? (
          <SVGIcons icon="fa-user-check" width={20} height={16} />
        ) : (
          <SVGIcons icon="fa-user-plus" width={20} height={16} />
        )}
      </button>
      <button
        className={styles.toolBtn2}
        onClick={(e) => {
          showDetail(e);
        }}
      >
        <SVGIcons icon="detail" style={{ width: "20", height: "16" }} />
      </button>
      <ToolDetailModal
        isOpen={open}
        onClose={() => {
          setOpen(false);
        }}
        description={
          (agentType === META_AGENT || agentType === PLANNER_META_AGENT)
            ? tool?.agentic_application_description
            : tool?.tool_description
        }
        codeSnippet={tool?.code_snippet}
        agenticApplicationWorkflowDescription={
          tool?.agentic_application_workflow_description
        }
        systemPrompt={tool?.system_prompt}
        isMappedTool={isMappedTool}
        tool={tool}
        tagsList={tagsList}
        setShowForm={setShowForm}
        agentType={agentType}
      />
    </div>
  );
};

export default ToolCard;
