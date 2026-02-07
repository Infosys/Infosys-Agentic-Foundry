import React from "react";
import styles from "./PartsRenderer.module.css";
import DynamicWidget from "./DynamicWidget";

const PartsRenderer = ({ parts, messageId,sendUserMessage,isMinimized,isFullscreen,selectedAgent
 }) => {
  // Safely extract components from parts
  const getComponents = () => {
    if (!parts) return [];

    // Handle direct array of parts (new format)
    if (Array.isArray(parts)) {
      return parts;
    }

    // Handle direct parts object
    if (parts && Array.isArray(parts)) {
      return parts;
    }
    return [];
  };

  const components = getComponents();

  // If no parts components found, return null
  if (components.length === 0) {
    return (
      <div className={styles.emptyState}>
        <p>No content parts available to render</p>
      </div>
    );
  }

  // Process and render each component
  const renderComponent = (component, index) => {
  const { type, data, metadata = {} } = component;
  // Only use is_last for non-'text' types
  const isLast = type !== "text" ? component.is_last === true : undefined;

    // Map parts types to canvas types
    const getCanvasType = (partsType) => {
      const typeMapping = {
        chart: "chart",
        table: "table",
        image: "image",
        canvas_text: "canvas_text",
        code: "code",
        json: "json",
        email: "email",
      };

      return typeMapping[partsType];
    };

    // Process content based on type
    const processContent = (type, data) => {
      switch (type) {
        case "canvas_text":
          // Ensure text content is always a string
          const textContent = data.content || data.text || data;
          return typeof textContent === "string" ? textContent : JSON.stringify(textContent);

        case "chart":
          // Check for both chart_data and data properties to handle different formats
          if (data?.chart_type && data?.chart_data) {
            return {
              chart_type: data?.chart_type,
              title: data?.title,
              chart_data: data?.chart_data,
            };
          }
          break;

        case "table":
          // Table data with headers and rows
          if (data?.headers && data?.rows) {
            return {
              title: data?.title,
              headers: data?.headers,
              rows: data?.rows,
            };
          }

        case "image":
          // Handle new image format with src and alt properties
          if (data?.src && data?.alt) {
            const result = {
              src: data?.src,
              alt: data?.alt,
            };
            return result;
          }
          // Handle image format with just src
          if (data?.src) {
            const result = {
              src: data?.src,
              alt: data?.alt,
            };
            return result;
          }
          break;

        case "code":
          // Handle new code format with language and code content
          if (data?.language && data?.code) {
            return {
              language: data?.language,
              code: data?.code,
            };
          }

        case "json":
          // Handle JSON format - return only the content inside data object
          return data;
        
        case "email":
          // Handle email format with to, subject, and body properties
          if (data?.to || data?.subject || data?.body) {
            return {
              to: data?.to || "",
              subject: data?.subject || "",
              body: data?.body || "",
            };
          }
          break;

        default:
          // For unknown types, try to extract text content safely
          const defaultContent = data.content || data.text || data;
          return typeof defaultContent === "string" ? defaultContent : JSON.stringify(defaultContent);
      }
    };

    const canvasType = getCanvasType(type);

    // Skip rendering if not a valid canvas type
    if (!canvasType) {
      return null;
    }

    const content = processContent(type, data);

    return (
      <div
        key={index}
        className={styles.componentWrapper}
        data-is-last={isLast ? "true" : undefined}
      >
        {/* Component Header (optional) */}
        {metadata.showHeader !== false && (
          <div className={styles.componentHeader}>
            <div className={styles.componentType}>
              <span className={styles.typeIndicator} data-type={type}>
                {type === "email" && !isLast ? "Email Preview" : type}
              </span>
            </div>
          </div>
        )}

        {/* Component Content */}
        <div className={styles.componentContent}>
          <DynamicWidget
            type={canvasType}
            content={content}
            messageId={`${messageId}-part-${index}`}
            metadata={metadata}
            {...metadata}
            is_last={isLast}
            sendUserMessage={sendUserMessage}
            isMinimized={isMinimized}
            isFullscreen={isFullscreen}
            selectedAgent={selectedAgent}

          />
        </div>
      </div>
    );
  };

  return (
    <div className={styles.partsRenderer}>
      <div className={styles.partsContainer}>{components.map((component, index) => renderComponent(component, index))}</div>
    </div>
  );
};

export default PartsRenderer;
