import { useState, useEffect, useRef, useCallback } from "react";
import { usePermissions } from "../../context/PermissionsContext";
import EvaluationScore from "../AdminScreen/EvaluationScore";
import AgentsEvaluator from "../AgentsEvaluator";
import GroundTruth from "../GroundTruth/GroundTruth";
import ConsistencyTab from "./ConsistencyTab";
import SubHeader from "../commonComponents/SubHeader";
import SVGIcons from "../../Icons/SVGIcons";
import useFetch from "../../Hooks/useAxios";
import { APIs, agentTypesDropdown, PIPELINE_AGENT } from "../../constant";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import Loader from "../commonComponents/Loader";
import styles from "./EvaluationPageNew.module.css";

// Filter out pipeline agent type for Metrics section
const metricsAgentTypes = agentTypesDropdown.filter(
  (type) => type.value !== PIPELINE_AGENT && type.value !== "pipeline"
);

/**
 * EvaluationPageNew - Redesigned Evaluation screen using hamburger navigation pattern
 *
 * STRUCTURE:
 * Layout.dashboardContainer > pageContainer > SubHeader > PageLayout > content
 *
 * TABS:
 * - LLM AS JUDGE: LLM as Judge (standalone)
 * - Metrics: Evaluation Records, Tool Efficiency, Agent Efficiency
 * - Evaluation: Ground Truth, Consistency (has listWrapper with SummaryLine)
 */

const EvaluationPageNew = () => {
  // Permission checks - must be called before any conditional returns
  const { permissions, loading: permissionsLoading, hasPermission } = usePermissions();

  const [menuOpen, setMenuOpen] = useState(false);
  const [activeTab, setActiveTab] = useState("llmAsJudge");

  // Header dropdown state (replacing hamburger)
  const [openDropdown, setOpenDropdown] = useState(null);
  const [dropdownPosition, setDropdownPosition] = useState({ top: 0, left: 0 });
  const closeTimeoutRef = useRef(null);

  // Agent filter state for Metrics section
  const [availableAgents, setAvailableAgents] = useState([]);
  const [selectedAgentNames, setSelectedAgentNames] = useState([]);
  const [selectedAgentTypes, setSelectedAgentTypes] = useState([]);
  const [filterTrigger, setFilterTrigger] = useState(0); // Used to trigger filter in EvaluationScore

  // Trigger for Consistency tab's plus button
  const [consistencyPlusTrigger, setConsistencyPlusTrigger] = useState(0);

  // Search state for SubHeader - moved here to comply with hooks rules
  const [searchValue, setSearchValue] = useState("");

  const { fetchData } = useFetch();
  const hasLoadedAgentsOnce = useRef(false);

  // Permission check for evaluation access
  const evaluationAllowed = typeof hasPermission === "function"
    ? hasPermission("evaluation_access")
    : !(permissions && permissions.evaluation_access === false);

  // Metrics section tab keys for conditional filter display
  const metricsTabs = ["evaluationRecords", "toolsEfficiency", "agentsEfficiency"];
  const isMetricsSection = metricsTabs.includes(activeTab);
  const isConsistencyTab = activeTab === "consistency";

  // Fetch available agents for the filter dropdown
  const fetchAvailableAgents = useCallback(async () => {
    try {
      const response = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
      if (response && Array.isArray(response)) {
        setAvailableAgents(response);
      }
    } catch (error) {
      console.error("Failed to fetch agents:", error);
    }
  }, [fetchData]);

  useEffect(() => {
    if (hasLoadedAgentsOnce.current) return;
    hasLoadedAgentsOnce.current = true;
    fetchAvailableAgents();
  }, [fetchAvailableAgents]);

  // Show loader while checking permissions
  if (permissionsLoading) {
    return <Loader />;
  }

  // Check evaluation permission
  if (!evaluationAllowed) {
    return (
      <div className="pageContainer">
        <div style={{ padding: 24, color: "var(--danger)", fontWeight: 600 }}>
          You do not have permission to access Evaluation.
        </div>
      </div>
    );
  }

  // Handler for when filter is applied from SubHeader
  const handleAgentsFilterApply = (appliedTags, appliedTypes) => {
    // appliedTags contains the selected agent names (industryOptions)
    // appliedTypes contains the selected agent types
    setSelectedAgentNames(appliedTags || []);
    setSelectedAgentTypes(appliedTypes || []);
    // Trigger filter in EvaluationScore
    setFilterTrigger((prev) => prev + 1);
  };

  // Handler for clearing filters
  const handleClearFilters = () => {
    setSelectedAgentNames([]);
    setSelectedAgentTypes([]);
    setFilterTrigger((prev) => prev + 1);
  };

  // Navigation configuration matching the requested structure
  const navigationConfig = [
    {
      type: "section",
      key: "llmAsJudge",
      label: "LLM As Judge",
      children: [
        {
          key: "llmAsJudge",
          label: "LLM As Judge",
          component: AgentsEvaluator,
        },
      ],
    },
    {
      type: "section",
      key: "metrics",
      label: "Metrics",
      children: [
        { key: "evaluationRecords", label: "Evaluation Records" },
        { key: "toolsEfficiency", label: "Tool Efficiency" },
        { key: "agentsEfficiency", label: "Agent Efficiency" },
      ],
    },
    {
      type: "section",
      key: "evaluation",
      label: "Evaluation",
      children: [
        {
          key: "groundTruth",
          label: "Ground Truth",
          component: GroundTruth,
        },
        {
          key: "consistency",
          label: "Consistency",
          // Already handled separately via isConsistencyTab check
        },
      ],
    },
  ];

  // Map activeTab to activeMetricsSubTab for EvaluationScore
  const getActiveMetricsSubTab = () => {
    switch (activeTab) {
      case "evaluationRecords":
        return "evaluationRecords";
      case "toolsEfficiency":
        return "toolsEfficiency";
      case "agentsEfficiency":
        return "agentsEfficiency";
      default:
        return null;
    }
  };

  const handleNavClick = (key) => {
    // Reset filters when switching tabs within Metrics section
    if (metricsTabs.includes(key) && activeTab !== key) {
      setSelectedAgentNames([]);
      setSelectedAgentTypes([]);
      setFilterTrigger((prev) => prev + 1);
    }
    setActiveTab(key);
    setMenuOpen(false);
    setOpenDropdown(null);
  };

  // Check if a section has an active child tab
  const isSectionActive = (section) => {
    return section.children?.some((child) => child.key === activeTab);
  };

  // Handle dropdown hover - calculate position for fixed menu
  const handleDropdownEnter = (sectionKey, event) => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    setDropdownPosition({
      top: rect.bottom,
      left: rect.left,
    });
    setOpenDropdown(sectionKey);
  };

  const handleDropdownLeave = () => {
    closeTimeoutRef.current = setTimeout(() => {
      setOpenDropdown(null);
    }, 150);
  };

  const handleMenuEnter = () => {
    if (closeTimeoutRef.current) {
      clearTimeout(closeTimeoutRef.current);
      closeTimeoutRef.current = null;
    }
  };

  const handleMenuLeave = () => {
    setOpenDropdown(null);
  };

  // Find active label and parent section
  const findActiveItem = () => {
    for (const section of navigationConfig) {
      if (section.key === activeTab && section.component) {
        return { component: section.component, label: section.label, sectionLabel: null, sectionKey: section.key };
      }
      if (section.children) {
        const child = section.children.find((c) => c.key === activeTab);
        if (child) return { component: child.component, label: child.label, sectionLabel: section.label, sectionKey: section.key };
      }
    }
    return null;
  };

  const activeItem = findActiveItem();
  const ActiveComponent = activeItem?.component;
  const activeLabel = activeItem?.label || "";
  const sectionLabel = activeItem?.sectionLabel;

  // Build breadcrumb items for Evaluation screen
  const getBreadcrumbItems = () => {
    const items = [{ label: "Evaluation" }];

    // Add section label if exists
    if (sectionLabel) {
      items.push({ label: sectionLabel });
    }

    // Add current tab label
    items.push({ label: activeLabel });

    return items;
  };

  const handleSearch = (value) => {
    setSearchValue(value);
    // Search functionality can be implemented per tab if needed
  };

  const clearSearch = () => {
    setSearchValue("");
    handleClearFilters();
  };

  // Header navigation with dropdown menus (matching Admin style)
  const headerNav = (
    <nav className={styles.headerNav}>
      {navigationConfig.map((section) => (
        <div
          key={section.key}
          className={styles.navDropdown}
          onMouseEnter={(e) => handleDropdownEnter(section.key, e)}
          onMouseLeave={handleDropdownLeave}
        >
          <button
            className={`${styles.navDropdownTrigger} ${isSectionActive(section) ? styles.active : ""}`}
            aria-haspopup="true"
            aria-expanded={openDropdown === section.key}
          >
            {section.label}
            <SVGIcons icon="chevron-down" width={14} height={14} />
          </button>
          {openDropdown === section.key && (
            <div
              className={`${styles.navDropdownMenu} ${styles.open}`}
              style={{ top: dropdownPosition.top, left: dropdownPosition.left }}
              onMouseEnter={handleMenuEnter}
              onMouseLeave={handleMenuLeave}
            >
              {section.children?.map((child) => (
                <button
                  key={child.key}
                  className={`${styles.navDropdownItem} ${activeTab === child.key ? styles.active : ""}`}
                  onClick={() => handleNavClick(child.key)}
                >
                  {child.label}
                </button>
              ))}
            </div>
          )}
        </div>
      ))}
    </nav>
  );

  // Create agent type metadata mapping for badges
  const agentTypeMetadata = availableAgents.reduce((acc, agent) => {
    acc[agent.agentic_application_name] = agent.agentic_application_type;
    return acc;
  }, {});

  return (
    <div className="pageContainer">
      <SubHeader
        heading=""
        activeTab="metrics"
        searchValue={searchValue}
        onSearch={handleSearch}
        clearSearch={clearSearch}
        showRefreshButton={false}
        showPlusButton={isConsistencyTab}
        plusButtonLabel={"New Consistency"}
        onPlusClick={() => setConsistencyPlusTrigger((prev) => prev + 1)}
        showSearch={isConsistencyTab}
        leftContent={headerNav}
        // Show agent type dropdown for Metrics section (excluding pipeline) and Consistency
        showAgentTypeDropdown={isMetricsSection || isConsistencyTab}
        agentTypes={isMetricsSection ? metricsAgentTypes : agentTypesDropdown}
        selectedAgentType={selectedAgentTypes}
        handleTypeFilter={(e) => setSelectedAgentTypes(e.target.value)}
        // Show agents list filter for Metrics section tabs (not Consistency)
        showTagsDropdown={isMetricsSection}
        availableTags={isMetricsSection ? availableAgents.map((agent) => agent.agentic_application_name) : []}
        selectedTagsForDropdown={selectedAgentNames}
        onTagsChange={handleAgentsFilterApply}
        // Hide Created By dropdown for Metrics
        showCreatedByDropdown={false}
        // Hide breadcrumb - navigation is in header dropdowns
        breadcrumbItems={null}
        // Disable inline type filter for Metrics section - show Type as standalone section
        showInlineTypeFilter={false}
        // Pass agent type metadata for showing type badges
        agentTypeMetadata={agentTypeMetadata}
      />

      {/* Main content area */}
      <PageLayout>
        {isMetricsSection ? (
          <EvaluationScore
            activeMetricsSubTab={getActiveMetricsSubTab()}
            selectedAgentNames={selectedAgentNames}
            selectedAgentTypes={selectedAgentTypes}
            filterTrigger={filterTrigger}
          />
        ) : isConsistencyTab ? (
          <ConsistencyTab plusClickTrigger={consistencyPlusTrigger} searchValue={searchValue} onClearSearch={clearSearch} selectedAgentTypes={selectedAgentTypes} />
        ) : (
          ActiveComponent && <ActiveComponent />
        )}
      </PageLayout>
    </div>
  );
};

export default EvaluationPageNew;