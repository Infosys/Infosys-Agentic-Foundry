import React, { useState, useEffect, useCallback, useRef } from "react";
import { formatMessageTimestamp } from "../../utils/timeFormatter";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { faTimes, faSearch, faFilter, faSpinner, faTrash, faCheck } from "@fortawesome/free-solid-svg-icons";
import styles from "./ChatHistorySlider.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import { useChatServices } from "../../services/chatService";

const ChatHistorySlider = ({ chats, onClose, onSelectChat, fetchChatHistory, setOldSessionId, agentSelectValue, agentType, onChatDeleted, framework_type }) => {
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedTimeRange, setSelectedTimeRange] = useState("all");
  const [isFilterOpen, setIsFilterOpen] = useState(false);
  const filterRef = useRef(null);
  const [filteredChats, setFilteredChats] = useState([]);
  const [isLoading, setIsLoading] = useState(false);
  const [deletingChatId, setDeletingChatId] = useState(null);
  const [showDeleteConfirmation, setShowDeleteConfirmation] = useState(false);
  const [pendingDeleteSessionId, setPendingDeleteSessionId] = useState(null);
  const { resetChat } = useChatServices();

  const filterChats = useCallback(() => {
    if (!Array.isArray(chats)) {
      setFilteredChats([]);
      return;
    }

    let filtered = [...chats];
    if (searchTerm) {
      filtered = filtered?.filter(
        (chat) => chat?.user_input?.toLowerCase().includes(searchTerm.toLowerCase()) || chat?.agent_response?.toLowerCase().includes(searchTerm.toLowerCase()),
      );
    }
    const now = new Date();
    if (selectedTimeRange !== "all") {
      filtered = filtered?.filter((chat) => {
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

  // Close filter dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (filterRef.current && !filterRef.current.contains(event.target)) {
        setIsFilterOpen(false);
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const formatTimestamp = (timestamp) => {
    if (!timestamp) return "Unknown time";
    try {
      // Parse timestamp directly - backend sends local time, not UTC
      // Do NOT add 'Z' suffix as the timestamp is already in local timezone
      const date = new Date(timestamp.trim());
      if (isNaN(date.getTime())) {
        return "Invalid date";
      }
      
      // Format time in local timezone with 12-hour format
      const timeStr = date.toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit",
        hour12: true,
      });
      
      // Calculate relative date for display (in local timezone)
      const now = new Date();
      // Reset to start of day in local timezone for accurate day comparison
      const todayStart = new Date(now.getFullYear(), now.getMonth(), now.getDate());
      const msgDateStart = new Date(date.getFullYear(), date.getMonth(), date.getDate());
      
      // Calculate difference in days (positive = past, negative = future)
      const diffMs = todayStart.getTime() - msgDateStart.getTime();
      const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
      
      // Build display text with date prefix
      if (diffDays === 0) {
        return timeStr; // Today - just show time
      } else if (diffDays === 1) {
        return `Yesterday ${timeStr}`;
      } else if (diffDays > 0 && diffDays < 7) {
        const dayName = date.toLocaleDateString([], { weekday: "short" });
        return `${dayName} ${timeStr}`;
      } else {
        const dateStr = date.toLocaleDateString([], { month: "short", day: "numeric" });
        return `${dateStr} ${timeStr}`;
      }
    } catch (error) {
      console.error("Error formatting timestamp:", error, "Original timestamp:", timestamp);
      return "Invalid time";
    }
  };

  const handleChatSelect = async (chat) => {
    if (isLoading || !chat?.session_id) return;

    try {
      setIsLoading(true);
      // The onSelectChat prop (which is handleChatSelected in AskAssistant)
      // already handles setting the session ID and fetching the history.
      // We just need to call it!

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

  const handleDeleteChat = (chatSessionId, e) => {
    e.stopPropagation();
    setPendingDeleteSessionId(chatSessionId);
    setShowDeleteConfirmation(true);
  };

  const confirmDeleteChat = async () => {
    if (!pendingDeleteSessionId) return;
    try {
      setDeletingChatId(pendingDeleteSessionId);
      setShowDeleteConfirmation(false);
      const data = {
        session_id: pendingDeleteSessionId,
        agent_id: agentSelectValue,
        framework_type: framework_type,
      };
      const response = await resetChat(data);
      if (response?.status === "success") {
        setFilteredChats((prev) => prev.filter((chat) => chat.session_id !== pendingDeleteSessionId));
        if (onChatDeleted) {
          onChatDeleted(pendingDeleteSessionId);
          onChatDeleted(pendingDeleteSessionId);
        }
      }
    } catch (error) {
      console.error("Error deleting chat:", error);
    } finally {
      setDeletingChatId(null);
      setPendingDeleteSessionId(null);
    }
  };

  return (
    <>
      <div className={styles.overlay} onClick={(e) => e.target === e.currentTarget && onClose()}>
        <div className={styles.slider}>
          {/* Header */}
          <div className={styles.header}>
            <div className={styles.headerContent}>
              <SVGIcons icon="history" width={24} height={24} color="var(--app-primary-color)" />
              <h3 className={styles.title}>Chat History</h3>
            </div>
            <button className={styles.closeButton} onClick={onClose} aria-label="Close">
              <FontAwesomeIcon icon={faTimes} />
            </button>
          </div>

          {/* Filters */}
          <div className={styles.filters}>
            {/* Search Bar */}
            <div className={styles.searchContainer}>
              <input type="text" placeholder="Search Chat History..." value={searchTerm} onChange={(e) => setSearchTerm(e.target.value)} className={styles.searchInput} />
            </div>

            {/* Time Range Filter Dropdown */}
            <div className={styles.timeFilterWrapper} ref={filterRef}>
              <button className={styles.timeFilterButton} onClick={() => setIsFilterOpen(!isFilterOpen)}>
                <SVGIcons icon="filter-funnel" width={16} height={16} className={styles.filterIcon} />
                <span>{selectedTimeRange === "all" ? "All Time" : selectedTimeRange === "today" ? "Today" : selectedTimeRange === "week" ? "This Week" : "This Month"}</span>
              </button>

              {isFilterOpen && (
                <div className={styles.filterDropdown}>
                  {[
                    { value: "all", label: "All Time" },
                    { value: "today", label: "Today" },
                    { value: "week", label: "This Week" },
                    { value: "month", label: "This Month" },
                  ].map((option) => (
                    <button
                      key={option.value}
                      className={`${styles.filterOption} ${selectedTimeRange === option.value ? styles.selected : ""}`}
                      onClick={() => {
                        setSelectedTimeRange(option.value);
                        setIsFilterOpen(false);
                      }}>
                      <span>{option.label}</span>
                      {selectedTimeRange === option.value && <FontAwesomeIcon icon={faCheck} className={styles.checkIcon} />}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
          {/* Chat List */}
          <div className={styles.chatList}>
            {filteredChats.length > 0 ? (
              filteredChats.map((chat) => (
                <div
                  key={chat.session_id}
                  className={`${styles.chatItem} ${isLoading ? styles.loading : ""}`}
                  onClick={() => handleChatSelect(chat)}
                  style={{
                    opacity: isLoading ? 0.6 : 1,
                    pointerEvents: isLoading ? "none" : "auto",
                  }}>
                  <button className={styles.deleteButton} onClick={(e) => handleDeleteChat(chat.session_id, e)} title="Delete Chat" disabled={deletingChatId === chat.session_id}>
                    {deletingChatId === chat.session_id ? <FontAwesomeIcon icon={faSpinner} spin /> : <SVGIcons icon="trash-outline" width={16} height={16} />}
                  </button>
                  <div className={styles.chatHeader}>
                    <h4 className={styles.chatTitle}>{chat?.user_input || "No message"}</h4>
                  </div>

                  <div className={styles.chatFooter}>
                    <span className={styles.timestamp}>{chat?.timestamp_start ? formatTimestamp(chat.timestamp_start) : "Unknown time"}</span>
                    <div className={styles.messageCount}>
                      <SVGIcons icon="chat-bubble" width={12} height={12} />
                      {chat?.messageCount || 0}
                    </div>
                  </div>
                </div>
              ))
            ) : (
              <div className={styles.emptyState}>
                <SVGIcons icon="history" width={48} height={48} />
                <h4 className={styles.emptyTitle}>No chat history found</h4>
              </div>
            )}
          </div>

          {/* Footer */}
          {false && (
            <div className={styles.footer}>
              <span className={styles.chatCount}></span>
            </div>
          )}
        </div>
      </div>
      {showDeleteConfirmation && (
        <ConfirmationModal
          message="Are you sure you want to delete this chat? This action cannot be undone."
          onConfirm={confirmDeleteChat}
          setShowConfirmation={setShowDeleteConfirmation}
        />
      )}
    </>
  );
};

export default ChatHistorySlider;
