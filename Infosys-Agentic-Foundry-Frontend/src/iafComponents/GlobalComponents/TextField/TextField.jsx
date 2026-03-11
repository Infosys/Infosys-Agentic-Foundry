import React from "react";
import styles from "./TextField.module.css";
import SVGIcons from "../../../Icons/SVGIcons";

/**
 * TextField component supporting default, focus, with icon, and disabled states.
 * @param {object} props
 * @param {string} props.label - Label for the text field
 * @param {string} props.placeholder - Placeholder text
 * @param {boolean} props.disabled - Disabled state
 * @param {React.ReactNode} [props.icon] - Optional icon (JSX)
 * @param {string} [props.value] - Controlled value
 * @param {function} [props.onChange] - Change handler
 * @param {function} [props.onIconClick] - Icon/button click handler (for search)
 * @param {function} [props.onClear] - Clear button click handler
 * @param {boolean} [props.showClearButton] - Show clear button when value exists
 * @param {boolean} [props.showSearchButton] - Show clickable search button on right side
 * @param {function} [props.onSearch] - Search button click handler
 * @param {string} [props.className] - Additional className
 */
const TextField = ({
  label,
  placeholder = "",
  disabled = false,
  icon,
  value,
  onChange,
  onIconClick,
  onClear,
  showClearButton = false,
  showSearchButton = false,
  onSearch,
  className = "",
  ...rest
}) => {
  const hasClearButton = showClearButton && value;
  const hasLeftIcon = icon && !showSearchButton;

  return (
    <div className={styles.textFieldWrapper}>
      {label && <label className={styles.label}>{label}</label>}
      <div className={styles.inputContainer}>
        {icon && !showSearchButton && (
          <button type="button" className={styles.icon} onClick={onIconClick} tabIndex={-1} disabled={disabled} aria-label="icon">
            {icon}
          </button>
        )}
        <input
          type="text"
          className={[
            styles.inputBase,
            hasLeftIcon ? styles.inputWithIcon : "",
            hasClearButton && !showSearchButton ? styles.inputWithRightContent : "",
            showSearchButton ? (hasClearButton ? styles.inputWithSearchAndClear : styles.inputWithSearchButton) : "",
            disabled ? styles.inputDisabled : "",
            className
          ]
            .filter(Boolean)
            .join(" ")}
          placeholder={placeholder}
          disabled={disabled}
          value={value}
          onChange={onChange}
          {...rest}
        />
        {hasClearButton && !showSearchButton && (
          <div className={styles.rightContent}>
            <button type="button" className={styles.clearButton} onClick={onClear} tabIndex={-1} disabled={disabled} aria-label="Clear">
              <SVGIcons icon="x" width={14} height={14} stroke="var(--content-color, #6b7280)" color="var(--content-color, #6b7280)" />
            </button>
          </div>
        )}
        {hasClearButton && showSearchButton && (
          <button type="button" className={styles.clearButtonWithSearch} onClick={onClear} tabIndex={-1} disabled={disabled} aria-label="Clear">
            <SVGIcons icon="x" width={14} height={14} stroke="var(--content-color, #6b7280)" color="var(--content-color, #6b7280)" />
          </button>
        )}
        {showSearchButton && (
          <button type="button" className={styles.searchIcon} onClick={onSearch} disabled={disabled} aria-label="Search">
            <SVGIcons icon="search" width={16} height={16} stroke="var(--button-text-color, #fff)" />
          </button>
        )}
      </div>
    </div>
  );
};

export default TextField;
