import React from "react";
import styles from "./EmptyState.module.css";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";

/**
 * EmptyState Component
 *
 * Displays an empty state UI for screens with no data.
 * Supports two modes:
 * 1. Filter mode - Shows active filters and option to clear them (when filters are applied but no results)
 * 2. Empty mode - Shows simple message when no data exists in backend
 *
 * @param {Array} filters - Active filters to display (search, tags, types, etc.)
 * @param {Function} onClearFilters - Handler to clear all filters
 * @param {Function} onCreateClick - Handler for create button click
 * @param {string} createButtonLabel - Label for the create button (e.g., "Create Tool", "Create Agent")
 * @param {boolean} showClearFilter - Whether to show the clear filter button
 * @param {boolean} showCreateButton - Whether to show the create button
 * @param {string} message - Main message to display (defaults based on context)
 * @param {string} subMessage - Secondary message to display below the main message
 */
const EmptyState = ({
  filters = [],
  onClearFilters,
  onCreateClick,
  createButtonLabel = "New Tool",
  showClearFilter = true,
  showCreateButton = true,
  message = "No matching results",
  subMessage = "",
}) => {
  // Categorize filters by type
  const categorizedFilters = React.useMemo(() => {
    const categories = {
      search: [],
      type: [],
      industry: [],
      createdBy: [],
      other: [],
    };

    filters.forEach((filter) => {
      if (typeof filter === "string") {
        const lowerFilter = filter.toLowerCase();
        if (lowerFilter.startsWith("search:")) {
          categories.search.push(filter.replace(/^search:\s*/i, ""));
        } else if (lowerFilter.startsWith("created by:")) {
          categories.createdBy.push(filter.replace(/^created by:\s*/i, ""));
        } else if (lowerFilter.includes("validator") || lowerFilter.includes("tool") || lowerFilter.includes("agent")) {
          // Check if it's a type filter (Tool, Validator, Agent types)
          categories.type.push(filter);
        } else {
          // Assume it's an industry/tag filter
          categories.industry.push(filter);
        }
      } else {
        categories.other.push(filter);
      }
    });

    return categories;
  }, [filters]);

  const hasAnyFilters = filters && filters.length > 0;

  return (
    <div className={styles.container} data-empty-state="true">
      <div className={styles.iconWrapper}>
        <div className={styles.iconGlow}></div>
        <div className={styles.iconCircle}>
          <svg
            xmlns="http://www.w3.org/2000/svg"
            width="32"
            height="32"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            className={styles.funnelIcon}
            aria-hidden="true">
            <path d="M10 20a1 1 0 0 0 .553.895l2 1A1 1 0 0 0 14 21v-7a2 2 0 0 1 .517-1.341L21.74 4.67A1 1 0 0 0 21 3H3a1 1 0 0 0-.742 1.67l7.225 7.989A2 2 0 0 1 10 14z"></path>
          </svg>
        </div>
      </div>

      <h3 className={styles.heading}>{message}</h3>

      {/* Show sub-message if provided, otherwise show filter-related message */}
      {subMessage && <p className={styles.message}>{subMessage}</p>}
      {!subMessage && hasAnyFilters && <p className={styles.message}>Try adjusting or clearing your filters to see more results</p>}

      {hasAnyFilters && (
        <div className={styles.filtersContainer}>
          {/* Search Section */}
          {categorizedFilters.search.length > 0 && (
            <div className={styles.filterGroup}>
              <span className={styles.filterGroupLabel}>Search:</span>
              <div className={styles.filterBadges}>
                {categorizedFilters.search.map((filter, index) => (
                  <span key={`search-${index}`} className={styles.badge}>
                    {filter}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Type Section */}
          {categorizedFilters.type.length > 0 && (
            <div className={styles.filterGroup}>
              <span className={styles.filterGroupLabel}>Type:</span>
              <div className={styles.filterBadges}>
                {categorizedFilters.type.map((filter, index) => (
                  <span key={`type-${index}`} className={styles.badge}>
                    {filter}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Industry/Tags Section */}
          {categorizedFilters.industry.length > 0 && (
            <div className={styles.filterGroup}>
              <span className={styles.filterGroupLabel}>Industry:</span>
              <div className={styles.filterBadges}>
                {categorizedFilters.industry.map((filter, index) => (
                  <span key={`industry-${index}`} className={styles.badge}>
                    {filter}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Created By Section */}
          {categorizedFilters.createdBy.length > 0 && (
            <div className={styles.filterGroup}>
              <span className={styles.filterGroupLabel}>Created By:</span>
              <div className={styles.filterBadges}>
                {categorizedFilters.createdBy.map((filter, index) => (
                  <span key={`createdBy-${index}`} className={styles.badge}>
                    {filter}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Other Filters Section */}
          {categorizedFilters.other.length > 0 && (
            <div className={styles.filterGroup}>
              <span className={styles.filterGroupLabel}>Other:</span>
              <div className={styles.filterBadges}>
                {categorizedFilters.other.map((filter, index) => (
                  <span key={`other-${index}`} className={styles.badge}>
                    {filter}
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div className={styles.actions}>
        {showClearFilter && hasAnyFilters && (
          <IAFButton type="secondary" onClick={onClearFilters} aria-label={"Clear Filter"}>
            Clear Filter
          </IAFButton>
        )}
        {showCreateButton && onCreateClick && (
          <IAFButton type="primary" onClick={onCreateClick} aria-label={createButtonLabel}>
            {createButtonLabel}
          </IAFButton>
        )}
      </div>
    </div>
  );
};

export default EmptyState;
