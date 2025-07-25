import React, { useEffect, useState, useRef } from "react";
import DropDown from "../commonComponents/DropDowns/DropDown";
import { APIs, META_AGENT, PLANNER_META_AGENT } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import Tag from "../../components/Tag/Tag";
import useFetch from "../../Hooks/useAxios";
import Cookies from "js-cookie";
import InfoTag from "../commonComponents/InfoTag";
import SVGIcons from "../../Icons/SVGIcons";
import ZoomPopup from "../commonComponents/ZoomPopup";

const AgentForm = (props) => {
  const {
    styles,
    selectedTool,
    handleClose,
    submitForm,
    selectedAgents,
    selectedAgent,
    loading,
    tags,
    setSelectedAgents,
    setSelectedTool,
  } = props;

  const loggedInUserEmail = Cookies.get("email");

  const initialState = {
    agent_name: "",
    email_id: loggedInUserEmail,
    agent_goal: "",
    workflow_description: "",
    model_name: "gpt4-8k",
  };
  const [formData, setFormData] = useState(initialState);
  const [successMsg, setSuccessMsg] = useState(false);
  const [isFormDisabled, setIsFormDisabled] = useState(true);
  const [models, setModels] = useState([]);
  const [initialTags, setInitialTags] = useState([]);

  const [showZoomPopup, setShowZoomPopup] = useState(false);
  const [popupTitle, setPopupTitle] = useState("");
  const [popupContent, setPopupContent] = useState("");

  const [copiedStates, setCopiedStates] = useState({});

  const { fetchData } = useFetch();

  const {setShowPopup } = useMessage();

  useEffect(() => {
    if (!loading) {
      setShowPopup(true);
    } else {
      setShowPopup(false);
    }
  }, [loading]);

  const handleChange = (event) => {
    const { name, value } = event.target;
    setFormData({
      ...formData,
      [name]: value,
    });
  };

  const onSubmit = (e) => {
    e.preventDefault();
    submitForm(
      {
        ...formData,
        tag_ids: initialTags.filter((e) => e.selected).map((e) => e.tagId),
      },
      () => {
        setSuccessMsg(true);
        setFormData(initialState);
        resetSelectedCards();
        setSelectedAgents([]);
        setSelectedTool([]);
      }
    );
  };

  useEffect(() => {
    if ((selectedAgent === META_AGENT||selectedAgent === PLANNER_META_AGENT))
      setIsFormDisabled(selectedAgents.length <= 0);
    else setIsFormDisabled(selectedTool.length <= 0);
  }, [selectedAgent, selectedAgents, selectedTool]);

  useEffect(() => {
    if (!successMsg) return;
    setTimeout(() => {
      setSuccessMsg(false);
    }, 3000);
  }, [successMsg]);

  useEffect(() => {
    setInitialTags(
      (tags || []).map((tag) => ({
        tag: tag.tag_name,
        tagId: tag.tag_id,
        selected: false,
      }))
    );
  }, [tags]);
  const toggleTagSelection = (index) => {
    const newTags = [...initialTags];
    newTags[index].selected = !newTags[index].selected;
    setInitialTags(newTags);
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
      console.error("Model fetch failed");
      setModels([]);
    }
  };

  // Use a ref to ensure models are fetched only once
  const hasLoadedModelsOnce = useRef(false);

  useEffect(() => {
    if (hasLoadedModelsOnce.current) return;
    hasLoadedModelsOnce.current = true;
    fetchModels();
  }, []);

  const resetSelectedCards = () => {
    const selectedCards = document?.querySelectorAll("[data-isclicked=true]");
    if (selectedCards?.length > 0) {
      for (let card of selectedCards) {
        card?.setAttribute("data-isclicked", false);
        const button = card?.querySelector("[data-selected=true]");
        button?.setAttribute("data-selected", false);
      }
    }
    const tags = initialTags.map((tag) => ({
      ...tag,
      selected: false,
    }));
    setInitialTags(tags);
  };

  const handleZoomClick = (title, content) => {
    setPopupTitle(title);
    setPopupContent(content);
    setShowZoomPopup(true);
  };

  const handleZoomSave = (updatedContent) => {
    if (popupTitle === "Agent Goal") {
      setFormData((prev) => ({
        ...prev,
        agent_goal: updatedContent,
      }));
    } else if (popupTitle === "Workflow Description") {
      setFormData((prev) => ({
        ...prev,
        workflow_description: updatedContent,
      }));
    }
    setShowZoomPopup(false);
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
          console.error("Failed to copy text, Agent form");
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
      } catch  {
        console.error("Fallback: Failed to copy text, agent form");
      } finally {
        document.body.removeChild(textarea); // Clean up
      }
    }
  };

  return (
    <div className={styles.formContainer}>
      {isFormDisabled && <div className={styles.coverLayer} />}
      <form className={styles.form} onSubmit={onSubmit}>
        <div className={styles.inputName}>
          <label htmlFor="agent_name">
            AGENT NAME
            <InfoTag message="Provide name for the agent." />
          </label>
          <input
            type="text"
            id="agent_name"
            name="agent_name"
            disabled={!selectedTool}
            value={formData.agent_name}
            onChange={(e) => {
              const value = e.target.value.replace(/[^a-zA-Z0-9_\s()-{}[\]]/g, "");
              handleChange({
                target: { name: "agent_name", value }
              });
            }}
            required
          />
        </div>
        <div className={styles.inputGoal}>
          <label htmlFor="agent_goal">
            AGENT GOAL
            <InfoTag message="Provide goal for the agent." />
          </label>
          <div className={styles.textAreaContainer}>
            <textarea
              id="agent_goal"
              name="agent_goal"
              disabled={!selectedTool}
              value={formData.agent_goal}
              onChange={handleChange}
              required
              className={styles.agentTextArea}
            />
            <button
              type="button"
              className={styles.copyIcon}
              onClick={isFormDisabled ? (e) => { e.preventDefault(); } : () => handleCopy("agent_goal", formData.agent_goal)}
              title="Copy"
              disabled={isFormDisabled}
            >
              <SVGIcons
                icon="fa-regular fa-copy"
                width={16}
                height={16}
                fill={isFormDisabled ? '#bdbdbd' : '#343741'}
              />
            </button>
            <div className={styles.iconGroup}>
              <button
                type="button"
                className={styles.expandIcon}
                onClick={isFormDisabled ? (e) => { e.preventDefault(); } : () => handleZoomClick("Agent Goal", formData.agent_goal)}
                title="Expand"
                disabled={isFormDisabled}
              >
                <SVGIcons
                  icon="fa-solid fa-up-right-and-down-left-from-center"
                  width={16}
                  height={16}
                  fill={isFormDisabled ? '#bdbdbd' : '#343741'}
                />
              </button>
            </div>
            <span
              className={`${styles.copiedText} ${
                copiedStates["agent_goal"] ? styles.visible : styles.hidden
              }`}
            >
              Text Copied!
            </span>
          </div>
        </div>
        <div className={styles.inputDescription}>
          <label htmlFor="workflow_description">
            WORKFLOW DESCRIPTION
            <InfoTag message="Provide description for the agent." />
          </label>
          <div className={styles.textAreaContainer}>
            <textarea
              id="workflow_description"
              name="workflow_description"
              disabled={!selectedTool}
              value={formData.workflow_description}
              onChange={handleChange}
              required
              className={styles.agentTextArea}
            />
            <button
              type="button"
              className={styles.copyIcon}
              onClick={isFormDisabled ? (e) => { e.preventDefault(); } : () => handleCopy("workflow_description", formData.workflow_description)}
              title="Copy"
              disabled={isFormDisabled}
            >
              <SVGIcons
                icon="fa-regular fa-copy"
                width={16}
                height={16}
                fill={isFormDisabled ? '#bdbdbd' : '#343741'}
              />
            </button>
            <div className={styles.iconGroup}>
              <button
                type="button"
                className={styles.expandIcon}
                onClick={isFormDisabled ? (e) => { e.preventDefault(); } : () => handleZoomClick("Workflow Description", formData.workflow_description)}
                title="Expand"
                disabled={isFormDisabled}
              >
                <SVGIcons
                  icon="fa-solid fa-up-right-and-down-left-from-center"
                  width={16}
                  height={16}
                  fill={isFormDisabled ? '#bdbdbd' : '#343741'}
                />
              </button>
            </div>
            <span
              className={`${styles.copiedText} ${
                copiedStates["workflow_description"]
                  ? styles.visible
                  : styles.hidden
              }`}
            >
              Text Copied!
            </span>
          </div>
        </div>
        <div className={styles.selectContainer}>
          <label htmlFor="model_name">
            MODEL
            <InfoTag message="Select model for the agent." />
          </label>
          <DropDown
            options={models}
            selectStyle={styles.selectStyle}
            disabled={!selectedTool}
            id="model_name"
            name="model_name"
            value={formData.model_name}
            onChange={handleChange}
            required
          />
        </div>
        <div className={styles.inputTags}>
          <label htmlFor="tags">
            Select Tags
            <InfoTag message="Select tags for the agent." />
          </label>
          <div className={styles.tagsContainer}>
            {initialTags.map((tag, index) => (
              <Tag
                key={index}
                index={index}
                tag={tag.tag}
                selected={tag.selected}
                toggleTagSelection={toggleTagSelection}
              />
            ))}
          </div>
        </div>
        <div className={styles.closeAndAddBtn}>
          <button
            className={styles.closeBtn}
            disabled={!selectedTool}
            onClick={handleClose}
          >
            Close
          </button>
          <input
            type="submit"
            value="ADD AGENT"
            className={styles.submitBtn}
            disabled={!selectedTool}
          />
        </div>
      </form>
      <ZoomPopup
        show={showZoomPopup}
        onClose={() => setShowZoomPopup(false)}
        title={popupTitle}
        content={popupContent}
        onSave={handleZoomSave}
      />
    </div>
  );
};

export default AgentForm;
