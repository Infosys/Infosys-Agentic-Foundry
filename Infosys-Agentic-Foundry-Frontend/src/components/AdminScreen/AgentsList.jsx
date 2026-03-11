import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1.jsx";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine.jsx";
import EmptyState from "../commonComponents/EmptyState.jsx";
import Loader from "../commonComponents/Loader.jsx";

/**
 * AgentList component - displays agents available for learning/approval
 * @param {Array} agents - List of agents to display
 * @param {Function} onSelect - Callback when an agent card is clicked
 * @param {string} searchValue - Current search term (for EmptyState display)
 * @param {Function} onClearSearch - Callback to clear search (for EmptyState)
 * @param {boolean} loading - Loading state from parent
 */
const AgentList = ({ agents, onSelect, searchValue = "", onClearSearch, loading = false }) => {
  const agentList = Array.isArray(agents) ? agents : [];

  // Build filters array for EmptyState display
  const activeFilters = searchValue.trim() ? [`Search: ${searchValue}`] : [];

  return (
    <>
      <SummaryLine visibleCount={agentList.length} />
      <div className="listWrapper">
        {loading ? (
          <Loader />
        ) : agentList.length > 0 ? (
          <DisplayCard1
            data={agentList}
            onCardClick={(name, item) => onSelect(item.agent_id, item.agent_name)}
            cardNameKey="agent_name"
            cardDescriptionKey="agent_description"
            cardOwnerKey="created_by"
            emptyMessage="No agents yet—create one to get started!"
            contextType="agent"
            idKey="agent_id"
            showCreateCard={false}
            showButton={false}
            isUnusedSection={true}
            footerButtonsConfig={[]}
            className="learningAgentsList"
          />
        ) : (
          <EmptyState message="No agents found for learning" filters={activeFilters} onClearFilters={onClearSearch} showCreateButton={false} />
        )}
      </div>
    </>
  );
};

export default AgentList;
