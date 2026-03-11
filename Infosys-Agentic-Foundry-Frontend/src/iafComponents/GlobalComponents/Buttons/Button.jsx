import styles from "./Button.module.css";

/**
 * Button component supporting primary, secondary, and icon-only variants.
 *
 * Props:
 * - type: "primary" | "secondary" | "icon" - Button variant
 * - htmlType: "button" | "submit" | "reset" - HTML button type (default: "button")
 * - children: Button text (not used for icon-only variant)
 * - icon: React node (icon element from SVGIcons or any React element)
 * - disabled: Boolean - Disable the button
 * - active: Boolean - Active/focused state styling
 * - loading: Boolean - Show loading spinner
 * - onClick: Function - Click handler
 * - className: String - Additional CSS classes
 * - title: String - Tooltip text
 * - ...rest: Other button props (e.g., aria-label, data-* attributes)
 *
 * Usage examples:
 * Primary: <Button type="primary">Save</Button>
 * Secondary: <Button type="secondary">Cancel</Button>
 * Submit: <Button type="primary" htmlType="submit">Submit Form</Button>
 * Icon: <Button type="icon" icon={<SVGIcons icon="eye" width={16} height={16} />} title="View" />
 */
const Button = ({ type = "primary", htmlType = "button", children, icon, disabled = false, active = false, loading = false, onClick, className = "", title, ...rest }) => {
  // Determine button style classes

  // Build class list using CSS module
  const classList = [
    styles.iafButton,
    type === "primary" || loading ? styles.iafButtonPrimary : "",
    type === "secondary" ? styles.iafButtonSecondary : "",
    type === "icon" ? styles.iconOnly : "",
    active ? styles.active : "",
    className, // allow passing extra classes (should be module-based)
  ]
    .filter(Boolean)
    .join(" ");

  const isDisabled = disabled || loading;

  // Sanitize string to prevent XSS - escape HTML entities
  const sanitizeString = (str) => {
    if (typeof str !== "string") return str;
    return str
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#x27;");
  };

  // Whitelist safe props to prevent XSS via spread operator
  const allowedProps = ["aria-label", "aria-describedby", "aria-expanded", "aria-haspopup", "aria-controls", "aria-pressed", "data-testid", "data-id", "id", "name", "tabIndex", "role", "form"];
  const safeProps = Object.keys(rest).reduce((acc, key) => {
    if (allowedProps.includes(key) || key.startsWith("data-")) {
      // Sanitize string values to prevent XSS
      const value = rest[key];
      acc[key] = typeof value === "string" ? sanitizeString(value) : value;
    }
    return acc;
  }, {});

  const safeTitle = sanitizeString(title);

  // Fortify False Positive: onClick is a function reference passed from parent component,
  // not user-controlled string data. React event handlers expect function references,
  // not executable strings like inline HTML onclick attributes.
  return (
    <button type={htmlType} className={classList} disabled={isDisabled} aria-disabled={isDisabled} onClick={onClick} title={safeTitle} {...safeProps}>
      {loading && (
        <svg
          className={styles.loadingSpinner}
          width="16"
          height="16"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round">
          <circle cx="12" cy="12" r="10" strokeOpacity="0.25" />
          <path d="M21 12a9 9 0 1 1-6.219-8.56" />
        </svg>
      )}

      {!loading && type === "icon" && icon && <span className={styles.iconWrapper}>{icon}</span>}

      {!loading && type !== "icon" && icon && <span className={styles.iconWrapper}>{icon}</span>}

      {!loading && type !== "icon" && children}
      {loading && type !== "icon" && loading && children}
    </button>
  );
};

export default Button;
