import SVGIcons from "../../../Icons/SVGIcons";
import HaderStyle from "./Header.module.css";

/**
 * Header1 - Modular header with optional click handler.
 * @param {string} name - Header text
 * @param {function} handleRefresh - Optional refresh handler
 * @param {function} onHeaderClick - Optional click handler for header (e.g., to toggle checkbox)
 * @param {boolean} enableHeaderClick - If true, header is clickable
 */
const Header1 = ({ name, handleRefresh, onHeaderClick, enableHeaderClick = false }) => {
  const handleClick = (e) => {
    if (enableHeaderClick && typeof onHeaderClick === "function") {
      e.stopPropagation();
      onHeaderClick(e);
    }
  };
  return (
    <div className={`${HaderStyle["header-container"]} ellipsis`}>
      <p
        className={`header-text${enableHeaderClick ? " clickable-header" : ""}`}
        title={name}
        onClick={handleClick}
        tabIndex={enableHeaderClick ? 0 : -1}
        role={enableHeaderClick ? "button" : undefined}
        aria-pressed={enableHeaderClick ? "false" : undefined}
        style={enableHeaderClick ? { cursor: "pointer" } : {}}>
        {name}
      </p>
      {handleRefresh && (
        <button
          type="button"
          onClick={() => {
            if (typeof handleRefresh === "function") handleRefresh();
          }}
          title="Refresh"
          className="refresh-button">
          <SVGIcons icon="refresh" fill="none" stroke="var(--content-color, #6b7280)"></SVGIcons>
        </button>
      )}
    </div>
  );
};

export default Header1;
