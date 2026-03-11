import React, { useState } from "react";
import styles from "./ResourceAccordion.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

/**
 * ResourceAccordion - Displays selected resources grouped by type in accordion format
 * @param {Object} props
 * @param {disabled} props.disabled - Whether the accordion is disabled
 * @param {Array} props.selectedResources - Array of selected resources
 * @param {function} props.onRemoveResource - Callback to remove a resource
 * @param {function} props.onClearAll - Callback to clear all resources
 */
const ResourceAccordion = ({ selectedResources = [], onRemoveResource, onClearAll, onResourceClick, disabled = false }) => {
  // Group resources by type (tools, servers, agents, validators)
  const groupedResources = selectedResources.reduce((acc, resource) => {
    // Determine resource type based on available properties
    let type = "tools"; // default type

    if (resource.kb_id || resource.kb_name) {
      type = "knowledgebases";
    } else if (resource.server_id || resource.server_name) {
      type = "servers";
    } else if (resource.agent_id || resource.agent_name || resource.agentic_application_id || resource.agentic_application_name) {
      type = "agents";
    } else if (resource.validator_id || resource.validator_name) {
      type = "validators";
    } else if (resource.tool_id || resource.tool_name) {
      type = "tools";
    }

    // Allow override via explicit type property
    if (resource.type) {
      type = resource.type;
    }

    if (!acc[type]) {
      acc[type] = [];
    }
    acc[type].push(resource);
    return acc;
  }, {});

  // State to track expanded accordions
  const [expandedSections, setExpandedSections] = useState({
    tools: true,
    servers: true,
    agents: true,
    validators: true,
    knowledgebases: true,
  });

  // Toggle accordion expansion
  const toggleSection = (section) => {
    setExpandedSections((prev) => ({
      ...prev,
      [section]: !prev[section],
    }));
  };

  // Get icon for resource type
  const getIconForType = (type) => {
    switch (type) {
      case "tools":
        return "wrench";
      case "servers":
        return "server";
      case "agents":
        return "fa-robot";
      case "validators":
        return "clipboard-check";
      case "knowledgebases":
        return "knowledge-base";
      default:
        return "wrench";
    }
  };

  // Get display title for resource type
  const getTitleForType = (type) => {
    switch (type) {
      case "tools":
        return "Tools";
      case "servers":
        return "Servers";
      case "agents":
        return "Agents";
      case "validators":
        return "Validators";
      case "knowledgebases":
        return "Knowledge Bases";
      default:
        return type.toUpperCase();
    }
  };

  // Get resource name safely
  const getResourceName = (resource) => {
    return resource.tool_name || resource.name || resource.server_name || resource.agent_name || resource.agentic_application_name || resource.validator_name || resource.kb_name || "Unknown";
  };

  // Get resource ID safely
  const getResourceId = (resource) => {
    return resource.tool_id || resource.id || resource.server_id || resource.agent_id || resource.agentic_application_id || resource.validator_id || resource.kb_id;
  };

  // Define fixed order for resource types (only show if they have values)
  const resourceTypeOrder = ["tools", "servers", "knowledgebases", "agents", "validators"];
  const orderedResourceTypes = resourceTypeOrder.filter((type) => groupedResources[type] && groupedResources[type].length > 0);

  if (orderedResourceTypes.length === 0) {
    return null;
  }

  return (
    <div className={`${styles.accordionContainer} ${disabled ? styles.accordionContainerDisabled : ""}`}>
      {orderedResourceTypes.map((type) => {
        const resources = groupedResources[type];
        const isExpanded = expandedSections[type];
        const count = resources.length;

        return (
          <div key={type} className={styles.accordionItem}>
            {/* Accordion Header */}
            <div
              className={styles.accordionHeader}
              onClick={() => toggleSection(type)}
              role="button"
              tabIndex={0}
              aria-expanded={isExpanded}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  toggleSection(type);
                }
              }}>
              <div className={styles.accordionHeaderLeft}>
                <span className={styles.chevronIcon}>
                  <SVGIcons icon={isExpanded ? "chevron-down" : "chevronRight"} width={12} height={12} />
                </span>
                <span className={styles.typeIcon}>
                  <SVGIcons icon={getIconForType(type)} width={14} height={14} />
                </span>
                <span className={styles.accordionTitle}>{getTitleForType(type)}</span>
              </div>
              <span className={styles.countBadge}>{count}</span>
            </div>

            {/* Accordion Content */}
            {isExpanded && (
              <div className={styles.accordionContent}>
                <div className={styles.pillsContainer}>
                  {resources.map((resource) => {
                    const isKnowledgeBase = type === "knowledgebases";
                    const clickHandler = !isKnowledgeBase && onResourceClick ? () => onResourceClick(resource) : undefined;
                    return (
                      <div
                        key={getResourceId(resource)}
                        className={`${styles.resourcePill} ${clickHandler ? styles.clickable : ""}`}
                        title={getResourceName(resource)}
                        onClick={clickHandler}
                        role={clickHandler ? "button" : undefined}
                        tabIndex={clickHandler ? 0 : undefined}
                        onKeyDown={(e) => {
                          if (clickHandler && (e.key === "Enter" || e.key === " ")) {
                            e.preventDefault();
                            clickHandler();
                          }
                        }}>
                        <span className={styles.pillText}>{getResourceName(resource)}</span>
                        {onRemoveResource && (
                          <button
                            type="button"
                            className={styles.removePillButton}
                            onClick={(e) => {
                              e.stopPropagation();
                              onRemoveResource(resource);
                            }}
                            aria-label={`Remove ${getResourceName(resource)}`}>
                            <SVGIcons icon="close-icon" width={10} height={10} />
                          </button>
                        )}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
};

export default ResourceAccordion;
