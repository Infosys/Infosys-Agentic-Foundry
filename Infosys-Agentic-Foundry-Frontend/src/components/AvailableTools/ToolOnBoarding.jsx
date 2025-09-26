import React, { useEffect, useState, useRef, useCallback } from "react";
import style from "../../css_modules/ToolOnboarding.module.css";
import { useToolsAgentsService } from "../../services/toolService.js";
import Loader from "../commonComponents/Loader.jsx";
import DropDown from "../commonComponents/DropDowns/DropDown";
import { APIs, BASE_URL } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import Tag from "../Tag/Tag";
import useFetch from "../../Hooks/useAxios.js";
import Cookies from "js-cookie";
import DeleteModal from "../commonComponents/DeleteModal.jsx";
import { useAuth } from "../../context/AuthContext";
import InfoTag from "../commonComponents/InfoTag.jsx";
import MessageUpdateform from "../AskAssistant/MsgUpdateform.jsx";
import SVGIcons from "../../Icons/SVGIcons.js";
import ZoomPopup from "../commonComponents/ZoomPopup.jsx";
import { WarningModal } from "../AvailableTools/WarningModal.jsx";

import AddServer from "../AgentOnboard/AddServer";

function ToolOnBoarding(props) {
  const loggedInUserEmail = Cookies.get("email");
  const userName = Cookies.get("userName");
  const role = Cookies.get("role");
  const { updateTools, addTool, recycleTools } = useToolsAgentsService();

  const formObject = {
    description: "",
    code: "",
    model: "",
    createdBy: userName === "Guest" ? userName : loggedInUserEmail,
    userEmail: "",
  };
  const { isAddTool, setShowForm, editTool, tags, refreshData = true, fetchPaginatedTools, hideServerTab = false, contextType = "tools" } = props;

  const [formData, setFormData] = useState({});
  const [showKnowledge, setShowKnowledge] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorModalVisible, setErrorModalVisible] = useState(false);
  const [errorMessages, setErrorMessages] = useState([]);

  const [files, setFiles] = useState([]);

  const { addMessage, setShowPopup } = useMessage();

  const [models, setModels] = useState([]);
  const [updateModal, setUpdateModal] = useState(false);
  const [responseData, setresponseData] = useState({});

  const [hideCloseIcon, setHideCloseIcon] = useState(false);

  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");

  const [copiedStates, setCopiedStates] = useState({});
  const [forceAdd, setForceAdd] = useState(false);
  // Theme for the whole form (if needed elsewhere)
  const [isDarkTheme, setIsDarkTheme] = useState(true);
  const overlayRef = useRef(null);

  const activeTab = contextType === "servers" ? "addServer" : "toolOnboarding"; // 'toolOnboarding' | 'addServer'

  const { fetchData, deleteData, postData } = useFetch();

  const [floaterForInput, setFloaterForInput] = useState(false);
  const [turnOnDisable, setTurnOnDisable] = useState(false);

  // State for validation response display
  const [validationResult, setValidationResult] = useState(null);
  const [showValidationResult, setShowValidationResult] = useState(false);
  const [inputValidationErrors, setInputValidationErrors] = useState({});
  const validationResultRef = useRef(null);

  useEffect(() => {
    if (validationResultRef.current) {
      validationResultRef.current.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [validationResult, showValidationResult]);

  const fetchAgents = async (e) => {
    try {
      const data = await fetchData(APIs.GET_ALLUPLOADFILELIST);
      setresponseData(data?.user_uploads || {});
    } catch {
      console.error("Tool onboarding failed fetching agent");
      setresponseData({});
    }
  };

  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loading]);

  useEffect(() => {
    setFiles(files);
  }, [files, setFiles]);

  useEffect(() => {
    if (!isAddTool) {
      setFormData((values) => ({
        ...values,
        id: editTool.tool_id,
        description: editTool.tool_description,
        code: editTool.code_snippet,
        model: editTool.model_name,
        userEmail: loggedInUserEmail,
        name: editTool.tool_name,
        createdBy: userName === "Guest" ? null : editTool.created_by,
      }));
    } else if (props?.recycle) {
      setFormData((values) => ({
        ...values,
        item_id: editTool.tool_id,
        description: editTool.tool_description,
        code: editTool.code_snippet,
        model: editTool.model_name,
        userEmail: loggedInUserEmail,
        name: editTool.tool_name,
        createdBy: userName === "Guest" ? null : editTool.created_by,
      }));
    } else {
      setFormData(formObject);
    }
  }, []);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData((values) => ({ ...values, [name]: value }));
  };
  const deleteTool = async () => {
    let response;
    if (props?.recycle) {
      const isAdmin = role && role.toUpperCase() === "ADMIN";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: editTool.created_by, // Use creator email from editTool
        user_email_id: formData.userEmail,
        updated_tag_id_list: initialUpdateTags.filter((e) => e.selected).map((e) => e.tagId),
      };
      let url = "";
      if (props?.selectedType === "tools") {
        url = `${APIs.DELETE_TOOLS_PERMANENTLY}${editTool?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
      }

      response = await deleteData(url);
      if (response?.is_delete) {
        props?.setRestoreData(response);
        addMessage(response?.status_message, "success");
        setLoading(false);
        setShowForm(false);
      } else {
        addMessage(response?.status_message, "error");
        setLoading(false);
        //  setShowForm(false)
      }
    }
  };

  const handleSubmit = async (event, force = false) => {
    if (event) {
      event.preventDefault();
      event.stopPropagation();
    }
    if (userName === "Guest") {
      setUpdateModal(true);
      return;
    }

    setLoading(true);
    let response;
    if (isAddTool) {
      const toolsdata = {
        model_name: formData.model,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: userName === "Guest" ? formData.createdBy : loggedInUserEmail,
        tag_ids: initialTags.filter((e) => e.selected).map((e) => e.tagId),
      };
      response = await addTool(toolsdata, force);
    } else if (!isAddTool && !props?.recycle) {
      const isAdmin = role && role.toUpperCase() === "ADMIN";
      const toolsdata = {
        model_name: formData.model,
        is_admin: isAdmin,
        tool_description: formData.description,
        code_snippet: formData.code,
        created_by: editTool.created_by, // Use creator email from editTool
        user_email_id: formData.userEmail,
        updated_tag_id_list: initialUpdateTags.filter((e) => e.selected).map((e) => e.tagId),
      };
      response = await updateTools(toolsdata, editTool.tool_id, force);
    } else {
      if (props?.recycle) {
        const isAdmin = role && role.toUpperCase() === "ADMIN";
        const toolsdata = {
          model_name: formData.model,
          is_admin: isAdmin,
          tool_description: formData.description,
          code_snippet: formData.code,
          created_by: editTool.created_by, // Use creator email from editTool
          user_email_id: formData.userEmail,
          updated_tag_id_list: initialUpdateTags.filter((e) => e.selected).map((e) => e.tagId),
        };

        let url = "";
        if (props?.selectedType === "tools") {
          url = `${APIs.RESTORE_TOOLS}${editTool?.tool_id}?user_email_id=${encodeURIComponent(Cookies?.get("email"))}`;
        }

        response = await postData(url); // Check if tools data is needed here **
        if (response?.is_restored) {
          props?.setRestoreData(response);
          addMessage(response?.status_message, "success");
          setLoading(false);
          setShowForm(false);
        } else {
          addMessage(response?.status_message, "error");
          setLoading(false);
          //  setShowForm(false)
        }
      }
    }
    if (response?.is_created || response?.is_update) {
      if (isAddTool) {
        addMessage("Tool has been added successfully!", "success");
      } else {
        addMessage("Tool has been updated successfully!", "success");
      }
      setLoading(false);
      if (refreshData && typeof fetchPaginatedTools === "function") {
        await props.fetchPaginatedTools(1);
      }
      setShowForm(false);
      setErrorModalVisible(false);
      setForceAdd(false);
    } else if (!props?.recycle) {
      setLoading(false);
      if (response?.message?.includes("Verification failed:")) {
        const match = response.message.match(/Verification failed:\s*\[(.*)\]/s);
        if (match && match[1]) {
          const raw = match[1];
          let warnings = [];
          try {
            warnings = JSON.parse(`[${raw}]`);
          } catch {
            warnings = raw.split(/(?<!\\)',\s*|(?<!\\)"\,\s*/).map((s) => s.replace(/^['"]|['"]$/g, ""));
          }
          setErrorMessages(warnings);
          setErrorModalVisible(true);
          setForceAdd(true);
          return;
        }
      }
      if (response?.status && response?.response?.status !== 200) {
        addMessage(response?.response?.data?.detail, "error");
      } else {
        addMessage(response?.message ? response?.message : "No response received. Please try again.", "error");
      }
    } else {
      if (props?.recycle) {
        if (response?.is_restored) {
          props?.setRestoreData(response);
          addMessage(response?.status_message, "success");
          setLoading(false);
          setShowForm(false);
        } else {
          addMessage(response?.status_message, "error");
          setLoading(false);
          //  setShowForm(false)
        }
      }
    }
  };
  const [initialTags, setInitialTags] = useState([]);
  useEffect(() => {
    if (tags) {
      const newTags = tags.map((tag) => ({
        tag: tag.tag_name,
        tagId: tag.tag_id,
        selected: false,
      }));
      setInitialTags(newTags);
    }
  }, [tags]);

  const [initialUpdateTags, setInitialUpdateTags] = useState([]);
  useEffect(() => {
    if (editTool.tags && initialTags.length > 0) {
      const newTags = initialTags.map((tag) => {
        if (editTool.tags.some((editTag) => editTag.tag_id === tag.tagId)) {
          return { ...tag, selected: true };
        } else {
          return { ...tag, selected: false };
        }
      });

      setInitialUpdateTags(newTags);
    }
  }, [editTool.tags, initialTags]);

  const toggleTagSelection = (index) => {
    if (isAddTool) {
      const newTags = [...initialTags];
      newTags[index].selected = !newTags[index].selected;
      setInitialTags(newTags);
    } else {
      const newTags = [...initialUpdateTags];
      newTags[index].selected = !newTags[index].selected;
      setInitialUpdateTags(newTags);
    }
  };

  const fetchModels = async () => {
    try {
      const data = await fetchData(APIs.GET_MODELS);
      if (data?.models && Array.isArray(data.models)) {
        const formattedModels = data.models.map((model) => ({
          label: model,
          value: model,
        }));
        setModels(formattedModels);
      } else {
        setModels([]);
      }
    } catch {
      console.error("Fetching failed");
      setModels([]);
    }
  };

  const hasLoadedModelsOnce = useRef(false);
  const hasLoadedAgentsOnce = useRef(false);

  useEffect(() => {
    if (!hasLoadedModelsOnce.current) {
      hasLoadedModelsOnce.current = true;
      fetchModels();
    }
    if (!hasLoadedAgentsOnce.current) {
      hasLoadedAgentsOnce.current = true;
      fetchAgents();
    }
  }, []);

  const { logout } = useAuth();

  const handleLoginButton = (e) => {
    e.preventDefault();
    logout("/login");
  };

  const handleZoomClick = useCallback((title, content) => {
    setPopupTitle(title);
    setPopupContent(content || "");
    setShowZoomPopup(true);
  }, []);

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Code Snippet") {
      setFormData((prev) => ({
        ...prev,
        code: updatedContent,
      }));
    } else if (popupTitle === "Description") {
      setFormData((prev) => ({
        ...prev,
        description: updatedContent,
      }));
    }
  };

  const [inputFields, setInputFields] = useState({});
  const [requiredInputs, setRequiredInputs] = useState([]);

  // validation function for tool execute dynamic inputs
  const validateInputFields = () => {
    const errors = {};
    let hasErrors = false;

    requiredInputs.forEach((inputItem) => {
      const value = inputFields[inputItem.name];
      if (
        value === null ||
        value === undefined ||
        (typeof value === "string" && value.trim() === "") ||
        (Array.isArray(value) && value.length === 0) ||
        (typeof value === "object" && !Array.isArray(value) && Object.keys(value).length === 0)
      ) {
        errors[inputItem.name] = `${toTitleCase(inputItem.name)} is required`;
        hasErrors = true;
      }
    });

    setInputValidationErrors(errors);
    return !hasErrors;
  };

  // Updated runCode function
  const runCode = async (userCode, userInputs = null, handle_default = false) => {
    try {
      if (userCode) {
        let payload = { code: userCode, handle_default: handle_default };
        if (userInputs) {
          payload.inputs = userInputs;
        }
        setLoading(true);
        const validationResponse = await postData(APIs.EXECUTE_CODE, payload);
        // const validationResponse = {
        //   inputs_required: [
        //     {
        //       name: "a",
        //       default: null,
        //     },
        //     {
        //       name: "b",
        //       default: 90,
        //     },
        //   ],
        //   output: "",
        //   output_type: "int",
        //   error: "",
        //   success: true,
        //   feedback: null,
        // };
        setLoading(false);
        if (validationResponse.success && validationResponse.output !== "") {
          // We have to show the string or list of strings of the 'output' key from the response in the "success_error_section"
          setValidationResult({
            type: "success",
            data: validationResponse.output,
          });
          setShowValidationResult(true);
        } else if (!validationResponse.success && validationResponse.error !== "") {
          // We have to show the string or list of strings of the 'error' key from the response in the "success_error_section"
          setValidationResult({
            type: "error",
            data: validationResponse.error,
          });
          setShowValidationResult(true);
        } else if (Array.isArray(validationResponse.inputs_required) && validationResponse.inputs_required.length > 0) {
          setRequiredInputs(validationResponse.inputs_required);
          setFloaterForInput(true);
          setShowValidationResult(false);
          // Reset input fields for new required inputs
          const initialInputs = {};
          validationResponse.inputs_required.forEach((inputItem) => {
            initialInputs[inputItem.name] = inputItem.default || "";
          });
          setInputFields(initialInputs);
        }
      } else {
        addMessage("Please provide valid code to run", "error");
      }
    } catch (err) {
      addMessage("Something went wrong. Please try again.", "error");
      setFloaterForInput(false);
      setLoading(false);
      setRequiredInputs([]);
      setInputFields({});
      setShowValidationResult(false);
      return null;
    }
  };

  // Handler for input changes
  const handleInputFieldChange = (key, value) => {
    setInputFields((prev) => ({
      ...prev,
      [key]: value,
    }));

    // Clear validation error when user starts typing
    if (inputValidationErrors[key]) {
      setInputValidationErrors((prev) => ({
        ...prev,
        [key]: "",
      }));
    }
  };

  // Handler for submitting required inputs
  const handleInputFieldsSubmit = async (e) => {
    e.preventDefault();

    // check if inputs are valid
    if (!validateInputFields()) {
      // addMessage("Please fill in all required fields", "error");
      return; // since error the function skips execution and the error is shown on the form itself
    }

    await runCode(formData.code, inputFields, true);
  };

  const handleCopy = (key, text) => {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      // Use Clipboard API if supported
      navigator.clipboard
        .writeText(text)
        .then(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state
          setTimeout(() => {
            setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
          }, 2000);
        })
        .catch(() => {
          console.error("Failed to copy text, tool on board");
        });
    } else {
      // Fallback for unsupported browsers
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed"; // Prevent scrolling to the bottom of the page
      textarea.style.opacity = "0"; // Hide the textarea
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();

      try {
        document.execCommand("copy");
        setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state
        setTimeout(() => {
          setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
        }, 2000);
      } catch {
        console.error("Fallback: Failed to copy text, on boarding tools");
      } finally {
        document.body.removeChild(textarea); // Clean up
      }
    }
  };

  const applySyntaxHighlighting = useCallback(
    (code) => {
      if (!code) return "";

      // Simple tokenizer approach
      const lines = code.split("\n");
      const highlightedLines = lines.map((line) => {
        let highlightedLine = line;

        // Escape HTML first
        highlightedLine = highlightedLine.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

        // Comments (must be first to avoid conflicts) - LIGHT GREEN
        if (highlightedLine.trim().startsWith("#")) {
          return `<span style="color: ${isDarkTheme ? "#90ee90" : "#32cd32"}; font-style: italic;">${highlightedLine}</span>`;
        }

        // Check for function definitions first (def function_name)
        const defMatch = highlightedLine.match(/(\s*)(def)\s+(\w+)/);
        if (defMatch) {
          const [fullMatch, indent, defKeyword, functionName] = defMatch;
          const replacement = `${indent}<span style="color: ${isDarkTheme ? "#87ceeb" : "#4169e1"}; font-weight: bold;">${defKeyword}</span> <span style="color: ${
            isDarkTheme ? "#ffff99" : "#ffa500"
          }; font-weight: bold;">${functionName}</span>`;
          highlightedLine = highlightedLine.replace(fullMatch, replacement);
        }

        // Check for class definitions (class ClassName)
        const classMatch = highlightedLine.match(/(\s*)(class)\s+(\w+)/);
        if (classMatch) {
          const [fullMatch, indent, classKeyword, className] = classMatch;
          const replacement = `${indent}<span style="color: ${isDarkTheme ? "#87ceeb" : "#4169e1"}; font-weight: bold;">${classKeyword}</span> <span style="color: ${
            isDarkTheme ? "#ffff99" : "#ffa500"
          }; font-weight: bold;">${className}</span>`;
          highlightedLine = highlightedLine.replace(fullMatch, replacement);
        }

        const words = highlightedLine.split(/(\s+)/);
        const highlighted = words.map((word, index) => {
          const trimmed = word.trim();

          if (word.includes("<span")) {
            return word;
          }

          if (
            /^(if|elif|else|for|while|try|except|finally|with|import|from|as|return|yield|break|continue|pass|lambda|and|or|not|is|in|True|False|None|self|async|await)$/.test(
              trimmed
            )
          ) {
            return word.replace(trimmed, `<span style="color: ${isDarkTheme ? "#87ceeb" : "#4169e1"}; font-weight: bold;">${trimmed}</span>`);
          }

          if (/^".*"$/.test(trimmed) || /^'.*'$/.test(trimmed)) {
            return word.replace(trimmed, `<span style="color: ${isDarkTheme ? "#ff6b6b" : "#dc143c"};">${trimmed}</span>`);
          }
          if (/^\d+\.?\d*$/.test(trimmed)) {
            return word.replace(trimmed, `<span style="color: ${isDarkTheme ? "#ffff99" : "#ffa500"}; font-weight: 500;">${trimmed}</span>`);
          }
          if (/^\w+$/.test(trimmed)) {
            const nextWord = words[index + 2];
            if (nextWord && nextWord.trim().startsWith("(")) {
              return word.replace(trimmed, `<span style="color: ${isDarkTheme ? "#ffff99" : "#ffa500"}; font-weight: 500;">${trimmed}</span>`);
            }
          }

          return word;
        });

        return highlighted.join("");
      });

      return highlightedLines.join("\n");
    },
    [isDarkTheme]
  );

  const handleScroll = useCallback((e) => {
    if (overlayRef.current) {
      overlayRef.current.scrollTop = e.target.scrollTop;
      overlayRef.current.scrollLeft = e.target.scrollLeft;
    }
  }, []);

  const toTitleCase = useCallback((str) => {
    return str
      ? str
          .split(/[_\s]+/)
          .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
          .join(" ")
      : "Provide value";
  }, []);

  // Helper function to render validation result content
  const renderValidationContent = (data) => {
    if (data !== null) {
      if (typeof data === "string" || typeof data === "number") {
        return <div className={`${style.success_error_content} ${style[validationResult.type]}`}>{data}</div>;
      } else if (Array.isArray(data)) {

        return (
          <ul className={`${style.success_error_list} ${style.success_error_content} ${style[validationResult.type]}`}>
            {data.map((item, index) => (
              <li key={index}>
                {typeof item === "object" && item !== null ? (
                  // Check if it's a transaction-like object for better formatting
                  item.transaction_id ? (
                    <div>
                      <strong>ID:</strong> {item.transaction_id} |<strong> Amount:</strong> {item.transaction_amount} |<strong> Detail:</strong> {item.transaction_detail}
                    </div>
                  ) : (
                    <pre style={{ margin: 0, whiteSpace: "pre-wrap", fontFamily: "inherit" }}>{JSON.stringify(item, null, 2)}</pre>
                  )
                ) : (
                  item
                )}
              </li>
            ))}
          </ul>
        );
      } else if (typeof data === "object") {
        return <pre className={`${style.success_error_content} ${style[validationResult.type]}`}>{JSON.stringify(data, null, 2)}</pre>;
      } else if (typeof data === "boolean") {
        return <div className={`${style.success_error_content} ${style[validationResult.type]}`}>{toTitleCase(data.toString())}</div>;
      }
    }
    return null;
  };

  const handleKeyDown = useCallback(
    (e) => {
      // Handle Tab key for proper indentation
      if (e.key === "Tab") {
        e.preventDefault();
        const textarea = e.target;
        const start = textarea.selectionStart;
        const end = textarea.selectionEnd;
        const currentCode = formData.code || "";

        if (e.shiftKey) {
          // Shift+Tab: Remove indentation
          const lines = currentCode.split("\n");
          const startLine = currentCode.substring(0, start).split("\n").length - 1;
          const endLine = currentCode.substring(0, end).split("\n").length - 1;

          let newContent = "";
          let newStart = start;
          let newEnd = end;

          for (let i = 0; i < lines.length; i++) {
            if (i >= startLine && i <= endLine && lines[i].startsWith("    ")) {
              lines[i] = lines[i].substring(4);
              if (i === startLine) newStart = Math.max(0, start - 4);
              if (i === endLine) newEnd = Math.max(0, end - 4);
            } else if (i >= startLine && i <= endLine && lines[i].startsWith("\t")) {
              lines[i] = lines[i].substring(1);
              if (i === startLine) newStart = Math.max(0, start - 1);
              if (i === endLine) newEnd = Math.max(0, end - 1);
            }
          }

          newContent = lines.join("\n");
          setFormData((prev) => ({ ...prev, code: newContent }));

          setTimeout(() => {
            textarea.selectionStart = newStart;
            textarea.selectionEnd = newEnd;
          }, 0);
        } else {
          // Tab: Add indentation
          const beforeCursor = currentCode.substring(0, start);
          const afterCursor = currentCode.substring(end);
          const indent = "    "; // 4 spaces for Python

          const newContent = beforeCursor + indent + afterCursor;
          setFormData((prev) => ({ ...prev, code: newContent }));

          setTimeout(() => {
            textarea.selectionStart = textarea.selectionEnd = start + indent.length;
          }, 0);
        }
      }

      // Handle Enter key for auto-indentation
      else if (e.key === "Enter") {
        e.preventDefault();
        const textarea = e.target;
        const start = textarea.selectionStart;
        const currentCode = formData.code || "";
        const beforeCursor = currentCode.substring(0, start);
        const afterCursor = currentCode.substring(start);

        // Get current line
        const lines = beforeCursor.split("\n");
        const currentLine = lines[lines.length - 1];

        // Calculate indentation of current line
        const indentMatch = currentLine.match(/^(\s*)/);
        let indent = indentMatch ? indentMatch[1] : "";

        // Add extra indentation if line ends with colon (Python)
        if (currentLine.trim().endsWith(":")) {
          indent += "    ";
        }

        const newContent = beforeCursor + "\n" + indent + afterCursor;
        setFormData((prev) => ({ ...prev, code: newContent }));

        setTimeout(() => {
          textarea.selectionStart = textarea.selectionEnd = start + 1 + indent.length;
        }, 0);
      }
    },
    [formData.code]
  );

  return (
    <>
      <DeleteModal show={updateModal} onClose={() => setUpdateModal(false)}>
        <p>You are not authorized to update a tool. Please login with registered email.</p>
        <div className={style.buttonContainer}>
          <button onClick={(e) => handleLoginButton(e)} className={style.loginBtn}>
            Login
          </button>
          <button onClick={() => setUpdateModal(false)} className={style.cancelBtn}>
            Cancel
          </button>
        </div>
      </DeleteModal>{" "}
      <div className={style["modalOverlay"]} onClick={() => setShowForm(false)}>
        {loading && <Loader />}
        <div
          className={style["modal"]}
          onClick={(e) => e.stopPropagation()}
          style={{
            width: floaterForInput || showValidationResult ? "calc(100vw - 70px)" : showKnowledge ? "900px" : "790px",
            maxWidth: "calc(100% - 40px)",
            paddingTop: "6px",
            transition: "width 0.3s ease-in-out",
          }}>
          <div
            className={style["container"]}
            style={{ flex: 1, display: "flex", flexDirection: "column", justifyContent: "flex-start", height: "100%", overflowY: "auto", paddingTop: 0, paddingBottom: 0 }}>
            {" "}
            <div
              className={style["main"]}
              style={{
                flex: 1,
                display: "flex",
                flexDirection: "column",
                justifyContent: "flex-start",
                height: "100%",
                overflowY: "auto",
                paddingTop: 0,
                paddingBottom: 0,
                paddingRight: "18px",
              }}>
              {" "}
              <div className={style["nav"]}>
                {" "}
                <div className={style["header"]} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", width: "100%" }}>
                  <div>
                    {(isAddTool ? activeTab === "toolOnboarding" : true) && (
                      <h2 style={{ fontSize: "22px", fontWeight: 700, color: "#0f172a", margin: 0 }}>{props?.recycle ? "RESTORE TOOL" : isAddTool ? "ADD TOOL" : "UPDATE TOOL"}</h2>
                    )}
                    {isAddTool && activeTab === "addServer" && !hideServerTab && <h2 style={{ fontSize: "22px", fontWeight: 700, color: "#0f172a", margin: 0 }}>ADD SERVER</h2>}
                  </div>
                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    {!props?.recycle && activeTab === "toolOnboarding" && (
                      <label className={style["toggle-switch"]}>
                        <input
                          checked={showKnowledge}
                          onChange={(e) => {
                            setShowKnowledge(e.target.checked);
                            setHideCloseIcon(!hideCloseIcon);
                          }}
                          type="checkbox"
                        />
                        <span className={style["slider"]}></span>
                      </label>
                    )}
                    {!props?.recycle && activeTab === "toolOnboarding" && (
                      <div className={showKnowledge ? style["knowledge"] + " " + style["active"] : style["knowledge"]}>KNOWLEDGE</div>
                    )}
                    {/* Close button always visible */}
                    <button className={style["closeBtn"]} onClick={() => setShowForm(false)}>
                      ×
                    </button>
                  </div>
                </div>{" "}
              </div>{" "}
              {/* Only show ToolOnboarding form if editing, else allow tab switch */}{" "}
              {(isAddTool ? activeTab === "toolOnboarding" : true) && (
                <div className={`${style["main-content-wrapper"]} ${floaterForInput || showValidationResult ? style["split-layout"] : ""}`}>
                  <form onSubmit={handleSubmit} className={style["form-section"]}>
                    <div className={style["form-content"]}>
                      <div className={style["form-fields"]}>
                        <div className={style["description-container"]}>
                          <label className={style["label-desc"]}>
                            DESCRIPTION
                            <InfoTag message="Enter a brief description." />
                          </label>
                          <div className={style.textAreaContainer}>
                            <input
                              id="description"
                              name="description"
                              className={style["input-class"] + " " + style.agentTextArea}
                              type="text"
                              onChange={handleChange}
                              value={formData.description}
                              required
                              readOnly={!!props?.recycle}
                              style={props?.recycle ? { background: "#f8f9fa", color: "#6c757d", cursor: "not-allowed" } : {}}
                            />
                            <button type="button" className={style.copyIcon} onClick={() => handleCopy("desc", formData.description)} title="Copy">
                              <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#000000" />
                            </button>
                            <div className={style.iconGroup}>
                              <button type="button" className={style.expandIcon} onClick={() => handleZoomClick("Description", formData.description)} title="Expand">
                                <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#000000" />
                              </button>
                            </div>
                            <span className={`${style.copiedText} ${copiedStates["desc"] ? style.visible : style.hidden}`}>Text Copied!</span>
                          </div>
                        </div>

                        <div className={style["snippet-container"]}>
                          <label className={style["label-desc"]}>
                            CODE SNIPPET
                            <InfoTag message="Enter the code snippet." />
                          </label>
                          <div className={style.codeEditorContainer}>
                            <textarea
                              className={style.codeTextarea}
                              value={formData.code || ""}
                              onChange={props?.recycle ? undefined : (e) => setFormData((prev) => ({ ...prev, code: e.target.value }))}
                              placeholder="Enter your Python code here..."
                              rows={12}
                              readOnly={!!props?.recycle}
                              style={{
                                width: "100%",
                                resize: "vertical",
                                fontFamily: "Consolas, Monaco, 'Courier New', monospace",
                                fontSize: "14px",
                                lineHeight: "1.4",
                                padding: "12px",
                                border: "1px solid #e0e0e0",
                                borderRadius: "8px",
                                backgroundColor: isDarkTheme ? "#1e1e1e" : "#ffffff",
                                color: isDarkTheme ? "#ffffff" : "#000000",
                                outline: "none",
                                boxSizing: "border-box"
                              }}
                            />
                            <button 
                              type="button" 
                              className={style.copyIcon} 
                              onClick={() => handleCopy("code-snippet", formData.code)} 
                              title="Copy"
                            >
                              <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="#ffffff" />
                            </button>
                            <button 
                              type="button" 
                              className={style.playIcon} 
                              onClick={() => runCode(formData.code)} 
                              title="Run Code"
                            >
                              <SVGIcons icon="play" width={16} height={16} fill={isDarkTheme ? "#ffffff" : "#000000"} />
                            </button>
                            <div className={style.iconGroup}>
                              <button 
                                type="button" 
                                className={style.expandIcon} 
                                onClick={() => handleZoomClick("Code Snippet", formData.code)} 
                                title="Expand"
                              >
                                <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="#ffffff" />
                              </button>
                            </div>
                            <span className={`${style.copiedText} ${copiedStates["code-snippet"] ? style.visible : style.hidden}`}>Text Copied!</span>
                          </div>
                        </div>

                        <div className={style["other"]}>
                          <div className={style["model"]}>
                            <label className={style["label-desc"]}>
                              MODEL
                              <InfoTag message="Select the model." />
                            </label>
                            <div>
                              <DropDown
                                options={models}
                                selectStyle={style.selectStyle}
                                id="model"
                                name="model"
                                value={formData.model}
                                onChange={handleChange}
                                className={style["select-class"]}
                                placeholder={"Select Model"}
                                required
                                disabled={!!props?.recycle}
                              />
                            </div>
                          </div>
                          <div className={style["left"]}>
                            <label className={style["label-desc"]}>{isAddTool ? null : "CREATED BY"}</label>
                            <div>
                              {isAddTool ? null : <input id="created-by" className={style["created-input"]} type="text" name="createdBy" value={editTool.created_by} disabled />}
                            </div>
                          </div>
                        </div>
                        {!props?.recycle && (
                          <div className={style["tagsMainContainer"]}>
                            <label htmlFor="tags" className={style["label-desc"]}>
                              Select Tags
                              <InfoTag message="Select the tags." />
                            </label>
                            <div className={style["tagsContainer"]}>
                              {isAddTool
                                ? initialTags.map((tag, index) => (
                                    <Tag key={"li-<ulName>-" + index} index={index} tag={tag.tag} selected={tag.selected} toggleTagSelection={toggleTagSelection} />
                                  ))
                                : initialUpdateTags.map((tag, index) => (
                                    <Tag key={"li-<ulName>-" + index} index={index} tag={tag.tag} selected={tag.selected} toggleTagSelection={toggleTagSelection} />
                                  ))}
                            </div>
                          </div>
                        )}
                      </div>
                      {showKnowledge && (
                        <MessageUpdateform
                          hideComponent={() => {
                            setShowKnowledge(false);
                            setHideCloseIcon(false);
                          }}
                          showKnowledge={showKnowledge}
                        />
                      )}
                    </div>
                    {props?.recycle ? (
                      <>
                        <div className={style["modal-footer"]}>
                          <div className={style["button-class"]}>
                            <button type="submit" className={style["add-button"]}>
                              {"RESTORE"}
                            </button>
                            <button type="button" className={style["add-button"]} onClick={deleteTool}>
                              {"DELETE"}
                            </button>
                          </div>
                        </div>
                      </>
                    ) : (
                      <>
                        <div className={style["modal-footer"]}>
                          <div className={style["button-class"]}>
                            <button type="submit" className={style["add-button"]}>
                              {isAddTool ? (contextType === "servers" ? "ADD SERVER" : "ADD TOOL") : contextType === "servers" ? "UPDATE SERVER" : "UPDATE"}
                            </button>
                            <button onClick={() => setShowForm(false)} className={style["cancel-button"]}>
                              CANCEL
                            </button>
                            {errorMessages.length > 0 && !errorModalVisible && !forceAdd && (
                              <button type="button" className={style["viewWarningsButton"]} onClick={() => setErrorModalVisible(true)}>
                                VIEW WARNINGS
                              </button>
                            )}
                          </div>
                        </div>
                      </>
                    )}
                  </form>
                  {(floaterForInput || showValidationResult) && (
                    <div className={style.executorContainer}>
                      <span
                        onClick={() => {
                          setTurnOnDisable(true);
                          setFloaterForInput(false);
                          setRequiredInputs([]);
                          setInputFields({});
                          setShowValidationResult(false);
                          setValidationResult(null);
                        }}
                        title="Close executor"
                        className={style.closeButton}>
                        <SVGIcons icon="close-icon" color="#dc3545" width={18} height={18} />
                      </span>

                      {floaterForInput && (
                        <div className={style.validationPanel} role="dialog" aria-modal="true" aria-label="Required Inputs">
                          <div className={style.validatorHeader}>
                            <div className={style.headerTitleAndEdit}>
                              <p className={style.headerText}>Required inputs:</p>
                              {/* <div className={style.editAndClose}>
                                {turnOnDisable ? (
                                  <span
                                    onClick={() => {
                                      setTurnOnDisable(false);
                                    }}
                                    title="Enable inputs"
                                    className={style.editButton}>
                                    <SVGIcons className={style.editIcon} icon="pencil" width={18} height={18} />
                                  </span>
                                ) : (
                                  <span
                                    onClick={() => {
                                      setTurnOnDisable(true);
                                    }}
                                    title="Disable inputs"
                                    className={style.editButton}>
                                    <SVGIcons className={style.editIcon} icon="disable_icon" width={18} height={18} />
                                  </span>
                                )}
                              </div> */}
                            </div>
                          </div>
                          <div className={style.ValidationInputWrapper}>
                            {requiredInputs.map((inputItem) => (
                              <label key={inputItem.name} className={style.inputFieldLabel}>
                                {toTitleCase(inputItem.name)}:
                                <input
                                  type="text"
                                  name={inputItem.name}
                                  placeholder={inputItem.default ? `Default: "${inputItem.default}"` : ""}
                                  value={inputFields[inputItem.name] || ""}
                                  onChange={(e) => handleInputFieldChange(inputItem.name, e.target.value)}
                                  className={`${style.validationInput} ${inputValidationErrors[inputItem.name] ? style.inputError : ""}`}
                                  aria-label={inputItem.name}
                                  // disabled={turnOnDisable}
                                  aria-describedby={inputValidationErrors[inputItem.name] ? `${inputItem.name}-error` : undefined}
                                />
                                {inputValidationErrors[inputItem.name] && (
                                  <span id={`${inputItem.name}-error`} className={style.subtleErrorMessage} role="alert">
                                    {/* {inputValidationErrors[inputItem.name]}  */}
                                    This field is required
                                  </span>
                                )}
                              </label>
                            ))}
                            <div className={style.ValidationButtonWrapper}>
                              <button type="button" onClick={handleInputFieldsSubmit} disabled={loading}>
                                {loading ? "Running..." : "Run"}
                              </button>
                              {Object.keys(inputValidationErrors).length > 0 && Object.values(inputValidationErrors).some((error) => error) && (
                                <span className={style.subtleErrorMessage} role="alert">
                                  Please fill all the fields
                                </span>
                              )}
                            </div>
                          </div>
                        </div>
                      )}

                      {showValidationResult && validationResult && (
                        <div ref={validationResultRef} className={`${style.success_error_section} ${style[validationResult.type]} ${!floaterForInput ? style.withTopMargin : ""}`}>
                          <div className={`${style.success_error_header} ${style[validationResult.type]}`}>{validationResult.type === "success" ? <>Success</> : <>Error</>}</div>
                          {validationResult.type === "success" && <p className={style.outputLabel}>Output is:</p>}
                          {renderValidationContent(validationResult.data)}
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}
              {isAddTool && activeTab === "addServer" && !hideServerTab && (
                <div className={style["main-content-wrapper"]}>
                  <AddServer />
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
      <ZoomPopup
        show={showZoomPopup}
        onClose={() => setShowZoomPopup(false)}
        title={popupTitle}
        content={popupContent}
        onSave={handleZoomSave}
        type={popupTitle === "Code Snippet" ? "code" : "text"}
      />
      <WarningModal
        show={errorModalVisible}
        messages={errorMessages}
        onClose={() => {
          setErrorModalVisible(false);
          setForceAdd(false);
        }}
        onForceAdd={async () => {
          setErrorModalVisible(false);
          await handleSubmit(null, true);
        }}
        showForceAdd={forceAdd}
        isUpdate={!isAddTool}
      />
    </>
  );
}

export default ToolOnBoarding;
