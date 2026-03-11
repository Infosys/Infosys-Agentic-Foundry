/**
 * SummaryLine Component
 *
 * A reusable component for displaying item counts.
 * Works with both paginated APIs (showing x of total) and non-paginated (showing current count).
 *
 * @param {number} visibleCount - Number of currently visible/loaded items
 * @param {number} [totalCount] - Total count from API (optional - defaults to visibleCount for non-paginated)
 * @param {string} [itemLabel] - Label for items (e.g., "agents", "tools") - optional, defaults to "items"
 * @param {string} [className] - Additional CSS class for custom styling
 * @param {boolean} [showWhenEmpty=false] - Whether to show the summary when count is 0
 *
 * @example
 * // Paginated API usage - shows "Showing items 10 of 50"
 * <SummaryLine visibleCount={visibleData.length} totalCount={totalAgentCount} />
 *
 * @example
 * // Non-paginated API usage (totalCount defaults to visibleCount)  - shows "Showing items 5 of 5"
 * <SummaryLine visibleCount={agentList.length} />
 *
 * @example
 * // With custom label - shows "Showing agents 10 of 50"
 * <SummaryLine visibleCount={10} totalCount={50} itemLabel="agents" />
 */
const SummaryLine = ({ visibleCount, totalCount, itemLabel = "items", className = "", showWhenEmpty = false }) => {
  // Use visibleCount as totalCount if not provided (non-paginated scenario)
  const displayTotal = totalCount ?? visibleCount;

  // Don't render if no items and showWhenEmpty is false
  if (!showWhenEmpty && visibleCount === 0) {
    return null;
  }

  return (
    <div className={`summary-line ${className}`.trim()}>
      Showing {itemLabel} <strong>{visibleCount}</strong> of <strong>{displayTotal}</strong>
    </div>
  );
};

export default SummaryLine;
