import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { BASE_URL, APIs } from '../constant';
import styles from '../css_modules/AgentsMultiSelect.module.css';

const AgentsMultiSelect = ({ onSelectionChange }) => {
  const [availableAgents, setAvailableAgents] = useState([]);
  const [selectedAgents, setSelectedAgents] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const dropdownRef = useRef(null);

  // Fetch agents data when component mounts
  useEffect(() => {
    fetchAgents();

    // Close dropdown when clicking outside
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsDropdownOpen(false);
      }
    };
    
    document.addEventListener("mousedown", handleClickOutside);
    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
    };
  }, []);

  // Update parent component when selection changes
  useEffect(() => {
    if (onSelectionChange && typeof onSelectionChange === 'function') {
      onSelectionChange(selectedAgents.map(agent => agent.agentic_application_name));
    }
  }, [selectedAgents, onSelectionChange]);

  const fetchAgents = async () => {
    setLoading(true);
    try {
      const response = await axios.get(`${BASE_URL}${APIs.GET_AGENTS_BY_DETAILS}`);
      if (response.data && Array.isArray(response.data)) {
        setAvailableAgents(response.data);
      } else {
        console.error("Invalid agents response");
      }
    } catch (error) {
      console.error("Failed to fetch agents:", error);
    } finally {
      setLoading(false);
    }
  };
  
  const toggleDropdown = () => {
    setIsDropdownOpen(!isDropdownOpen);
  };
  
  const handleAgentSelection = (agent) => {
    setSelectedAgents(prevSelected => {
      const isAlreadySelected = prevSelected.some(
        selected => selected.agentic_application_id === agent.agentic_application_id
      );
      
      if (isAlreadySelected) {
        return prevSelected.filter(
          selected => selected.agentic_application_id !== agent.agentic_application_id
        );
      } else {
        return [...prevSelected, agent];
      }
    });
  };
  
  const handleSearchChange = (e) => {
    setSearchTerm(e.target.value);
  };

  const removeSelectedAgent = (agentId) => {
    setSelectedAgents(prevSelected => 
      prevSelected.filter(agent => agent.agentic_application_id !== agentId)
    );
  };
  
  const filteredAgents = availableAgents.filter(agent => 
    agent.agentic_application_name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className={styles.multiSelectContainer} ref={dropdownRef}>
      <div className={styles.multiSelectDropdown}>
        <div 
          className={styles.multiSelectHeader} 
          onClick={toggleDropdown}
        >
          <div className={styles.selectedAgentsDisplay}>
            {selectedAgents.length === 0 ? (
              <span>Select Agents</span>
            ) : (
              selectedAgents.map((agent) => (
                <div key={agent.agentic_application_id} className={styles.selectedAgentTag}>
                  {agent.agentic_application_name}
                  <span 
                    className={styles.removeTag} 
                    onClick={(e) => {
                      e.stopPropagation();
                      removeSelectedAgent(agent.agentic_application_id);
                    }}
                  >
                    ×
                  </span>
                </div>
              ))
            )}
          </div>
          <span>{isDropdownOpen ? '▲' : '▼'}</span>
        </div>
        {isDropdownOpen && (
          <div className={styles.dropdownContent}>
            <div className={styles.searchBox}>
              <input
                type="text"
                className={styles.searchInput}
                placeholder="Search agents..."
                value={searchTerm}
                onChange={handleSearchChange}
                onClick={(e) => e.stopPropagation()}
              />
            </div>
            {loading ? (
              <div className={styles.loading}>Loading agents...</div>
            ) : filteredAgents.length > 0 ? (
              <ul className={styles.agentsList}>
                {filteredAgents.map((agent) => (
                  <li
                    key={agent.agentic_application_id}
                    className={styles.agentItem}
                    onClick={() => handleAgentSelection(agent)}
                  >
                    <input
                      type="checkbox"
                      className={styles.checkbox}
                      checked={selectedAgents.some(
                        selected => selected.agentic_application_id === agent.agentic_application_id
                      )}
                      readOnly
                    />
                    {agent.agentic_application_name}
                  </li>
                ))}
              </ul>
            ) : (
              <div className={styles.noAgents}>No agents found</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default AgentsMultiSelect;
