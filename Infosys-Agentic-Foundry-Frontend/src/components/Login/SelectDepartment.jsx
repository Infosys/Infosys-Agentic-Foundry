import React, { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import axios from "axios";
import { APIs, BASE_URL } from "../../constant";
import { getAccessToken } from "../../auth/tokenProvider";
import { useVersion } from "../../context/VersionContext";
import { useTheme } from "../../Hooks/ThemeContext";
import brandlogotwo from "../../Assets/Agentic-Foundry-Logo-Dark-2.png";
import SVGIcons from "../../Icons/SVGIcons";
import styles from "./SelectDepartment.module.css";
import "./app.css";
import "./login.css";

/**
 * SelectDepartment — shown to brand-new SSO users who need to pick departments.
 *
 * Backend redirects here after a first-time SSO login:
 *   /select-department?email=user@example.com&username=john
 *
 * Flow:
 *   1. Read email + username from URL params.
 *   2. Fetch department list from /auth/departments.
 *   3. User picks one or more departments and submits.
 *   4. POST to /auth/sso/register  →  navigate to /pending-approval.
 */
function SelectDepartment() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { combinedVersion } = useVersion();
  const { theme, toggleTheme } = useTheme();

  const email = searchParams.get("email") || "";
  const username = searchParams.get("username") || "";

  const [departments, setDepartments] = useState([]);
  const [selectedDepts, setSelectedDepts] = useState([]);
  const [loadingDepts, setLoadingDepts] = useState(true);
  const [fetchError, setFetchError] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  // Guard — must have email + username in URL
  useEffect(() => {
    if (!email || !username) {
      navigate("/login", { replace: true });
    }
  }, [email, username, navigate]);

  // Fetch department list — MSAL token required (SSO onboarding only)
  const fetchDepartments = async () => {
    setLoadingDepts(true);
    setFetchError(false);
    try {
      const token = await getAccessToken();
      const res = await axios.get(`${BASE_URL}${APIs.GET_DEPARTMENTS}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      const body = res.data;
      let items = [];
      if (Array.isArray(body)) {
        items = body;
      } else if (body?.success && Array.isArray(body.departments)) {
        items = body.departments;
      } else if (Array.isArray(body?.departments)) {
        items = body.departments;
      } else if (Array.isArray(body?.data)) {
        items = body.data;
      }
      const names = items.map((d) =>
        typeof d === "string" ? d : d.department_name || d.name || String(d)
      );
      setDepartments(names);
    } catch {
      setDepartments([]);
      setFetchError(true);
    } finally {
      setLoadingDepts(false);
    }
  };

  useEffect(() => {
    fetchDepartments();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const toggleDept = (dept) => {
    setSelectedDepts((prev) =>
      prev.includes(dept) ? prev.filter((d) => d !== dept) : [...prev, dept]
    );
    setError("");
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (selectedDepts.length === 0) {
      setError("Please select at least one department.");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const token = await getAccessToken();
      await axios.post(
        `${BASE_URL}${APIs.SSO_REGISTER}`,
        { email, username, department_names: selectedDepts },
        {
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${token}`,
          },
        }
      );
      navigate(`/pending-approval?email=${encodeURIComponent(email)}`, {
        replace: true,
      });
    } catch (err) {
      const msg =
        err?.response?.data?.detail ||
        err?.response?.data?.message ||
        "Failed to submit department request. Please try again.";
      setError(msg);
      setSubmitting(false);
    }
  };

  return (
    <div className="app-container">
      <img src={brandlogotwo} alt="Agentic Foundry" />
      <div className="version_number" title={combinedVersion}>
        {combinedVersion}
      </div>

      <button
        className="authThemeToggle"
        title={theme === "light" ? "Switch to Dark Mode" : "Switch to Light Mode"}
        onClick={toggleTheme}
        aria-label="Toggle theme"
      >
        <SVGIcons
          icon={theme === "light" ? "dark-icon" : "light-icon"}
          width={18}
          height={18}
          fill="var(--text-primary)"
          stroke={theme === "light" ? "var(--app-primary-color)" : "var(--text-primary)"}
        />
      </button>

      <div className={styles.centeredWrapper}>
        <div className={styles.card}>
          {/* Header */}
          <div className={styles.header}>
            <div className={styles.iconWrap}>
              <SVGIcons icon="fa-user" width={22} height={22} fill="currentColor" />
            </div>
            <div>
              <h2 className={styles.title}>Select Departments</h2>
              <p className={styles.subtitle}>
                Welcome, <strong>{username}</strong>. Choose the departments you
                need access to.
              </p>
            </div>
          </div>

          {/* Email badge */}
          <div className={styles.emailBadge}>
            <SVGIcons icon="at-sign" width={13} height={13} fill="currentColor" />
            <span>{email}</span>
          </div>

          <form onSubmit={handleSubmit}>
            {/* Department list */}
            <div className={styles.deptListLabel}>Available Departments</div>
            {loadingDepts ? (
              <div className={styles.loadingRow}>
                <div className={styles.spinner} />
                <span>Loading departments…</span>
              </div>
            ) : fetchError ? (
              <div className={styles.fetchErrorWrap}>
                <p className={styles.fetchErrorMsg}>
                  We couldn't load departments. Try again.
                </p>
                <button
                  type="button"
                  className={styles.retryBtn}
                  onClick={fetchDepartments}
                >
                  <SVGIcons icon="refresh" width={14} height={14} stroke="currentColor" />
                  Retry
                </button>
              </div>
            ) : departments.length === 0 ? (
              <p className={styles.emptyMsg}>
                No departments available. Contact your administrator.
              </p>
            ) : (
              <ul className={styles.deptList}>
                {departments.map((dept) => {
                  const checked = selectedDepts.includes(dept);
                  return (
                    <li key={dept}>
                      <button
                        type="button"
                        className={`${styles.deptItem} ${checked ? styles.deptItemSelected : ""}`}
                        onClick={() => toggleDept(dept)}
                        aria-pressed={checked}
                      >
                        <span className={styles.deptName}>{dept}</span>
                        {checked && (
                          <span className={styles.checkIcon}>
                            <SVGIcons
                              icon="circle-check"
                              width={16}
                              height={16}
                              fill="currentColor"
                            />
                          </span>
                        )}
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}

            {/* Selection summary */}
            {selectedDepts.length > 0 && (
              <p className={styles.selectionCount}>
                {selectedDepts.length} department
                {selectedDepts.length > 1 ? "s" : ""} selected
              </p>
            )}

            {/* Error */}
            {error && (
              <div className={styles.errorBanner}>
                <SVGIcons
                  icon="exclamation"
                  width={14}
                  height={14}
                  fill="currentColor"
                />
                <span>{error}</span>
              </div>
            )}

            <button
              type="submit"
              className="submitBtn"
              disabled={submitting || loadingDepts || departments.length === 0}
            >
              {submitting ? (
                <>
                  <div className={styles.spinner} />
                  Submitting…
                </>
              ) : (
                <>
                  Request Access
                  <SVGIcons
                    icon="arrow-right"
                    width={14}
                    height={14}
                    stroke="currentColor"
                  />
                </>
              )}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}

export default SelectDepartment;
