import React, { useState, useEffect, useCallback } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import {
  faTimes,
  faHistory,
  faSearch,
  faCalendarAlt,
  faComment,
  faSpinner,
  faTrash
} from "@fortawesome/free-solid-svg-icons";
import styles from "./ChatHistorySlider.module.css";
import { resetChat } from "../../services/chatService";

const ChatHistorySlider = ({ 
  chats, 
  onClose, 
  onSelectChat, 
  fetchChatHistory, 
  setOldSessionId,
  agentSelectValue,
  agentType,
  customTemplatId,
  onChatDeleted
}) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedTimeRange, setSelectedTimeRange] = useState("all");
  const [filteredChats, setFilteredChats] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [deletingChatId, setDeletingChatId] = useState(null);

  const filterChats = useCallback(() => {
    // Ensure chats is an array
    if (!Array.isArray(chats)) {
      setFilteredChats([]);
      return;
    }
    
    let filtered = [...chats];
    
    // Filter by search term
    if (searchTerm) {
      filtered = filtered?.filter(chat =>
        chat?.user_input?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        chat?.agent_response?.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }

    // Filter by time range
    const now = new Date();
    if (selectedTimeRange !== "all") {
      filtered = filtered?.filter(chat => {
        if (!chat?.timestamp_start) return false;
        const chatDate = new Date(chat.timestamp_start);
        const timeDiff = now - chatDate;
        
        switch (selectedTimeRange) {
          case "today":
            return timeDiff < 24 * 60 * 60 * 1000;
          case "week":
            return timeDiff < 7 * 24 * 60 * 60 * 1000;
          case "month":
            return timeDiff < 30 * 24 * 60 * 60 * 1000;
          default:
            return true;
        }
      });
    }

    filtered?.sort((a, b) => {
      const aTime = a?.timestamp_start ? new Date(a.timestamp_start) : new Date(0);
      const bTime = b?.timestamp_start ? new Date(b.timestamp_start) : new Date(0);
      return bTime - aTime;
    });

    setFilteredChats(filtered || []);
  }, [chats, searchTerm, selectedTimeRange]);

  useEffect(() => {
    filterChats();
  }, [filterChats]);

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return 'Unknown time';
    
    try {
      
      let date;
      
      if (typeof timestamp === 'string') {
        // Handle different string formats
        if (timestamp.includes('T') && !timestamp.endsWith('Z') && !timestamp.includes('+') && !timestamp.includes('-', 10)) {
          // Format like "2025-01-24T14:30:00" without timezone - assume UTC
          date = new Date(timestamp + 'Z');
        } else if (timestamp.match(/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/)) {
          // Format like "2025-01-24 14:30:00" - assume UTC
          date = new Date(timestamp.replace(' ', 'T') + 'Z');
        } else {
          // Already has timezone info or other format
          date = new Date(timestamp);
        }
      } else {
        // Numeric timestamp
        date = new Date(timestamp);
      }
      
      // Check if the date is valid
      if (isNaN(date.getTime())) {
        console.warn('Invalid timestamp after conversion:', timestamp);
        return 'Invalid date';
      }
      
      const now = new Date();
      const timeDiff = now - date;
      
      if (timeDiff < 60 * 60 * 1000) {
        // Less than 1 hour
        const minutes = Math.floor(timeDiff / (60 * 1000));
        return `${minutes}m ago`;
      } else if (timeDiff < 24 * 60 * 60 * 1000) {
        // Less than 1 day
        const hours = Math.floor(timeDiff / (60 * 60 * 1000));
        return `${hours}h ago`;
      } else if (timeDiff < 7 * 24 * 60 * 60 * 1000) {
        // Less than 1 week
        const days = Math.floor(timeDiff / (24 * 60 * 60 * 1000));
        return `${days}d ago`;
      } else {
        // More than 1 week - show actual date in local time
        return date.toLocaleDateString('en-US', { 
          month: 'short', 
          day: 'numeric',
          year: date.getFullYear() !== now.getFullYear() ? 'numeric' : undefined
        });
      }
    } catch (error) {
      console.error('Error formatting timestamp:', error, 'Original timestamp:', timestamp);
      return 'Invalid time';
    }
  };

  const handleChatSelect = async (chat) => {
    if (isLoading || !chat?.session_id) return; // Prevent multiple clicks or invalid chat
    
    try {
      setIsLoading(true);
      if (setOldSessionId) {
        setOldSessionId(chat.session_id);
      }
            if (fetchChatHistory) {
        await fetchChatHistory(chat.session_id);
      }
      
      if (onSelectChat) {
        onSelectChat(chat.session_id);
      }
      onClose();
    } catch (error) {
      onClose();
    } finally {
      setIsLoading(false);
    }
  };

  const handleDeleteChat = async (chatSessionId, e) => {
    e.stopPropagation(); 
    
    if (window.confirm("Are you sure you want to delete this chat?")) {
      try {
        setDeletingChatId(chatSessionId);
        
        const data = {
          session_id: chatSessionId,
          agent_id: agentType !== "custom_template" ? agentSelectValue : customTemplatId,
        };
        
        const response = await resetChat(data);        
        if (response?.status === "success") {
          setFilteredChats(prev => prev.filter(chat => chat.session_id !== chatSessionId));
                    if (onChatDeleted) {
            onChatDeleted(chatSessionId);
          }
                  } else {
         
        }
      } catch (error) {
        console.error("Error deleting chat:", error);
      } finally {
        setDeletingChatId(null);
      }
    }
  };  

  return (
    <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className={styles.slider}>
        {/* Header */}
        <div className={styles.header}>
          <div className={styles.headerContent}>
            <FontAwesomeIcon icon={faHistory} className={styles.headerIcon} />
            <h3 className={styles.title}>Chat History</h3>
          </div>
          <button className={styles.closeButton} onClick={onClose}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {/* Filters */}
        <div className={styles.filters}>
          {/* Search */}
          <div className={styles.searchContainer}>
            <FontAwesomeIcon icon={faSearch} className={styles.searchIcon} />
            <input
              type="text"
              placeholder="Search chats..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className={styles.searchInput}
            />
          </div>

          {/* Time Range Filter */}
          <div className={styles.timeFilter}>
            <FontAwesomeIcon icon={faCalendarAlt} className={styles.timeIcon} />
            <select
              value={selectedTimeRange}
              onChange={(e) => setSelectedTimeRange(e.target.value)}
              className={styles.timeSelect}
            >
              <option value="all">All Time</option>
              <option value="today">Today</option>
              <option value="week">This Week</option>
              <option value="month">This Month</option>
            </select>
          </div>
        </div>
        {/* Chat List */}
        <div className={styles.chatList}>
          {filteredChats.length > 0 ? (
            filteredChats.map((chat) => (
              <div
                key={chat.session_id}
                className={`${styles.chatItem} ${isLoading ? styles.loading : ''}`}
                onClick={() => handleChatSelect(chat)}
                style={{ opacity: isLoading ? 0.6 : 1, pointerEvents: isLoading ? 'none' : 'auto' }}
              >
                <div className={styles.chatHeader}>
                  <h4 className={styles.chatTitle}>{chat?.user_input || 'No message'}</h4>
                  <div className={styles.chatMeta}>
                    <span className={styles.timestamp}>
                      {chat?.timestamp_start ? formatTimestamp(chat.timestamp_start) : 'Unknown time'}
                    </span>
                    <button
                      className={styles.deleteButton}
                      onClick={(e) => handleDeleteChat(chat.session_id, e)}
                      title="Delete Chat"
                      disabled={deletingChatId === chat.session_id}
                    >
                      {deletingChatId === chat.session_id ? (
                        <FontAwesomeIcon icon={faSpinner} spin />
                      ) : (
                        <FontAwesomeIcon icon={faTrash} />
                      )}
                    </button>
                  </div>
                </div>

                <p className={styles.lastMessage}>{chat?.agent_response || 'No response'}</p>

                <div className={styles.chatFooter}>
                  <div className={styles.chatInfo}>
                    {/* <span 
                      className={styles.agentBadge}
                      style={{ backgroundColor: getAgentTypeColor(chat.agentType) }}
                    >
                      {getAgentTypeLabel(chat.agentType)}
                    </span> */}
                    {/* <span className={styles.modelBadge}>{chat.model}</span> */}
                    <span className={styles.messageCount}>
                      <FontAwesomeIcon icon={faComment} />
                      {chat?.messageCount || 0}
                    </span>
                  </div>
                </div>
              </div>
            ))
          ) : (
            <div className={styles.emptyState}>
              <FontAwesomeIcon icon={faHistory} className={styles.emptyIcon} />
              <h4 className={styles.emptyTitle}>No chats found</h4>
              <p className={styles.emptyDescription}>
                {searchTerm || selectedTimeRange !== "all"
                  ? "Try adjusting your search or filter criteria"
                  : "Start a conversation to see your chat history here"
                }
              </p>
            </div>
          )}
        </div>

        {/* Footer */}
        {filteredChats.length > 0 && (
          <div className={styles.footer}>
            <span className={styles.chatCount}>
              {filteredChats.length} chat{filteredChats.length !== 1 ? 's' : ''} found
            </span>
            {isLoading && (
              <span className={styles.loadingText}>
                <FontAwesomeIcon icon={faSpinner} spin className={styles.loadingIcon} />
                Loading chat...
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatHistorySlider;
