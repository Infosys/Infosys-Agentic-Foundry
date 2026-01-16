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
    server,
  } = props;

  const [open, setOpen] = useState(false);

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

  const isSelected = useMemo(() => [...addedToolsId, ...removedToolsId].find((id) => id === tool?.tool_id), [tool?.tool_id, addedToolsId, removedToolsId]);

  const isAgentSelected = useMemo(
    () => [...addedAgentsId, ...removedAgentsId].find((id) => id === tool?.agentic_application_id),
    [tool?.agentic_application_id, addedAgentsId, removedAgentsId]
  );

  const showDetail = (e) => {
    e.preventDefault();
    setOpen(true);
    setEditTool(tool || server);
  };
  // Helper to get code preview for servers (robust extraction)
  const getServerCodePreview = (server) => {
    if (!server) return "";
    const type = String(server?.type || "").toUpperCase();
    const raw = server?.raw || server || {};
    if (type === "REMOTE") {
      // For remote servers, return only endpoint
      const endpoint = server?.endpoint || raw?.mcp_url || raw?.endpoint || raw?.mcp_config?.url || "Not available";
      return endpoint;
    }

    const normalizeCandidate = (c) => {
      if (typeof c !== "string") return c;
      let v = c;
      try {
        if (v.startsWith("-c ")) v = v.slice(3);
        v = v.replace(/\\n/g, "\n").replace(/\\"/g, '"');
        if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
          v = v.slice(1, -1);
        }
        const trimmed = v.trim();
        if ((trimmed.startsWith("{") && trimmed.endsWith("}")) || (trimmed.startsWith("[") && trimmed.endsWith("]"))) {
          try {
            const parsed = JSON.parse(trimmed);
            if (typeof parsed === "string") return parsed;
            if (typeof parsed === "object") return JSON.stringify(parsed, null, 2);
            return String(parsed);
          } catch (e) {
            // fall through
          }
        }
      } catch (e) {
        // ignore
      }
      return v;
    };

    const codeCandidates = [
      raw?.mcp_config?.args?.[1],
      raw?.mcp_config?.code_content,
      raw?.mcp_file?.code_content,
      raw?.mcp_config?.file?.content,
      raw?.file?.content,
      raw?.code_content,
      raw?.code,
      raw?.script,
    ];
    for (const c of codeCandidates) {
      const candidate = typeof c === "string" ? normalizeCandidate(c) : c;
      if (typeof candidate === "string" && candidate.trim().length > 0) return candidate;
    }
    if (raw && typeof raw === "object") {
      const fileLike = raw?.mcp_config?.file || raw?.mcp_file || raw?.file || raw?.mcp_config;
      if (fileLike && typeof fileLike === "object") {
        try {
          return JSON.stringify(fileLike, null, 2);
        } catch (e) {
          return String(fileLike);
        }
      }
    }
    return "# No code available for this server.";
  };

  return (
    <div className={styles.toolContainer}>
      <p>{agentType === META_AGENT || agentType === PLANNER_META_AGENT ? tool?.agentic_application_name : tool?.tool_name || server?.name}</p>
      <div className={styles.line} />
      <button
        className={styles.toolBtn}
        onClick={
          isMappedTool
            ? (e) => (agentType === META_AGENT || agentType === PLANNER_META_AGENT ? updateRemoveAgentsId(e, tool?.agentic_application_id) : updateRemoveToolsId(e, tool?.tool_id))
            : (e) => (agentType === META_AGENT || agentType === PLANNER_META_AGENT ? updateAddAgentsId(e, tool?.agentic_application_id) : updateAddToolsId(e, tool?.tool_id))
        }
        data-mapped={!!isMappedTool}
        data-selected={agentType === META_AGENT || agentType === PLANNER_META_AGENT ? !!isAgentSelected : !!isSelected}>
        {isMappedTool ? (
          isSelected ? (
            <SVGIcons icon="fa-user-check" width={20} height={16} />
          ) : (
            <SVGIcons icon="recycle-bin" width={20} height={16} />
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
        }}>
        <SVGIcons icon="detail" style={{ width: "20", height: "16" }} />
      </button>
      <ToolDetailModal
        isOpen={open}
        onClose={() => {
          setOpen(false);
        }}
        description={
          // For remote servers, show only description
          server && String(server?.type || "").toUpperCase() === "REMOTE"
            ? (() => {
                const raw = server?.raw || server || {};
                return server?.description || server?.tool_description || raw?.tool_description || "No description available";
              })()
            : agentType === META_AGENT || agentType === PLANNER_META_AGENT
            ? tool?.agentic_application_description || tool?.tool_description || tool?.description || server?.tool_description || server?.description
            : tool?.tool_description || tool?.description || server?.tool_description || server?.description
        }
        endpoint={
          // For remote servers, pass endpoint separately
          server && String(server?.type || "").toUpperCase() === "REMOTE"
            ? (() => {
                const raw = server?.raw || server || {};
                return server?.endpoint || raw?.mcp_url || raw?.endpoint || raw?.mcp_config?.url || "Not available";
              })()
            : undefined
        }
        codeSnippet={tool?.code_snippet || (server && String(server?.type || "").toUpperCase() === "LOCAL" ? getServerCodePreview(server) : undefined)}
        agenticApplicationWorkflowDescription={
          tool?.agentic_application_workflow_description ||
          server?.workflow_description ||
          server?.agenticApplicationWorkflowDescription ||
          server?.server_workflow_description ||
          tool?.server_workflow_description
        }
        systemPrompt={tool?.system_prompt || server?.systemPrompt || server?.system_prompt || server?.server_system_prompt || tool?.server_system_prompt}
        isMappedTool={isMappedTool}
        tool={tool || server}
        tagsList={tagsList}
        setShowForm={setShowForm}
        agentType={agentType}
        // Hide modify button for remote servers
        hideModifyButton={server && String(server?.type || "").toUpperCase() === "REMOTE"}
        // Pass a prop to force modal to use tool card CSS for description
        useToolCardDescriptionStyle={true}
      />
    </div>
  );
};

export default ToolCard;
