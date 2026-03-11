import { useState, useEffect, useRef } from "react";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./WelcomeModal.module.css";
import { agentTypesDropdown, PIPELINE_AGENT } from "../../constant";

// Include pipeline in WelcomeModal filters so users can filter pipeline agents
const welcomeAgentTypes = [
  ...agentTypesDropdown,
  { label: "Pipeline", value: PIPELINE_AGENT },
];

/**
 * WelcomeModal - Initial welcome popup shown when user first visits the chat page
 * Displays welcome message with framework and agent selection
 * Auto-closes when agent is selected (no button needed)
 */
const WelcomeModal = ({
  isOpen,
  onClose,
  frameworkOptions,
  selectedFramework,
  onFrameworkChange,
  agents = [],
  selectedAgent,
  onAgentChange,
  loadingAgents,
  disabled,
  // Additional props for agent dropdown
  getAgentTypeFilterOptions,
  agentType,
  onAgentTypeChange,
  focusChatInput, // Callback to focus chat input after modal closes
}) => {
  const [localFramework, setLocalFramework] = useState(selectedFramework);
  const [localAgent, setLocalAgent] = useState(selectedAgent);
  const [localAgentType, setLocalAgentType] = useState(agentType || "all");
  const [agentDropdownOpen, setAgentDropdownOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [showFilters, setShowFilters] = useState(false);
  const agentDropdownRef = useRef(null);
  const searchInputRef = useRef(null);

  // Build abbreviation map from welcomeAgentTypes (includes pipeline)
  const typeAbbreviations = Object.fromEntries(
    welcomeAgentTypes.map((t) => {
      // Generate 2-letter abbreviation from label words
      const words = t.label.trim().split(/\s+/);
      const abbr = words.length > 1
        ? words.map((w) => w[0].toUpperCase()).join("").slice(0, 2)
        : t.value.toUpperCase().slice(0, 2);
      return [t.value, abbr];
    }),
  );

  // Get agent type filter options from constant - always show ALL known types
  const getTypeFilterOptions = () => {
    const options = [{ label: "All", value: "all", short: "ALL" }];

    welcomeAgentTypes.forEach((t) => {
      const abbr = typeAbbreviations[t.value] || t.value.toUpperCase().slice(0, 2);
      options.push({
        label: t.label,
        value: t.value,
        short: abbr,
      });
    });

    // Include any additional types from agents that aren't in the constant
    const knownValues = new Set(welcomeAgentTypes.map((t) => t.value));
    agents.forEach((agent) => {
      const type = agent.agentic_application_type;
      if (type && !knownValues.has(type)) {
        const abbr = type.toUpperCase().slice(0, 2);
        options.push({
          label: type.replace(/_/g, " ").replace(/\b\w/g, (l) => l.toUpperCase()),
          value: type,
          short: abbr,
        });
        knownValues.add(type);
      }
    });
    return options;
  };

  // Sync with parent state
  useEffect(() => {
    setLocalFramework(selectedFramework);
  }, [selectedFramework]);

  useEffect(() => {
    setLocalAgent(selectedAgent);
  }, [selectedAgent]);

  useEffect(() => {
    setLocalAgentType(agentType || "all");
  }, [agentType]);

  // Auto-open agent dropdown when modal opens and agents are loaded
  useEffect(() => {
    if (isOpen && agents.length > 0 && !loadingAgents && !localAgent) {
      // Small delay to ensure DOM is ready
      const timer = setTimeout(() => {
        setAgentDropdownOpen(true);
      }, 300);
      return () => clearTimeout(timer);
    }
  }, [isOpen, agents.length, loadingAgents, localAgent]);

  // Handle framework change
  const handleFrameworkSelect = (label) => {
    const selected = frameworkOptions.find((f) => f.label === label);
    if (selected) {
      setLocalFramework(selected.value);
      onFrameworkChange(selected.value);
      // Reset agent selection when framework changes
      setLocalAgent("");
      setLocalAgentType("all");
      // Open agent dropdown after framework change
      setTimeout(() => setAgentDropdownOpen(true), 100);
    }
  };

  // Handle agent selection - auto close modal and focus chat input
  const handleAgentSelect = (agentName) => {
    setLocalAgent(agentName);
    onAgentChange(agentName);
    // Auto-close modal when agent is selected
    if (agentName) {
      setAgentDropdownOpen(false);
      // Small delay before closing to show selection
      setTimeout(() => {
        onClose();
        // Focus chat input after modal closes
        if (focusChatInput) {
          setTimeout(() => focusChatInput(), 100);
        }
      }, 200);
    }
  };

  // Filter agents based on search and type
  // In WelcomeModal, show ALL agents including hybrid_agent regardless of framework
  // Framework will be auto-switched when hybrid_agent is selected
  // Exclude pipeline agents from "All" view - only show when explicitly filtered
  const filteredAgents = agents.filter((agent) => {
    const matchesSearch = !searchQuery ||
      agent.agentic_application_name.toLowerCase().includes(searchQuery.toLowerCase());
    const matchesType = localAgentType === "all" ||
      agent.agentic_application_type === localAgentType;
    const isPipeline = agent.agentic_application_type === PIPELINE_AGENT;
    const pipelineAllowed = localAgentType === PIPELINE_AGENT || !isPipeline;
    return matchesSearch && matchesType && pipelineAllowed;
  });

  // Build option metadata for agent dropdown (type badges)
  const getOptionMetadata = () => {
    return Object.fromEntries(
      agents.map((agent) => [
        agent.agentic_application_name,
        typeAbbreviations[agent.agentic_application_type] ||
        (agent.agentic_application_type ? agent.agentic_application_type.toUpperCase().slice(0, 2) : ""),
      ])
    );
  };

  if (!isOpen) return null;

  const frameworkLabel = frameworkOptions.find((f) => f.value === localFramework)?.label || "";

  return (
    <div className={styles.modalOverlay}>
      <div className={styles.landingModal}>
        {/* Left Panel - IAF Branding */}
        <div className={styles.brandingPanel}>
          <div className={styles.brandingContent}>
            {/* Logo & Title */}
            <div className={styles.logoSection}>
              <div className={styles.logoIcon}>
                <SVGIcons icon="brain" width={28} height={28} color="#ffffff" stroke="#ffffff" />
              </div>
              <div>
                <h1 className={styles.brandTitle}>Infosys Agentic Foundry</h1>
                <p className={styles.brandTagline}>Part of Infosys Topaz</p>
              </div>
            </div>

            {/* IAF Description */}
            <div className={styles.aboutSection}>
              <p className={styles.aboutText}>
                A powerful enterprise platform for building, deploying, and managing AI agents at scale.
                Streamline your agentic workflows with our comprehensive toolkit.
              </p>
            </div>

            {/* Key Capabilities */}
            <div className={styles.capabilitiesSection}>
              <div className={styles.capabilityItem}>
                <div className={styles.capabilityIcon}>
                  <SVGIcons icon="brain" width={20} height={20} color="#3b82f6" stroke="#3b82f6" />
                </div>
                <div className={styles.capabilityText}>
                  <h4>Multi Agent Orchestration</h4>
                  <p>Seamlessly coordinate multiple AI agents to solve complex tasks collaboratively</p>
                </div>
              </div>
              <div className={styles.capabilityItem}>
                <div className={styles.capabilityIcon}>
                  <SVGIcons icon="bolt" width={20} height={20} color="#3b82f6" stroke="#3b82f6" />
                </div>
                <div className={styles.capabilityText}>
                  <h4>Automated Learning</h4>
                  <p>Continuously improve agent performance through adaptive learning mechanisms</p>
                </div>
              </div>
              <div className={styles.capabilityItem}>
                <div className={styles.capabilityIcon}>
                  <SVGIcons icon="checkmark" width={20} height={20} color="#3b82f6" stroke="#3b82f6" />
                </div>
                <div className={styles.capabilityText}>
                  <h4>Reliable Execution</h4>
                  <p>Enterprise-grade reliability with built-in guardrails and error handling</p>
                </div>
              </div>
              <div className={styles.capabilityItem}>
                <div className={styles.capabilityIcon}>
                  <SVGIcons icon="folder" width={20} height={20} color="#3b82f6" stroke="#3b82f6" />
                </div>
                <div className={styles.capabilityText}>
                  <h4>Open Architecture</h4>
                  <p>Flexible integration with any tools, APIs, and knowledge sources</p>
                </div>
              </div>
            </div>
          </div>

          {/* Footer Branding */}
          <div className={styles.brandingFooter}>
            <span className={styles.poweredBy}>Powered by Infosys</span>
          </div>
        </div>

        {/* Right Panel - Agent Selection */}
        <div className={styles.selectionPanel}>
          <div className={styles.selectionContent}>
            {/* Feature Highlights at Top */}
            <div className={styles.featureHighlights}>
              <div className={styles.highlightItem}>
                <SVGIcons icon="bolt" width={14} height={14} color="#3b82f6" stroke="#3b82f6" />
                <span>Instant Responses</span>
              </div>
              <div className={styles.highlightItem}>
                <SVGIcons icon="chat" width={14} height={14} color="#3b82f6" stroke="#3b82f6" />
                <span>Natural Conversations</span>
              </div>
              <div className={styles.highlightItem}>
                <SVGIcons icon="database" width={14} height={14} color="#3b82f6" stroke="#3b82f6" />
                <span>Context-Aware</span>
              </div>
            </div>

            {/* Welcome Message */}
            <div className={styles.welcomeSection}>
              <h2 className={styles.welcomeTitle}>Get Started</h2>
              <p className={styles.welcomeSubtitle}>
                Select an AI agent to begin your conversation
              </p>
            </div>

            {/* Agent Selection Card */}
            <div className={styles.agentSelectionCard}>
              {/* Search and Filter Header */}
              <div className={styles.searchFilterRow}>
                <div className={styles.searchInputWrapper}>
                  <SVGIcons icon="search" width={16} height={16} color="rgba(255,255,255,0.4)" stroke="rgba(255,255,255,0.4)" />
                  <input
                    ref={searchInputRef}
                    type="text"
                    className={styles.searchInput}
                    placeholder="Search agents..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    disabled={disabled || loadingAgents}
                  />
                  {searchQuery && (
                    <button
                      className={styles.clearSearch}
                      onClick={() => setSearchQuery("")}
                    >
                      <SVGIcons icon="close" width={12} height={12} />
                    </button>
                  )}
                </div>
                <button
                  className={`${styles.filterToggleBtn} ${showFilters || localAgentType !== "all" ? styles.active : ""}`}
                  onClick={() => setShowFilters(!showFilters)}
                  title="Filter by type"
                >
                  <SVGIcons icon="filter-funnel" width={16} height={16} />
                  {localAgentType !== "all" && (
                    <span className={styles.filterBadge}>
                      {typeAbbreviations[localAgentType] || localAgentType.toUpperCase().slice(0, 2)}
                    </span>
                  )}
                </button>
              </div>

              {/* Type Filters - Collapsible */}
              {showFilters && (
                <div className={styles.typeFilterWrapper}>
                  {getTypeFilterOptions().map((option) => (
                    <button
                      key={option.value}
                      className={`${styles.typeFilterBtn} ${localAgentType === option.value ? styles.active : ""}`}
                      onClick={() => {
                        setLocalAgentType(option.value);
                        if (onAgentTypeChange) {
                          onAgentTypeChange(option.value === "all" ? "" : option.value);
                        }
                      }}
                    >
                      {option.short}
                    </button>
                  ))}
                </div>
              )}

              {/* Agent List */}
              <div className={styles.agentList}>
                {loadingAgents ? (
                  <div className={styles.loadingState}>
                    <SVGIcons icon="loader" width={24} height={24} className={styles.spinner} />
                    <span>Loading agent...</span>
                  </div>
                ) : filteredAgents.length === 0 ? (
                  <div className={styles.emptyState}>
                    <SVGIcons icon="search" width={32} height={32} color="rgba(255,255,255,0.3)" stroke="rgba(255,255,255,0.3)" />
                    <span>No agents found</span>
                    {searchQuery && <button onClick={() => setSearchQuery("")}>Clear search</button>}
                  </div>
                ) : (
                  filteredAgents.map((agent) => (
                    <button
                      key={agent.agentic_application_name}
                      className={`${styles.agentListItem} ${localAgent === agent.agentic_application_name ? styles.selected : ""}`}
                      onClick={() => handleAgentSelect(agent.agentic_application_name)}
                      disabled={disabled}
                    >
                      <div className={styles.agentItemIcon}>
                        <SVGIcons icon="brain" width={18} height={18} color="#3b82f6" stroke="#3b82f6" />
                      </div>
                      <span className={styles.agentItemName}>{agent.agentic_application_name}</span>
                      {agent.agentic_application_type && (
                        <span className={styles.agentItemType}>
                          {typeAbbreviations[agent.agentic_application_type] || agent.agentic_application_type.toUpperCase().slice(0, 2)}
                        </span>
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
          </div>

          {/* Skip Option - Bottom Right */}
          <button className={styles.skipButton} onClick={onClose}>
            Skip for now <SVGIcons icon="arrowRight" width={14} height={14} />
          </button>
        </div>
      </div>
    </div>
  );
};

export default WelcomeModal;
