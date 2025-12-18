import React, { useState, useEffect } from "react";
import PropTypes from "prop-types";
import styles from "../EvaluationPage/EvaluationPage.module.css";
// Reusable split layout for form + response panel
export function SplitLayout({ FormComponent, formProps, response, responseTitle, parseJson }) {
  return (
    <div className={styles.consistencySplitContainer}>
      <div className={styles.consistencyFormPanel}>
        <FormComponent {...formProps} />
      </div>
      {response ? (
        <div className={styles.consistencyResponsePanel}>
          <h3 className={styles.splitLayoutResponseTitle}>{responseTitle}</h3>
          {parseJson ? (() => {
            let parsed;
            try {
              parsed = JSON.parse(response);
            } catch {
              parsed = null;
            }
            if (parsed && typeof parsed === "object") {
              return (
                <div style={{ padding: "8px 0" }}>
                  {Object.entries(parsed).map(([key, value]) => (
                    <div key={key} style={{ marginBottom: "6px" }}>
                      <span className={styles.splitLayoutJsonKey}>{key}:</span> {typeof value === "object" ? JSON.stringify(value) : String(value)}
                    </div>
                  ))}
                </div>
              );
            } else {
              return (
                <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                  {response}
                </pre>
              );
            }
          })() : (
            <pre style={{ whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
              {response}
            </pre>
          )}
        </div>
      ) : null}
    </div>
  );
}


const ThreeColumnLayout = ({
  navigationConfig = [],
  defaultActiveTab = "",
  contentComponents = {},
  customRenderContent = null
}) => {
  const [activeTab, setActiveTab] = useState(defaultActiveTab);
  const [activeMetricsSubTab, setActiveMetricsSubTab] = useState("");

  // Initialize default active tab
  useEffect(() => {
    if (!activeTab && navigationConfig.length > 0) {
      const firstItem = navigationConfig.find(
        item => item.type === "item" || item.type === "subitem"
      );
      if (firstItem) {
        setActiveTab(firstItem.key);
      }
    }
  }, [navigationConfig, activeTab]);

  // Handle tab click
  const handleTabClick = (item) => {
    setActiveTab(item.key);
    
    // Handle metrics sub-tab
    if (item.metricsSubTab) {
      setActiveMetricsSubTab(item.metricsSubTab);
    }
    
    // Call custom onClick if provided
    if (item.onClick) {
      item.onClick(item);
    }
  };

  // Recursively render navigation items and sections
  const renderNavigationItems = (items) => {
    return items.map((item, index) => {
      // Automatically add separator before each parent section except the first
      if (item.type === "section") {
        const separator = index > 0 ? <p key={`separator-${index}`} className={styles.navSeparator}></p> : null;
        // If section is clickable (has component, no children), render as navItem
        if (!item.children && item.component) {
          return (
            <React.Fragment key={item.key}>
              {separator}
              <button
                className={`${styles.navItem} ${activeTab === item.key ? styles.activeItem : ""}`}
                onClick={() => handleTabClick(item)}
                aria-label={item.label}
                title={item.label}
              >
                {item.label}
              </button>
            </React.Fragment>
          );
        }
        // Otherwise, render label and children as submenu items
        return (
          <React.Fragment key={item.key || index}>
            {separator}
            <div>
              <div className={styles.navLabel}>{item.label}</div>
              {item.children && item.children.map((child, childIdx) => (
                <button
                  key={child.key}
                  className={`${styles.navSubItem} ${activeTab === child.key ? styles.activeSubItem : ""}`}
                  onClick={() => handleTabClick(child)}
                  aria-label={child.label}
                  title={child.label}
                >
                  <span className={styles.subItemIcon}>›</span>
                  <span className={styles.subItemText}>{child.label}</span>
                </button>
              ))}
            </div>
          </React.Fragment>
        );
      }
      // Render individual items (item, subitem, separator, etc.)
      switch (item.type) {
        case "separator":
          return <p key={`separator-${index}`} className={styles.navSeparator}></p>;
        case "label":
          return (
            <div key={`label-${index}`} className={styles.navLabel} title={item.label}>
              {item.label}
            </div>
          );
        case "item":
          // Only render as navItem if not inside a section
          return (
            <button
              key={item.key}
              className={`${styles.navItem} ${activeTab === item.key ? styles.activeItem : ""}`}
              onClick={() => handleTabClick(item)}
              aria-label={item.label}
              title={item.label}
            >
              {item.label}
            </button>
          );
        case "subitem":
          return (
            <button
              key={item.key}
              className={`${styles.navSubItem} ${activeTab === item.key ? styles.activeSubItem : ""}`}
              onClick={() => handleTabClick(item)}
              aria-label={item.label}
              title={item.label}
            >
              <span className={styles.subItemIcon}>›</span>
              <span className={styles.subItemText}>{item.label}</span>
            </button>
          );
        default:
          return null;
      }
    });
  };

  // Recursively find the active navigation item by key
  const findActiveItem = (items, key) => {
    for (const item of items) {
      // Match item, subitem, or clickable section (has component, no children)
      if (
        item.key === key && (
          item.type === "item" ||
          item.type === "subitem" ||
          (item.type === "section" && item.component && !item.children)
        )
      ) {
        return item;
      }
      if (item.children) {
        const found = findActiveItem(item.children, key);
        if (found) return found;
      }
    }
    return null;
  };

  // Render content area
  const renderContent = () => {
    if (customRenderContent) {
      return customRenderContent(activeTab, activeMetricsSubTab);
    }

    // Use recursive search for active item
    const activeItem = findActiveItem(navigationConfig, activeTab);
    if (!activeItem) {
      return null;
    }

    const Component = activeItem.component || contentComponents[activeTab];
    if (!Component) {
      return null;
    }

    // Only pass activeMetricsSubTab if explicitly set in componentProps
    const componentProps = {
      ...activeItem.componentProps
    };

    if (activeItem.splitLayout) {
      return (
        <div className={styles.rightTabContent}>
          {activeItem.renderSplitLayout ? (
            activeItem.renderSplitLayout(Component, componentProps)
          ) : (
            <Component {...componentProps} />
          )}
        </div>
      );
    }

    return (
      <div className={styles.rightTabContent}>
        <div className={styles.rightTabContent}>
          <Component {...componentProps} />
        </div>
      </div>
    );
  };

  return (
    <div className={`adminScreen ${styles.sideTabWrapper}`}>
      {/* Left Navigation Column */}
      <nav aria-label="Navigation Tabs" className={styles.leftNav}>
        <div className={styles.leftNavTabs}>
          {renderNavigationItems(navigationConfig)}
        </div>
      </nav>

      {/* Right Content Column */}
      {renderContent()}
    </div>
  );
};

export default ThreeColumnLayout;
