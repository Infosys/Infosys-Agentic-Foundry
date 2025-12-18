// export default AgentList;
import styles from './AgentsList.module.css';
import headerStyles from './PageWithHeader.module.css';

// AgentList component
const AgentList = ({ agents, onSelect }) => {
  const agentList = Array.isArray(agents) ? agents : [];
  return (
    <div className={styles.container}>
      <div className={styles.headerActions}>
  <h6 className={headerStyles.h6Heading}>Agents</h6>
      </div>
      {agentList.length === 0 ? (
        <div className={styles.noAgents}>
          No agents yet—create one to get started!
        </div>
      ) : (
        <div className={styles.grid}>
          {agentList.map((agent) => (
            <button
              key={agent.agent_id}
              onClick={() => onSelect(agent.agent_id,agent.agent_name)}
              className={styles.agentButton}
            >
              {agent.agent_name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
};

export default AgentList;
