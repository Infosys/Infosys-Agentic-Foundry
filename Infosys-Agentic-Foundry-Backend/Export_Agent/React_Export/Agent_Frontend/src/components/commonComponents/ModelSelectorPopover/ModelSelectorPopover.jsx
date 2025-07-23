import React, { useEffect, useRef } from "react";
import "./ModelSelectorPopover.css";


const ModelSelectorPopover = ({
  isOpen,
  onClose,
  onModelSelect,
  selectedModel,
}) => {
  const popoverRef = useRef(null);

  useEffect(() => {
    const handleClickOutside = (event) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(event.target)
      ) {
        onClose(); // Close the popover if the click is outside
      }
    };

    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, [isOpen, onClose]);

  const models = ["Gemini 2.5 Pro", "Claude 3.5", "GPT-4", "o3"]; // List of models

  if (!isOpen) return null;

  return (
    <div
      className="popover-container"
      ref={popoverRef}
      onClick={(e) => e.stopPropagation()}
    >
      <ul className="model-list">
        {models.map((model) => (
          <li
            key={model}
            className={`model-item ${
              selectedModel === model ? "selected" : ""
            }`}
            onClick={() => {
              onModelSelect(model);
              onClose();
            }}
          >
            {model}
          </li>
        ))}
      </ul>
    </div>
  );
};

export default ModelSelectorPopover;