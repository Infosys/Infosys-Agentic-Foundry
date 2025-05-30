import React, { useEffect, useState } from "react";
import DropDown from "../commonComponents/DropDowns/DropDown";
import { APIs, META_AGENT } from "../../constant";
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

  const { addMessage, setShowPopup } = useMessage();

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
    if (selectedAgent === META_AGENT)
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

  useEffect(() => {
    fetchModels();
  }, []);

  const resetSelectedCards = () => {
    const selectedCards = document?.querySelectorAll("[data-isClicked=true]");
    if (selectedCards?.length > 0) {
      for (let card of selectedCards) {
        card?.setAttribute("data-isClicked", false);
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

  // const handleCopy = (key, text) => {
  //   navigator.clipboard.writeText(text);
  //   setCopiedStates((prev) => ({ ...prev, [key]: true })); // Set copied state for the specific key
  //   setTimeout(() => {
  //     setCopiedStates((prev) => ({ ...prev, [key]: false })); // Reset after 2 seconds
  //   }, 2000);
  // };

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
          <label for="agent_name">
            AGENT NAME
            <InfoTag message="Provide name for the agent." />
          </label>
          <input
            type="text"
            id="agent_name"
            name="agent_name"
            disabled={!selectedTool}
            value={formData.agent_name}
            onChange={handleChange}
            required
          />
        </div>
        <div className={styles.inputEmail}>
          <label for="email_id">
            USER EMAIL
            <InfoTag message="Provide email for the agent." />
          </label>
          <input
            type="email"
            id="email_id"
            name="email_id"
            disabled={!selectedTool}
            value={formData.email_id}
            onChange={handleChange}
            required
          />
        </div>
        <div className={styles.inputGoal}>
          <label for="agent_goal">
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
            onClick={() => handleZoomClick("Agent Goal", formData.agent_goal)}
          />
            <button
              type="button"
              className={styles.copyIcon}
              onClick={() => handleCopy("agent_goal", formData.agent_goal)}
              title="Copy"
            >
              <SVGIcons
                icon="fa-regular fa-copy"
                width={16}
                height={16}
                fill="#343741"
              />
            </button>
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
          <label for="workflow_description">
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
            onClick={() =>
              handleZoomClick(
                "Workflow Description",
                formData.workflow_description
              )
            }
          />
            <button
              type="button"
              className={styles.copyIcon}
              onClick={() =>
                handleCopy(
                  "workflow_description",
                  formData.workflow_description
                )
              }
              title="Copy"
            >
              <SVGIcons
                icon="fa-regular fa-copy"
                width={16}
                height={16}
                fill="#343741"
              />
            </button>
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
          <label for="model_name">
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
          <label for="tags">
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
