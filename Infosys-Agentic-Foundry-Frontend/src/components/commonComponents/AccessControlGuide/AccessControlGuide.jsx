import React from "react";
import ReactDOM from "react-dom";
import SVGIcons from "../../../Icons/SVGIcons";
import styles from "./AccessControlGuide.module.css";

/**
 * AccessControlGuide - A reusable modal component that displays
 * comprehensive documentation for Python access control decorators.
 *
 * @param {Object} props
 * @param {boolean} props.isOpen - Controls visibility of the modal
 * @param {function} props.onClose - Callback function to close the modal
 */
const AccessControlGuide = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return ReactDOM.createPortal(
    <div className={styles.overlay} onClick={onClose}>
      <div className={styles.popup} onClick={(e) => e.stopPropagation()}>
        {/* Header */}
        <div className={styles.header}>
          <h2>Access Control Decorators</h2>
          <button
            type="button"
            className={styles.closeBtn}
            onClick={onClose}
            aria-label="Close"
          >
            <SVGIcons icon="x" width={20} height={20} />
          </button>
        </div>

        {/* Content */}
        <div className={styles.content}>
          {/* Introduction */}
          <div className={styles.introSection}>
            <p>
              When creating tools in IAF, you can implement fine-grained access control using <strong>decorators</strong>. These decorators allow you to:
            </p>
            <ul className={styles.featureList}>
              <li><strong>Control data-level access</strong> - Restrict which specific resources (employees, projects, etc.) a user can access</li>
              <li><strong>Control role-level access</strong> - Restrict which roles can execute certain tools</li>
              <li><strong>Combine both</strong> - Apply both role and resource checks together</li>
            </ul>
          </div>

          {/* Section 1: @resource_access */}
          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>
              <span className={styles.sectionNumber}>1</span>
              <code>@resource_access</code> - Data-Level Access Control
            </h3>

            <div className={styles.subsection}>
              <h4>What It Does</h4>
              <p>Checks if the user has permission to access the <strong>specific value</strong> passed to a function parameter.</p>
            </div>

            <div className={styles.subsection}>
              <h4>Syntax</h4>
              <div className={styles.codeBlock}>
                <pre>{`@resource_access(access_key: str, param_name: str)
def your_tool_function(param_name: str):
    ...`}</pre>
              </div>
              <ul className={styles.paramList}>
                <li><code>access_key</code>: The type of resource (e.g., <code>"employees"</code>, <code>"projects"</code>, <code>"databases"</code>)</li>
                <li><code>param_name</code>: The name of your function parameter that contains the resource ID to check</li>
              </ul>
            </div>

            <div className={styles.subsection}>
              <h4>Example: Employee Access Control</h4>
              <div className={styles.codeBlock}>
                <pre>{`@resource_access("employees", "emp_id")
def get_employee_salary(emp_id: str):
    """
    Get salary for an employee.
    User must have this emp_id in their 'employees' access list.

    Args:
        emp_id: The employee ID to look up

    Returns:
        dict with employee salary information
    """
    # Your logic here - only runs if user has access
    return {"emp_id": emp_id, "salary": 85000}`}</pre>
              </div>

              <div className={styles.howItWorks}>
                <strong>How it works:</strong>
                <ul>
                  <li>If user "john@company.com" has access list: <code>{`{"employees": ["EMP001", "EMP002"]}`}</code></li>
                  <li>Calling <code>get_employee_salary("EMP001")</code> → ✅ <strong>Allowed</strong></li>
                  <li>Calling <code>get_employee_salary("EMP003")</code> → ❌ <strong>Denied</strong> (403 error)</li>
                </ul>
              </div>
            </div>

            <div className={styles.subsection}>
              <h4>Example: Database Access Control</h4>
              <div className={styles.codeBlock}>
                <pre>{`@resource_access("databases", "db_name")
def query_database(db_name: str, query: str):
    """
    Run a query on a specific database.
    User must have access to the specified database.

    Args:
        db_name: Name of the database to query
        query: SQL query to execute

    Returns:
        Query results
    """
    # Execute query - only if user has database access
    return {"result": "query_results_here"}`}</pre>
              </div>
            </div>
          </div>

          {/* Section 2: @require_role */}
          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>
              <span className={styles.sectionNumber}>2</span>
              <code>@require_role</code> - Role-Based Access Control
            </h3>

            <div className={styles.subsection}>
              <h4>What It Does</h4>
              <p>Checks if the user has one of the <strong>required roles</strong> before allowing tool execution.</p>
            </div>

            <div className={styles.subsection}>
              <h4>Syntax</h4>
              <div className={styles.codeBlock}>
                <pre>{`@require_role(*required_roles: str)
def your_tool_function(...):
    ...`}</pre>
              </div>
            </div>

            <div className={styles.subsection}>
              <h4>Example: Admin-Only Tool</h4>
              <div className={styles.codeBlock}>
                <pre>{`@require_role("Admin")
def delete_all_records(table_name: str):
    """
    Delete all records from a table.
    Only Admins can execute this dangerous operation.

    Args:
        table_name: The table to clear

    Returns:
        Deletion confirmation
    """
    return {"deleted": True, "table": table_name}`}</pre>
              </div>
            </div>

            <div className={styles.subsection}>
              <h4>Example: Multiple Roles Allowed</h4>
              <div className={styles.codeBlock}>
                <pre>{`@require_role("Admin", "Manager", "HR")
def view_sensitive_data(report_type: str):
    """
    View sensitive company data.
    Only Admin, Manager, or HR roles can access.

    Args:
        report_type: Type of report to generate

    Returns:
        Sensitive report data
    """
    return {"report": report_type, "data": "sensitive_info"}`}</pre>
              </div>
            </div>
          </div>

          {/* Section 3: @authorized_tool */}
          <div className={styles.section}>
            <h3 className={styles.sectionTitle}>
              <span className={styles.sectionNumber}>3</span>
              <code>@authorized_tool</code> - Combined Access Control
            </h3>

            <div className={styles.subsection}>
              <h4>What It Does</h4>
              <p>Combines <strong>role checks</strong> AND <strong>resource checks</strong> in a single decorator.</p>
            </div>

            <div className={styles.subsection}>
              <h4>Syntax</h4>
              <div className={styles.codeBlock}>
                <pre>{`@authorized_tool(
    required_roles: List[str] = None,        # Roles allowed (None = any role)
    resource_checks: Dict[str, str] = None   # {access_key: param_name}
)
def your_tool_function(...):
    ...`}</pre>
              </div>
            </div>

            <div className={styles.subsection}>
              <h4>Example: Role + Single Resource Check</h4>
              <div className={styles.codeBlock}>
                <pre>{`@authorized_tool(
    required_roles=["Manager", "Admin"],
    resource_checks={"employees": "emp_id"}
)
def update_employee_salary(emp_id: str, new_salary: float):
    """
    Update an employee's salary.
    - Only Managers and Admins can use this
    - They can only update employees they have access to

    Args:
        emp_id: Employee ID to update
        new_salary: New salary amount

    Returns:
        Update confirmation
    """
    return {"emp_id": emp_id, "new_salary": new_salary, "updated": True}`}</pre>
              </div>
            </div>

            <div className={styles.subsection}>
              <h4>Example: Role + Multiple Resource Checks</h4>
              <div className={styles.codeBlock}>
                <pre>{`@authorized_tool(
    required_roles=["Manager", "Admin"],
    resource_checks={
        "projects": "project_id",
        "employees": "emp_id"
    }
)
def assign_employee_to_project(project_id: str, emp_id: str, role: str):
    """
    Assign an employee to a project.
    - Only Managers/Admins can assign
    - Must have access to BOTH the project AND the employee

    Args:
        project_id: Project to assign to
        emp_id: Employee to assign
        role: Role in the project

    Returns:
        Assignment confirmation
    """
    return {
        "project_id": project_id,
        "emp_id": emp_id,
        "role": role,
        "assigned": True
    }`}</pre>
              </div>
            </div>

            <div className={styles.subsection}>
              <h4>Example: Resource Check Only (No Role Restriction)</h4>
              <div className={styles.codeBlock}>
                <pre>{`@authorized_tool(
    required_roles=None,  # Any role can call
    resource_checks={"databases": "db_name"}
)
def backup_database(db_name: str, backup_location: str):
    """
    Backup a database.
    Any role can call, but must have access to the specific database.

    Args:
        db_name: Database to backup
        backup_location: Where to store the backup

    Returns:
        Backup status
    """
    return {"db_name": db_name, "backup_location": backup_location, "status": "completed"}`}</pre>
              </div>
            </div>
          </div>

          {/* Wildcard Info */}
          <div className={styles.wildcardInfo}>
            <div>
              <strong>Wildcard Access</strong>
              <p>If a user has <code>"*"</code> in their access list, they can access <strong>all values</strong> for that key:</p>
              <div className={styles.codeBlock}>
                <pre>{`{
  "employees": ["*"],     // Can access ALL employees
  "projects": ["PROJ-A"]  // Can only access PROJ-A
}`}</pre>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
};

export default AccessControlGuide;
