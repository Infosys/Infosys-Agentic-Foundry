import { useState, useEffect, useCallback, useRef } from "react";
import styles from "./LLMTracker.module.css";
import { useLlmTrackerService } from "../../services/llmTrackerService";
import SubHeader from "../commonComponents/SubHeader";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine";
import SVGIcons from "../../Icons/SVGIcons";
import { useAuth } from "../../context/AuthContext";
import { getRoleFromToken, getEmailFromToken } from "../../utils/jwtUtils";

// ─────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────
const LEVEL = { USERS: 1, SESSIONS: 2, REQUESTS: 3, CALLS: 4 };

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────
const formatDate = (isoString) => {
  if (!isoString) return "—";
  return new Date(isoString).toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
};

const safeParseJson = (str) => {
  try { return JSON.parse(str); } catch { return str; }
};

// Truncate long IDs for breadcrumb labels — full value is still in the table
const truncateId = (id, maxLen = 28) => {
  if (!id) return "";
  return id.length > maxLen ? `${id.slice(0, maxLen)}\u2026` : id;
};

// ─── Shared sub-components ───────────────────────────────────────────────────

function StatStrip({ stats }) {
  return (
    <div className={styles.statStrip}>
      {stats.map((s) => (
        <div key={s.label} className={`${styles.statCard} ${s.variant ? styles[s.variant] : ""}`}>
          <span className={styles.statValue}>{s.value ?? "—"}</span>
          <span className={styles.statLabel}>{s.label}</span>
        </div>
      ))}
    </div>
  );
}

function Badge({ value, variant }) {
  // variant: "Success" | "Danger"
  return (
    <span className={`${styles.badge} ${styles["badge" + variant]}`}>{value ?? 0}</span>
  );
}

function ErrorBanner({ message, status }) {
  const is403 = status === 403 || (typeof message === "string" && message.toLowerCase().includes("permission"));
  return (
    <div className={`${styles.errorBanner} ${is403 ? styles.errorBanner403 : ""}`}>
      <SVGIcons icon={is403 ? "vault-lock" : "warning"} width={18} height={18} fill={is403 ? "var(--warning)" : "var(--danger)"} />
      <div className={styles.errorBannerText}>
        <strong>{is403 ? "Access Denied" : "Error"}</strong>
        <span>{message}</span>
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Level 1 — Users
// ═══════════════════════════════════════════════════════════════════════════════
function UsersTable({ data, filter, onRowClick }) {
  const filtered = data.filter((u) =>
    (u.user_id || "").toLowerCase().includes(filter.toLowerCase())
  );
  const total = data.reduce((s, u) => s + (u.total_requests || 0), 0);
  const success = data.reduce((s, u) => s + (u.successful_requests || 0), 0);
  const failed = data.reduce((s, u) => s + (u.failed_requests || 0), 0);

  return (
    <>
      <StatStrip stats={[
        { label: "Total Users", value: data.length },
        { label: "Total Requests", value: total },
        { label: "Successful", value: success, variant: "success" },
        { label: "Failed", value: failed, variant: "danger" },
      ]} />
      <div className={styles.tableContainer}>
        {filtered.length === 0 ? (
          <EmptyState
            message="No users found"
            subMessage="Try adjusting your search filter"
            showCreateButton={false}
            showClearFilter={false}
          />
        ) : (
          <>
            <SummaryLine visibleCount={filtered.length} totalCount={data.length} itemLabel="users" />
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th className={styles.thId}>User ID</th>
                  <th className={styles.thNum}>Total Requests</th>
                  <th className={styles.thNum}>Successful</th>
                  <th className={styles.thNum}>Failed</th>
                  <th>First Request</th>
                  <th>Last Request</th>
                  <th className={styles.thChev}></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((u) => (
                  <tr
                    key={u.user_id}
                    className={styles.clickableRow}
                    onClick={() => onRowClick(u)}
                    title={`View sessions for ${u.user_id}`}
                  >
                    <td><span className={styles.idChip}>{u.user_id}</span></td>
                    <td className={styles.tdNum}>{u.total_requests ?? 0}</td>
                    <td className={styles.tdNum}><Badge value={u.successful_requests} variant="Success" /></td>
                    <td className={styles.tdNum}><Badge value={u.failed_requests} variant="Danger" /></td>
                    <td className={styles.tdDate}>{formatDate(u.first_request)}</td>
                    <td className={styles.tdDate}>{formatDate(u.last_request)}</td>
                    <td className={styles.tdChev}><SVGIcons icon="chevron-right" width={14} height={14} stroke="var(--content-color)" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Level 2 — Sessions
// ═══════════════════════════════════════════════════════════════════════════════
function SessionsTable({ data, filter, onRowClick, onBack }) {
  const filtered = data.filter((s) =>
    (s.session_id || "").toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <>
      <StatStrip stats={[
        { label: "Total Sessions", value: data.length },
        { label: "Total Requests", value: data.reduce((s, r) => s + (r.total_requests || 0), 0) },
        { label: "Successful", value: data.reduce((s, r) => s + (r.successful_requests || 0), 0), variant: "success" },
        { label: "Failed", value: data.reduce((s, r) => s + (r.failed_requests || 0), 0), variant: "danger" },
      ]} />
      {onBack && (
        <div className={styles.callsBackRow}>
          <button className={styles.backBtn} onClick={onBack} title="Back to Users">
            <SVGIcons icon="chevron-left" width={14} height={14} stroke="currentColor" />
          </button>
        </div>
      )}
      <div className={styles.tableContainer}>
        {filtered.length === 0 ? (
          <EmptyState
            message="No sessions found"
            subMessage="Try adjusting your search filter"
            showCreateButton={false}
            showClearFilter={false}
          />
        ) : (
          <>
            <SummaryLine visibleCount={filtered.length} totalCount={data.length} itemLabel="sessions" />
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th className={styles.thId}>Session ID</th>
                  <th className={styles.thNum}>Total Requests</th>
                  <th className={styles.thNum}>Successful</th>
                  <th className={styles.thNum}>Failed</th>
                  <th>First Request</th>
                  <th>Last Request</th>
                  <th className={styles.thChev}></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((s) => (
                  <tr
                    key={s.session_id}
                    className={styles.clickableRow}
                    onClick={() => onRowClick(s)}
                    title={`View requests for ${s.session_id}`}
                  >
                    <td><span className={styles.idChip}>{s.session_id}</span></td>
                    <td className={styles.tdNum}>{s.total_requests ?? 0}</td>
                    <td className={styles.tdNum}><Badge value={s.successful_requests} variant="Success" /></td>
                    <td className={styles.tdNum}><Badge value={s.failed_requests} variant="Danger" /></td>
                    <td className={styles.tdDate}>{formatDate(s.first_request)}</td>
                    <td className={styles.tdDate}>{formatDate(s.last_request)}</td>
                    <td className={styles.tdChev}><SVGIcons icon="chevron-right" width={14} height={14} stroke="var(--content-color)" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Level 3 — Requests
// ═══════════════════════════════════════════════════════════════════════════════
function RequestsTable({ data, filter, onRowClick, onBack }) {
  const filtered = data.filter((r) =>
    (r.request_id || "").toLowerCase().includes(filter.toLowerCase())
  );

  return (
    <>
      <StatStrip stats={[
        { label: "Unique Requests", value: data.length },
        { label: "Total LLM Calls", value: data.reduce((s, r) => s + (r.total_llm_calls || 0), 0) },
        { label: "Successful", value: data.reduce((s, r) => s + (r.successful_calls || 0), 0), variant: "success" },
        { label: "Failed", value: data.reduce((s, r) => s + (r.failed_calls || 0), 0), variant: "danger" },
      ]} />
      {onBack && (
        <div className={styles.callsBackRow}>
          <button className={styles.backBtn} onClick={onBack} title="Back to Sessions">
            <SVGIcons icon="chevron-left" width={14} height={14} stroke="currentColor" />
          </button>
        </div>
      )}
      <div className={styles.tableContainer}>
        {filtered.length === 0 ? (
          <EmptyState
            message="No requests found"
            subMessage="Try adjusting your search filter"
            showCreateButton={false}
            showClearFilter={false}
          />
        ) : (
          <>
            <SummaryLine visibleCount={filtered.length} totalCount={data.length} itemLabel="requests" />
            <table className={styles.dataTable}>
              <thead>
                <tr>
                  <th className={styles.thId}>Request ID</th>
                  <th className={styles.thNum}>LLM Calls</th>
                  <th className={styles.thNum}>Successful</th>
                  <th className={styles.thNum}>Failed</th>
                  <th>Sources</th>
                  <th>First Call</th>
                  <th>Last Call</th>
                  <th className={styles.thChev}></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((r) => (
                  <tr
                    key={r.request_id}
                    className={styles.clickableRow}
                    onClick={() => onRowClick(r)}
                    title={`View LLM calls for ${r.request_id}`}
                  >
                    <td><span className={styles.idChip}>{r.request_id}</span></td>
                    <td className={styles.tdNum}>{r.total_llm_calls ?? 0}</td>
                    <td className={styles.tdNum}><Badge value={r.successful_calls} variant="Success" /></td>
                    <td className={styles.tdNum}><Badge value={r.failed_calls} variant="Danger" /></td>
                    <td><span className={styles.sourcesText} title={r.request_sources || ""}>{r.request_sources || "—"}</span></td>
                    <td className={styles.tdDate}>{formatDate(r.first_call)}</td>
                    <td className={styles.tdDate}>{formatDate(r.last_call)}</td>
                    <td className={styles.tdChev}><SVGIcons icon="chevron-right" width={14} height={14} stroke="var(--content-color)" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Level 4 — LLM Call Cards
// ═══════════════════════════════════════════════════════════════════════════════
function CallsView({ data, onBack }) {
  const successful = data.filter((c) => c.status === "success").length;
  const failed = data.filter((c) => c.status !== "success").length;
  const totalTokens = data.reduce((s, c) => s + (c.total_tokens || 0), 0);

  return (
    <div className={styles.callsView}>
      {/* Fixed top section: stat strip + back button */}
      <div className={styles.callsViewTop}>
        <StatStrip stats={[
          { label: "Total LLM Calls", value: data.length },
          { label: "Successful", value: successful, variant: "success" },
          { label: "Failed", value: failed, variant: "danger" },
          { label: "Total Tokens", value: totalTokens.toLocaleString() },
        ]} />
        {onBack && (
          <div className={styles.callsBackRow}>
            <button className={styles.backBtn} onClick={onBack} title="Back to Requests">
              <SVGIcons icon="chevron-left" width={14} height={14} stroke="currentColor" />
            </button>
          </div>
        )}
      </div>

      {/* Scrollable cards list */}
      <div className={styles.callsContainer}>
        {data.length === 0 ? (
          <EmptyState
            message="No LLM calls found for this request"
            showCreateButton={false}
            showClearFilter={false}
          />
        ) : (
          data.map((call, idx) => (
            <CallCard key={call.llm_call_id || idx} call={call} index={idx + 1} />
          ))
        )}
      </div>
    </div>
  );
}

function CallCard({ call, index }) {
  const isFailed = call.status !== "success";
  const [isExpanded, setIsExpanded] = useState(false);

  return (
    <div
      className={`${styles.callCard} ${isFailed ? styles.callCardFailed : styles.callCardSuccess}`}
    >
      {/* Header bar — click to expand/collapse */}
      <div
        className={`${styles.callCardHeader} ${styles.callCardHeaderClickable}`}
        onClick={() => setIsExpanded((prev) => !prev)}
      >
        <div className={styles.callCardLeft}>
          <span className={styles.callIndex}>Call #{index}</span>
          <code className={styles.callIdCode} title={call.llm_call_id}>{call.llm_call_id}</code>
          <span className={`${styles.statusPill} ${isFailed ? styles.statusPillFailed : styles.statusPillSuccess}`}>
            {isFailed ? "Failed" : "Success"}
          </span>
        </div>
        <div className={styles.callCardRight}>
          <span className={styles.callTimestamp}>{formatDate(call.request_timestamp)}</span>
          <span className={`${styles.expandChevron} ${isExpanded ? styles.expandChevronOpen : ""}`}>
            <SVGIcons icon="chevron-down" width={14} height={14} stroke="var(--content-color)" />
          </span>
        </div>
      </div>

      {/* Token summary row — always visible */}
      <div className={styles.tokenRow}>
        {[
          { label: "Input Tokens", value: call.input_tokens },
          { label: "Output Tokens", value: call.output_tokens },
          { label: "Total Tokens", value: call.total_tokens },
        ].map((t) => (
          <div key={t.label} className={styles.tokenCell}>
            <span className={styles.tokenValue}>{(t.value ?? 0).toLocaleString()}</span>
            <span className={styles.tokenLabel}>{t.label}</span>
          </div>
        ))}
      </div>

      {/* Expandable detail section — combined class activates open state */}
      <div className={`${styles.callDetailsExpandable}${isExpanded ? ` ${styles.callDetailsExpandableOpen}` : ""}`}>
        <div className={styles.callDetails}>
          <KVRow label="Request ID" value={call.request_id} mono />
          <KVRow label="LLM Call ID" value={call.llm_call_id} mono />
          <KVRow label="User ID" value={call.user_id ?? "—"} />
          <KVRow label="Session ID" value={call.session_id ?? "—"} />
          <KVRow label="Model Name" value={call.model_name ?? "—"} bold />
          <KVRow label="Request Source" value={call.request_source ?? "—"} />
          <KVRow label="Agent ID" value={call.agent_id ?? "—"} mono={!!call.agent_id} />
          <KVRow label="Agent Name" value={call.agent_name ?? "—"} />
          <KVRow label="Input Tokens" value={(call.input_tokens ?? 0).toLocaleString()} />
          <KVRow label="Output Tokens" value={(call.output_tokens ?? 0).toLocaleString()} />
          <KVRow label="Total Tokens" value={(call.total_tokens ?? 0).toLocaleString()} />
          <KVRow label="Duration" value={`${call.duration_ms ?? 0} ms`} />
          <KVRow label="Request Timestamp" value={formatDate(call.request_timestamp)} />
          <KVRow label="Response Timestamp" value={formatDate(call.response_timestamp)} />
          <div className={styles.kvRow}>
            <span className={styles.kvLabel}>Request Context</span>
            <pre className={styles.codeBlock}>
              {call.request_context && call.request_context !== "{}"
                ? JSON.stringify(safeParseJson(call.request_context), null, 2)
                : "—"}
            </pre>
          </div>
          {isFailed && (
            <>
              <KVRow label="Error Message" value={call.error_message ?? "—"} error />
              <KVRow label="Error Type" value={call.error_type ?? "—"} />
              {call.stack_trace ? (
                <div className={styles.kvRow}>
                  <span className={styles.kvLabel}>Stack Trace</span>
                  <pre className={styles.stackBlock}>{call.stack_trace}</pre>
                </div>
              ) : (
                <KVRow label="Stack Trace" value="—" />
              )}
            </>
          )}
          {call.retry_count > 0 && <KVRow label="Retry Count" value={call.retry_count} />}
        </div>
      </div>
    </div>
  );
}

function KVRow({ label, value, mono, bold, error }) {
  const [copied, setCopied] = useState(false);
  if (value === null || value === undefined) return null;

  const handleCopy = () => {
    navigator.clipboard
      .writeText(String(value))
      .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1500); })
      .catch(() => {});
  };

  return (
    <div className={styles.kvRow}>
      <span className={styles.kvLabel}>{label}</span>
      <div className={styles.kvValueWrap}>
        <span
          className={[
            styles.kvValue,
            mono ? styles.kvMono : "",
            bold ? styles.kvBold : "",
            error ? styles.kvError : "",
          ].filter(Boolean).join(" ")}
        >
          {String(value)}
        </span>
        {mono && (
          <button
            type="button"
            className={styles.kvCopyBtn}
            onClick={handleCopy}
            title={copied ? "Copied!" : "Copy to clipboard"}
          >
            <SVGIcons
              icon={copied ? "clipboard-check" : "copy"}
              width={12}
              height={12}
              fill={copied ? "var(--accent-color)" : "var(--content-color)"}
            />
          </button>
        )}
      </div>
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main LLMTracker
// ═══════════════════════════════════════════════════════════════════════════════
export default function LLMTracker() {
  const { getUsers, getSessions, getRequests, getLlmCalls } = useLlmTrackerService();

  // ── Role context ──────────────────────────────────────────────────────────
  // Matches NavBar pattern: useAuth() is primary source, getRoleFromToken() is fallback.
  // useAuth() covers the MSAL path and any in-session role changes;
  // getRoleFromToken() covers fresh JWT reads and non-context callers.
  const { role: authRole } = useAuth();
  const role = (authRole || getRoleFromToken() || "").toUpperCase();
  const currentUserEmail = getEmailFromToken();
  const isUserOrDev = role === "USER" || role === "DEVELOPER";
  const isSuperAdmin = role === "SUPERADMIN";

  // Scope label shown in the role badge
  const scopeLabel = isSuperAdmin
    ? "All Departments"
    : isUserOrDev
    ? "My Data"
    : "My Department";

  const [level, setLevel] = useState(isUserOrDev ? LEVEL.SESSIONS : LEVEL.USERS);
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("");

  const [selectedUser, setSelectedUser] = useState(isUserOrDev ? currentUserEmail : null);
  const [selectedSession, setSelectedSession] = useState(null);
  const [selectedRequest, setSelectedRequest] = useState(null);

  // In-memory cache via ref — always holds the latest entries regardless of render cycle
  const cacheRef = useRef({});
  // Track the HTTP status of the last error for 403/401 differentiation
  const [errorStatus, setErrorStatus] = useState(null);

  // Generic data loader — accepts a service thunk (() => serviceMethod(params)) + cache key.
  // Errors are caught here so the component shows inline banners instead of global toasts.
  const load = useCallback(
    async (fetcher, cacheKey) => {
      if (cacheRef.current[cacheKey]) {
        setData(cacheRef.current[cacheKey]);
        setError(null);
        setErrorStatus(null);
        return;
      }
      setLoading(true);
      setError(null);
      setErrorStatus(null);
      try {
        const result = await fetcher();
        const arr = Array.isArray(result) ? result : [];
        cacheRef.current[cacheKey] = arr;
        setData(arr);
      } catch (err) {
        const status = err?.response?.status;
        setErrorStatus(status || null);
        if (status === 403) {
          setError("You don't have permission to view this data.");
        } else if (status === 401) {
          setError("Authentication required. Please log in again.");
        } else {
          setError(
            err?.response?.data?.detail ||
              err?.response?.data?.message ||
              err?.message ||
              "Failed to load data. Please try again."
          );
        }
        setData([]);
      } finally {
        setLoading(false);
      }
    },
    [] // setState setters are stable; fetchers are passed at call-time
  );

  // Load on mount — User/Dev skip the user list and go straight to their own sessions
  useEffect(() => {
    if (isUserOrDev && currentUserEmail) {
      setSelectedUser(currentUserEmail);
      setLevel(LEVEL.SESSIONS);
      load(() => getSessions(currentUserEmail), `sessions:${currentUserEmail}`);
    } else {
      load(() => getUsers(), "users");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // ── Navigation ────────────────────────────────────────────────────────────
  const goToUsers = useCallback(() => {
    setLevel(LEVEL.USERS);
    setSelectedUser(null);
    setSelectedSession(null);
    setSelectedRequest(null);
    setFilter("");
    // User/Dev can still navigate to Level 1 via breadcrumb (shows their single entry)
    load(() => getUsers(), "users");
  }, [load, getUsers]);

  const goToSessions = useCallback(
    (userId) => {
      setSelectedUser(userId);
      setSelectedSession(null);
      setSelectedRequest(null);
      setLevel(LEVEL.SESSIONS);
      setFilter("");
      load(() => getSessions(userId), `sessions:${userId}`);
    },
    [load, getSessions]
  );

  const goToRequests = useCallback(
    (sessionId) => {
      setSelectedSession(sessionId);
      setSelectedRequest(null);
      setLevel(LEVEL.REQUESTS);
      setFilter("");
      load(
        () => getRequests(sessionId, selectedUser),
        `requests:${sessionId}:${selectedUser}`
      );
    },
    [load, getRequests, selectedUser]
  );

  const goToCalls = useCallback(
    (requestId) => {
      setSelectedRequest(requestId);
      setLevel(LEVEL.CALLS);
      setFilter("");
      load(
        () => getLlmCalls(requestId, selectedUser, selectedSession),
        `calls:${requestId}:${selectedUser}:${selectedSession}`
      );
    },
    [load, getLlmCalls, selectedUser, selectedSession]
  );

  const handleRefresh = useCallback(() => {
    const [cacheKey, fetcher] =
      level === LEVEL.USERS
        ? ["users", () => getUsers()]
        : level === LEVEL.SESSIONS
        ? [`sessions:${selectedUser}`, () => getSessions(selectedUser)]
        : level === LEVEL.REQUESTS
        ? [
            `requests:${selectedSession}:${selectedUser}`,
            () => getRequests(selectedSession, selectedUser),
          ]
        : [
            `calls:${selectedRequest}:${selectedUser}:${selectedSession}`,
            () => getLlmCalls(selectedRequest, selectedUser, selectedSession),
          ];
    // Bust the cache entry so load() re-fetches fresh data
    delete cacheRef.current[cacheKey];
    load(fetcher, cacheKey);
  }, [level, selectedUser, selectedSession, selectedRequest, load, getUsers, getSessions, getRequests, getLlmCalls]);

  // ── SubHeader breadcrumb items ────────────────────────────────────────────
  const breadcrumbItems = level === LEVEL.USERS
    ? null
    : [
        { label: "All Users", onClick: goToUsers },
        level >= LEVEL.SESSIONS && {
          label: truncateId(selectedUser),
          onClick: level > LEVEL.SESSIONS ? () => goToSessions(selectedUser) : undefined,
        },
        level >= LEVEL.REQUESTS && {
          label: truncateId(selectedSession),
          onClick: level > LEVEL.REQUESTS ? () => goToRequests(selectedSession) : undefined,
        },
        level >= LEVEL.CALLS && { label: truncateId(selectedRequest) },
      ].filter(Boolean);

  // Role context badge shown in SubHeader left content slot
  const roleBadge = (
    <span className={`${styles.roleBadge} ${isSuperAdmin ? styles.roleBadgeSuperAdmin : isUserOrDev ? styles.roleBadgeUser : styles.roleBadgeAdmin}`}>
      <SVGIcons icon={isSuperAdmin ? "layout-grid" : isUserOrDev ? "fa-user" : "person-circle"} width={12} height={12} fill="currentColor" />
      {scopeLabel}
    </span>
  );

  return (
    <div className="pageContainer">
      <SubHeader
        heading="LLM Tracker"
        breadcrumbItems={breadcrumbItems}
        breadcrumbSeparator="chevron"
        showSearch={level !== LEVEL.CALLS}
        searchValue={filter}
        onSearch={(val) => setFilter(val || "")}
        clearSearch={() => setFilter("")}
        showPlusButton={false}
        showRefreshButton
        handleRefresh={handleRefresh}
      />

      <PageLayout>
        <div className={`listWrapper ${styles.listWrapper}`}>
          {loading ? (
            <Loader />
          ) : error ? (
            <div className={styles.errorWrap}>
              <ErrorBanner message={error} status={errorStatus} />
            </div>
          ) : (
            <>
              {level === LEVEL.USERS && (
                <UsersTable data={data} filter={filter} onRowClick={(u) => goToSessions(u.user_id)} />
              )}
              {level === LEVEL.SESSIONS && (
                <SessionsTable data={data} filter={filter} onRowClick={(s) => goToRequests(s.session_id)} onBack={goToUsers} />
              )}
              {level === LEVEL.REQUESTS && (
                <RequestsTable data={data} filter={filter} onRowClick={(r) => goToCalls(r.request_id)} onBack={() => goToSessions(selectedUser)} />
              )}
              {level === LEVEL.CALLS && <CallsView data={data} onBack={() => goToRequests(selectedSession)} />}
            </>
          )}
        </div>
      </PageLayout>
    </div>
  );
}
