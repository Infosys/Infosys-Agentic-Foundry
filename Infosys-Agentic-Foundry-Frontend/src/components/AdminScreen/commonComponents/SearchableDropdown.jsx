import React from "react";
import styles from "../AgentAssignment.module.css";

const SearchableDropdown = ({
  isOpen,
  onToggle,
  onClose,
  searchTerm,
  onSearchChange,
  placeholder = "Select...",
  searchPlaceholder = "Search...",
  items = [],
  selectedItems = [],
  onItemSelect,
  onItemRemove,
  renderItem,
  renderSelectedItem,
  highlightedIndex = -1,
  onKeyDown,
  multiple = false,
  required = false,
  label,
  error,
  disabled = false
}) => {
  const handleDropdownClick = (e) => {
    e.stopPropagation();
    if (!disabled) {
      onToggle();
    }
  };

  const handleItemClick = (item) => {
    onItemSelect(item);
    if (!multiple) {
      onClose();
    }
  };

  return (
    <div className={styles.controlGroup}>
      {label && (
        <label className={styles.controlLabel}>
          {label} {required && "*"}
        </label>
      )}
      
      <div className={styles.searchableDropdown}>
        <div
          className={`${styles.dropdownTrigger} ${isOpen ? styles.active : ""} ${disabled ? styles.disabled : ""}`}
          onClick={handleDropdownClick}
          onKeyDown={onKeyDown}
          tabIndex={disabled ? -1 : 0}
          role="combobox"
          aria-expanded={isOpen}
          aria-haspopup="listbox"
          aria-controls="dropdown-listbox"
        >
          <span>
            {selectedItems.length > 0 && multiple
              ? `${selectedItems.length} selected`
              : selectedItems.length === 1 && !multiple
              ? renderSelectedItem ? renderSelectedItem(selectedItems[0]) : selectedItems[0].name || selectedItems[0].email || selectedItems[0]
              : placeholder
            }
          </span>
          <svg
            width="18"
            height="18"
            viewBox="0 0 20 20"
            fill="none"
            xmlns="http://www.w3.org/2000/svg"
            className={`${styles.chevronIcon} ${isOpen ? styles.rotated : ""}`}
          >
            <path d="M6 8L10 12L14 8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>

        {/* Selected items display for multiple selection */}
        {multiple && selectedItems.length > 0 && (
          <div className={styles.selectedItems}>
            {selectedItems.map((item, index) => (
              <div key={index} className={styles.selectedItem}>
                <span>{renderSelectedItem ? renderSelectedItem(item) : item.name || item.email || item}</span>
                <button
                  type="button"
                  onClick={() => onItemRemove(item)}
                  className={styles.removeSelectedItem}
                >
                  ×
                </button>
              </div>
            ))}
          </div>
        )}

        {isOpen && (
          <div
            className={styles.dropdownContent}
            onClick={(e) => e.stopPropagation()}
            role="listbox"
            id="dropdown-listbox"
          >
            <div className={styles.searchContainer}>
              <svg width="18" height="18" viewBox="0 0 20 20" fill="none" xmlns="http://www.w3.org/2000/svg" className={styles.searchIcon}>
                <circle cx="9" cy="9" r="6" stroke="currentColor" strokeWidth="1.5" fill="none" />
                <path d="m15 15 4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
              </svg>
              <input
                type="text"
                placeholder={searchPlaceholder}
                value={searchTerm}
                onChange={(e) => onSearchChange(e.target.value)}
                className={styles.searchInput}
                autoComplete="off"
              />
            </div>
            
            <div className={styles.itemsList}>
              {items.length === 0 ? (
                <div className={styles.noResults}>No items found</div>
              ) : (
                items.map((item, index) => (
                  <div
                    key={index}
                    className={`${styles.dropdownItem} ${highlightedIndex === index ? styles.highlighted : ""}`}
                    onClick={() => handleItemClick(item)}
                    role="option"
                    aria-selected={highlightedIndex === index}
                  >
                    {renderItem ? renderItem(item) : item.name || item.email || item}
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </div>
      
      {error && <div className={styles.errorMessage}>{error}</div>}
    </div>
  );
};

export default SearchableDropdown;