import React, { useState, useCallback, useRef, useEffect, useMemo, useLayoutEffect } from "react";
import { createPortal } from "react-dom";
import { SUBHEADER_CUSTOM_ACTIONS_ID } from "../commonComponents/SubHeader";
import {
  BarChart,
  Bar,
  Line,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
  ComposedChart,
} from "recharts";
import { APIs } from "../../constant";
import useFetch, { axiosInstance } from "../../Hooks/useAxios";
import { useMessage } from "../../Hooks/MessageContext";
import { useTheme } from "../../Hooks/ThemeContext";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import { extractErrorMessage } from "../../utils/errorUtils";
import styles from "./TokenUsageTracking.module.css";

const CHART_COLORS = [
  "#3b82f6", "#14b8a6", "#f59e0b", "#8b5cf6", "#ec4899",
  "#06b6d4", "#f97316", "#84cc16", "#6366f1", "#ef4444",
];

const EMPTY_FILTERS = {
  agent_id: "",
  model: "",
  status: "",
  session_id: "",
  user_id: "",
  department_name: "",
  date_from: "",
  date_to: "",
};

const XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

const formatApiDetail = (detail) => {
  if (!detail) return null;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => (typeof item === "object" && item?.msg ? item.msg : String(item)))
      .join("; ");
  }
  if (typeof detail === "object" && detail.msg) return detail.msg;
  return String(detail);
};

const parseApiErrorPayload = (payload) => {
  if (!payload || typeof payload !== "object") return null;
  return formatApiDetail(payload.detail) || payload.message || payload.error || null;
};

const resolveDownloadErrorMessage = async (error) => {
  const data = error?.response?.data;

  if (data instanceof Blob) {
    try {
      const text = (await data.text()).trim();
      if (text.startsWith("{") || text.startsWith("[")) {
        return parseApiErrorPayload(JSON.parse(text)) || text;
      }
      return text || null;
    } catch (_) {
      /* fall through */
    }
  }

  if (typeof data === "string") {
    const trimmed = data.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try {
        return parseApiErrorPayload(JSON.parse(trimmed)) || trimmed;
      } catch (_) {
        return trimmed;
      }
    }
    return trimmed || null;
  }

  const fromObject = parseApiErrorPayload(data);
  if (fromObject) return fromObject;

  if (typeof error?.message === "string" && error.message && !/^Request failed with status code/i.test(error.message)) {
    return error.message;
  }

  const { message } = extractErrorMessage(error);
  if (message && !/^Request failed with status code/i.test(message)) {
    return message;
  }

  return "Failed to download report";
};

const toRelativeApiPath = (url) => {
  if (!url) return "";
  if (/^https?:\/\//i.test(url)) {
    try {
      const parsed = new URL(url);
      return `${parsed.pathname}${parsed.search}`;
    } catch {
      return url;
    }
  }
  return url.startsWith("/") ? url : `/${url}`;
};

const getFilenameFromDisposition = (disposition) => {
  if (!disposition) return null;
  const match = /filename\*?=(?:UTF-8''|")?([^";\n]+)/i.exec(disposition);
  if (!match?.[1]) return null;
  try {
    return decodeURIComponent(match[1].replace(/"/g, "").trim());
  } catch {
    return match[1].replace(/"/g, "").trim();
  }
};

const normalizeFilterOptions = (response) => ({
  departments: response?.departments || [],
  agents: response?.agents || [],
  users: response?.users || [],
  models: response?.models || [],
  statuses: response?.statuses || [],
  sessions: response?.sessions || [],
});

const formatCurrency = (val) => {
  const num = Number(val) || 0;
  const abs = Math.abs(num);
  if (abs === 0) return "$0.00";
  if (abs >= 1) {
    return `$${num.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  }
  if (abs >= 0.01) return `$${num.toFixed(4)}`;
  return `$${num.toFixed(6)}`;
};

const formatChartDate = (dateStr) => {
  if (!dateStr) return "";
  try {
    const d = new Date(`${dateStr}T00:00:00`);
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return dateStr;
  }
};

const isKnownAgentName = (name) =>
  String(name || "").trim().toLowerCase() !== "unknown";

const formatNumber = (val) => {
  const num = Number(val) || 0;
  return num.toLocaleString();
};

const formatDecimal = (val, places = 2) => {
  const num = Number(val) || 0;
  return num.toFixed(places);
};

const formatDateTime = (dateStr) => {
  if (!dateStr) return "";
  try {
    return new Date(dateStr).toLocaleString();
  } catch {
    return dateStr;
  }
};

const buildQueryString = (filters) => {
  const params = [];
  Object.entries(filters).forEach(([key, value]) => {
    if (value && String(value).trim()) {
      params.push(`${key}=${encodeURIComponent(String(value).trim())}`);
    }
  });
  return params.length > 0 ? `?${params.join("&")}` : "";
};

const getChartTheme = () => {
  if (typeof window === "undefined") {
    return { cardBg: "#fff", border: "#e2e8f0", text: "#374151", muted: "#64748b", grid: "#e2e8f0" };
  }
  const root = getComputedStyle(document.documentElement);
  return {
    cardBg: root.getPropertyValue("--card-bg")?.trim() || "#fff",
    border: root.getPropertyValue("--border")?.trim() || "#e2e8f0",
    text: root.getPropertyValue("--text-primary")?.trim() || "#374151",
    muted: root.getPropertyValue("--muted")?.trim() || "#64748b",
    grid: root.getPropertyValue("--border-color")?.trim() || "#e2e8f0",
  };
};

const ALL_OPTION = "All";

const SUMMARY_FIELDS = [
  { key: "total_queries", label: "Total Queries", format: "number" },
  { key: "total_query_cost", label: "Total Query Cost", format: "currency" },
  { key: "total_tokens", label: "Total Tokens", format: "number" },
  { key: "unique_users", label: "Unique Users", format: "number" },
  { key: "total_llm_calls", label: "Total LLM Calls", format: "number" },
  { key: "total_cost", label: "Total Cost", format: "currency" },
  { key: "unique_agents", label: "Unique Agents", format: "number" },
  { key: "avg_llm_calls_per_query", label: "Avg LLM Calls/Query", format: "decimal" },
  { key: "avg_cost_per_query", label: "Avg Cost/Query", format: "currency" },
];

const formatSummaryValue = (value, format) => {
  if (format === "currency") return formatCurrency(value);
  if (format === "decimal") return formatDecimal(value);
  return formatNumber(value);
};

const TokenUsageFilterDropdown = ({
  label,
  options,
  selected,
  onSelect,
  showSearch = false,
}) => (
  <div className={styles.filterDropdownField}>
    <NewCommonDropdown
      label={label}
      labelPosition="top"
      options={[ALL_OPTION, ...options.filter((opt) => opt !== ALL_OPTION)]}
      selected={selected || ALL_OPTION}
      onSelect={(value) => onSelect(value === ALL_OPTION ? "" : value)}
      placeholder={ALL_OPTION}
      showSearch={showSearch}
      width="100%"
      listZIndex={1000070}
    />
  </div>
);

const StatCard = ({ label, value }) => (
  <div className={styles.statCard}>
    <span className={styles.statLabel}>{label}</span>
    <span className={styles.statValue}>{value}</span>
  </div>
);

const ChartEmpty = ({ message }) => (
  <div className={styles.chartEmpty}>
    <SVGIcons icon="fa-chart-bar" width={28} height={28} color="var(--text-secondary, #94a3b8)" />
    <span>{message}</span>
  </div>
);

const DataTable = ({
  title,
  subtitle,
  headers,
  rows,
  renderRow,
  emptyMessage = "No data",
  scrollable = false,
  fullWidth = false,
  numericColumns = [],
}) => (
  <div className={`${styles.panelCard} ${fullWidth ? styles.panelCardFull : ""}`}>
    <div className={styles.panelHeader}>
      <h3 className={styles.panelTitle}>{title}</h3>
      {subtitle && <p className={styles.panelSubtitle}>{subtitle}</p>}
    </div>
    <div className={`${styles.tableWrap} ${scrollable ? styles.tableScrollable : ""}`}>
      <table className={styles.dataTable}>
        <thead>
          <tr>
            {headers.map((h, i) => (
              <th
                key={h}
                className={numericColumns.includes(i) ? styles.numHeader : undefined}
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={headers.length} className={styles.tableEmpty}>
                {emptyMessage}
              </td>
            </tr>
          ) : (
            rows.map((row, i) => renderRow(row, i))
          )}
        </tbody>
      </table>
    </div>
  </div>
);

const TokenUsageTracking = ({ onDownloadClickRef, onDownloadingChange }) => {
  const [filters, setFilters] = useState({ ...EMPTY_FILTERS });
  const [stagedFilters, setStagedFilters] = useState({ ...EMPTY_FILTERS });
  const [filterOpen, setFilterOpen] = useState(false);
  const [dropdownStyle, setDropdownStyle] = useState({});
  const buttonRef = useRef(null);
  const dropdownRef = useRef(null);
  const fetchDataRef = useRef(null);
  const addMessageRef = useRef(null);
  const filterOptionsCacheRef = useRef(null);
  const filterOptionsRequestRef = useRef(null);
  const dashboardDataCacheRef = useRef(new Map());
  const dashboardRequestRef = useRef(new Map());
  const [filterOptions, setFilterOptions] = useState({
    departments: [],
    agents: [],
    users: [],
    models: [],
    statuses: [],
    sessions: [],
  });
  const [dashboardData, setDashboardData] = useState(null);
  const [loadingFilters, setLoadingFilters] = useState(true);
  const [loadingData, setLoadingData] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [chartTheme, setChartTheme] = useState(getChartTheme);
  const [actionsSlot, setActionsSlot] = useState(null);

  const { fetchData } = useFetch();
  const { addMessage } = useMessage();
  const { theme } = useTheme();

  fetchDataRef.current = fetchData;
  addMessageRef.current = addMessage;

  const showUserFilter = filterOptions.users?.length > 0;
  const showDepartmentFilter = filterOptions.departments?.length > 0;

  const activeFilterCount = Object.values(filters).filter((v) => v && String(v).trim()).length;

  useLayoutEffect(() => {
    const resolveSlot = () => document.getElementById(SUBHEADER_CUSTOM_ACTIONS_ID);
    const slot = resolveSlot();
    if (slot) {
      setActionsSlot(slot);
      return undefined;
    }
    const frameId = requestAnimationFrame(() => {
      const retry = resolveSlot();
      if (retry) setActionsSlot(retry);
    });
    return () => cancelAnimationFrame(frameId);
  }, []);

  useEffect(() => {
    if (filterOpen && buttonRef.current) {
      requestAnimationFrame(() => {
        if (!buttonRef.current) return;
        const rect = buttonRef.current.getBoundingClientRect();
        const panelWidth = 320;
        const GAP = 8;
        const EDGE = 16;
        const windowWidth = window.innerWidth;
        const windowHeight = window.innerHeight;

        let left = rect.right - panelWidth;
        if (left < EDGE) left = EDGE;
        if (left + panelWidth > windowWidth - EDGE) {
          left = windowWidth - panelWidth - EDGE;
        }

        const spaceBelow = windowHeight - rect.bottom - EDGE;
        const spaceAbove = rect.top - EDGE;
        let top;
        let maxHeight;

        if (spaceBelow >= 350 || spaceBelow >= spaceAbove) {
          top = rect.bottom + GAP;
          maxHeight = windowHeight - top - EDGE;
        } else {
          maxHeight = spaceAbove - GAP;
          top = rect.top - GAP - Math.min(maxHeight, 520);
          if (top < EDGE) top = EDGE;
          maxHeight = rect.top - top - GAP;
        }

        setDropdownStyle({
          position: "fixed",
          left: `${Math.round(left)}px`,
          top: `${Math.round(top)}px`,
          maxHeight: `${Math.round(Math.min(maxHeight, 520))}px`,
          zIndex: 1000060,
        });
      });
    }
  }, [filterOpen]);

  useEffect(() => {
    if (!filterOpen) return;
    const handleClickOutside = (e) => {
      if (e.target.closest('[data-common-dropdown-portal="true"]')) return;
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target) &&
        buttonRef.current &&
        !buttonRef.current.contains(e.target)
      ) {
        setFilterOpen(false);
        setStagedFilters({ ...filters });
      }
    };
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [filterOpen, filters]);

  useEffect(() => {
    setChartTheme(getChartTheme());
  }, [theme]);

  const loadFilterOptions = useCallback(async () => {
    if (filterOptionsCacheRef.current) {
      return filterOptionsCacheRef.current;
    }
    if (filterOptionsRequestRef.current) {
      return filterOptionsRequestRef.current;
    }

    const request = fetchDataRef.current(APIs.TOKEN_USAGE_FILTER_OPTIONS)
      .then((response) => {
        const normalized = normalizeFilterOptions(response);
        filterOptionsCacheRef.current = normalized;
        return normalized;
      })
      .catch((err) => {
        filterOptionsRequestRef.current = null;
        throw err;
      })
      .finally(() => {
        filterOptionsRequestRef.current = null;
      });

    filterOptionsRequestRef.current = request;
    return request;
  }, []);

  const loadDashboardData = useCallback(async (activeFilters = EMPTY_FILTERS) => {
    const queryString = buildQueryString(activeFilters);
    const cacheKey = queryString || "__default__";

    if (dashboardDataCacheRef.current.has(cacheKey)) {
      return dashboardDataCacheRef.current.get(cacheKey);
    }
    if (dashboardRequestRef.current.has(cacheKey)) {
      return dashboardRequestRef.current.get(cacheKey);
    }

    const request = fetchDataRef.current(`${APIs.TOKEN_USAGE_DASHBOARD}${queryString}`)
      .then((response) => {
        const data = response || null;
        dashboardDataCacheRef.current.set(cacheKey, data);
        return data;
      })
      .catch((err) => {
        dashboardRequestRef.current.delete(cacheKey);
        throw err;
      })
      .finally(() => {
        dashboardRequestRef.current.delete(cacheKey);
      });

    dashboardRequestRef.current.set(cacheKey, request);
    return request;
  }, []);

  const fetchDashboardData = useCallback(async (overrideFilters) => {
    const activeFilters = overrideFilters ?? filters;
    setLoadingData(true);
    try {
      const response = await loadDashboardData(activeFilters);
      setDashboardData(response);
    } catch {
      addMessage("Failed to load token usage data", "error");
      setDashboardData(null);
    } finally {
      setLoadingData(false);
    }
  }, [filters, loadDashboardData, addMessage]);

  useEffect(() => {
    let cancelled = false;

    const init = async () => {
      setLoadingFilters(true);
      try {
        const options = await loadFilterOptions();
        if (!cancelled && options) {
          setFilterOptions(options);
        }
      } catch {
        if (!cancelled) {
          addMessageRef.current("Failed to load filter options", "error");
        }
      } finally {
        if (!cancelled) {
          setLoadingFilters(false);
        }
      }

      if (cancelled) return;

      setLoadingData(true);
      try {
        const response = await loadDashboardData(EMPTY_FILTERS);
        if (!cancelled) {
          setDashboardData(response);
        }
      } catch {
        if (!cancelled) {
          addMessageRef.current("Failed to load token usage data", "error");
          setDashboardData(null);
        }
      } finally {
        if (!cancelled) {
          setLoadingData(false);
        }
      }
    };

    init();
    return () => {
      cancelled = true;
    };
  }, [loadFilterOptions, loadDashboardData]);

  const handleStagedChange = (field, value) => {
    setStagedFilters((prev) => ({ ...prev, [field]: value }));
  };

  const handleApply = () => {
    setFilters({ ...stagedFilters });
    setFilterOpen(false);
    fetchDashboardData(stagedFilters);
  };

  const handleClearFilters = () => {
    const empty = { ...EMPTY_FILTERS };
    setStagedFilters(empty);
    setFilters(empty);
    setFilterOpen(false);
    fetchDashboardData(empty);
  };

  const handleDownloadReport = useCallback(async () => {
    setDownloading(true);
    try {
      const queryString = buildQueryString(filters);
      const reportMeta = await fetchData(
        `${APIs.TOKEN_USAGE_DOWNLOAD_REPORT}${queryString}`,
        { silent: true },
      );

      const apiDetail = formatApiDetail(reportMeta?.detail);
      if (apiDetail && !reportMeta?.download_url) {
        addMessage(apiDetail, "error");
        return;
      }

      if (!reportMeta?.download_url) {
        addMessage("No download URL returned", "error");
        return;
      }

      let filePath = toRelativeApiPath(reportMeta.download_url);
      let fileName = reportMeta.filename || "token_usage_report.xlsx";

      const fetchReportBlob = async (path, fallbackName = fileName) => {
        let fileResponse;
        try {
          fileResponse = await axiosInstance.get(path, { responseType: "blob" });
        } catch (err) {
          const message = await resolveDownloadErrorMessage(err);
          throw new Error(message);
        }
        const contentType = fileResponse.headers?.["content-type"] || "";

        if (contentType.includes("application/json")) {
          const text = await fileResponse.data.text();
          let json;
          try {
            json = JSON.parse(text);
          } catch {
            throw new Error("Failed to download report");
          }
          if (json.download_url) {
            return fetchReportBlob(
              toRelativeApiPath(json.download_url),
              json.filename || fallbackName,
            );
          }
          throw new Error(json.detail || json.message || "Failed to download report");
        }

        return { fileResponse, fileName: fallbackName };
      };

      const { fileResponse, fileName: resolvedName } = await fetchReportBlob(filePath);
      const contentType = fileResponse.headers?.["content-type"] || "";
      const dispositionName = getFilenameFromDisposition(fileResponse.headers?.["content-disposition"]);
      const blob = new Blob([fileResponse.data], {
        type: contentType.includes("spreadsheet") || contentType.includes("excel") ? contentType : XLSX_MIME,
      });
      const url = window.URL.createObjectURL(blob);
      const downloadedFileName = dispositionName || resolvedName;
      const a = document.createElement("a");
      a.href = url;
      a.download = downloadedFileName;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      a.remove();
      addMessage(`Report downloaded successfully: ${downloadedFileName}`, "success");
    } catch (error) {
      const message = await resolveDownloadErrorMessage(error);
      addMessage(message, "error");
    } finally {
      setDownloading(false);
    }
  }, [filters, fetchData, addMessage]);

  useEffect(() => {
    if (onDownloadClickRef) {
      onDownloadClickRef.current = handleDownloadReport;
    }
  }, [onDownloadClickRef, handleDownloadReport]);

  useEffect(() => {
    onDownloadingChange?.(downloading);
  }, [downloading, onDownloadingChange]);

  const summary = dashboardData?.summary;
  const isEmpty = summary && Number(summary.total_queries) === 0;

  const knownAgentCostOverTime = useMemo(
    () => (dashboardData?.cost_over_time_by_agent || []).filter((r) => isKnownAgentName(r.agent_name)),
    [dashboardData?.cost_over_time_by_agent],
  );

  const { agentCostChartData, agentChartSeries } = useMemo(() => {
    const totalsByAgent = {};
    knownAgentCostOverTime.forEach(({ agent_name, cost }) => {
      totalsByAgent[agent_name] = (totalsByAgent[agent_name] || 0) + (Number(cost) || 0);
    });

    const series = Object.entries(totalsByAgent)
      .sort((a, b) => b[1] - a[1])
      .map(([name]) => name);

    const byDate = {};
    knownAgentCostOverTime.forEach(({ date, agent_name, cost }) => {
      if (!byDate[date]) byDate[date] = { date };
      byDate[date][agent_name] = (byDate[date][agent_name] || 0) + (Number(cost) || 0);
    });

    return {
      agentCostChartData: Object.values(byDate).sort((a, b) => a.date.localeCompare(b.date)),
      agentChartSeries: series,
    };
  }, [knownAgentCostOverTime]);

  const modelBarData = useMemo(
    () =>
      (dashboardData?.model_breakdown || []).map((m) => ({
        model: m.model,
        cost: Number(m.cost) || 0,
        calls: Number(m.calls) || 0,
        tokens: Number(m.tokens) || 0,
      })),
    [dashboardData?.model_breakdown]
  );

  const dailyTrendData = useMemo(
    () =>
      (dashboardData?.daily_trend || []).map((d) => ({
        ...d,
        dateLabel: formatChartDate(d.date),
      })),
    [dashboardData?.daily_trend]
  );

  const activeFilterChips = useMemo(() => {
    const chips = [];
    if (filters.agent_id) {
      const agent = filterOptions.agents.find((a) => a.agent_id === filters.agent_id);
      if (agent) chips.push(`Agent: ${agent.agent_name}`);
    }
    if (filters.model) chips.push(`Model: ${filters.model}`);
    if (filters.status) chips.push(`Status: ${filters.status}`);
    if (filters.session_id) chips.push(`Session: ${filters.session_id}`);
    if (filters.user_id) chips.push(`User: ${filters.user_id}`);
    if (filters.department_name) chips.push(`Dept: ${filters.department_name}`);
    if (filters.date_from) chips.push(`From: ${filters.date_from}`);
    if (filters.date_to) chips.push(`To: ${filters.date_to}`);
    return chips;
  }, [filters, filterOptions]);

  const agentNameOptions = useMemo(
    () => filterOptions.agents.map((a) => a.agent_name),
    [filterOptions.agents]
  );

  const selectedAgentName = useMemo(() => {
    if (!stagedFilters.agent_id) return ALL_OPTION;
    return filterOptions.agents.find((a) => a.agent_id === stagedFilters.agent_id)?.agent_name || ALL_OPTION;
  }, [stagedFilters.agent_id, filterOptions.agents]);

  const DailyTrendTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const d = payload[0]?.payload;
    return (
      <div className={styles.chartTooltip}>
        <div className={styles.chartTooltipTitle}>{label}</div>
        <div>Queries: <strong>{formatNumber(d?.queries)}</strong></div>
        <div>Tokens: <strong>{formatNumber(d?.tokens)}</strong></div>
        <div>Cost: <strong>{formatCurrency(d?.cost)}</strong></div>
      </div>
    );
  };

  const AgentCostTooltip = ({ active, payload, label }) => {
    if (!active || !payload?.length) return null;
    const entries = [...payload]
      .filter((entry) => Number(entry.value) > 0)
      .sort((a, b) => (Number(b.value) || 0) - (Number(a.value) || 0));

    return (
      <div className={styles.chartTooltip}>
        <div className={styles.chartTooltipTitle}>{formatChartDate(label)}</div>
        {entries.map((entry) => (
          <div key={entry.dataKey}>
            {entry.name}: <strong>{formatCurrency(entry.value)}</strong>
          </div>
        ))}
      </div>
    );
  };


  if (loadingFilters) {
    return (
      <>
        {actionsSlot && createPortal(
          <div className={styles.headerActions}>
            <div className={styles.filterContainer}>
              <button
                type="button"
                className={styles.filterButton}
                disabled
                aria-label="Open filters"
              >
                <SVGIcons icon="funnel" width={16} height={16} color="var(--content-color)" />
              </button>
            </div>
          </div>,
          actionsSlot
        )}
        <div className={styles.container}>
          <div className={styles.loadingOverlay}>
            <Loader />
          </div>
        </div>
      </>
    );
  }

  const filterDropdown = (
    <div ref={dropdownRef} className={styles.dropdownPanel} style={dropdownStyle}>
      <div className={styles.dropdownScrollable}>
        <div className={styles.dropdownSection}>
          <div className={styles.dropdownSectionHeader}>Filters</div>
          <TokenUsageFilterDropdown
            label="Agent"
            options={agentNameOptions}
            selected={selectedAgentName}
            onSelect={(agentName) => {
              if (!agentName) {
                handleStagedChange("agent_id", "");
                return;
              }
              const agent = filterOptions.agents.find((a) => a.agent_name === agentName);
              handleStagedChange("agent_id", agent?.agent_id || "");
            }}
            showSearch
          />
          <TokenUsageFilterDropdown
            label="Model"
            options={filterOptions.models}
            selected={stagedFilters.model}
            onSelect={(value) => handleStagedChange("model", value)}
          />
          <TokenUsageFilterDropdown
            label="Status"
            options={filterOptions.statuses}
            selected={stagedFilters.status}
            onSelect={(value) => handleStagedChange("status", value)}
          />
          <TokenUsageFilterDropdown
            label="Session"
            options={filterOptions.sessions}
            selected={stagedFilters.session_id}
            onSelect={(value) => handleStagedChange("session_id", value)}
            showSearch
          />
          {showUserFilter && (
            <TokenUsageFilterDropdown
              label="User ID"
              options={filterOptions.users}
              selected={stagedFilters.user_id}
              onSelect={(value) => handleStagedChange("user_id", value)}
              showSearch
            />
          )}
          {showDepartmentFilter && (
            <TokenUsageFilterDropdown
              label="Department"
              options={filterOptions.departments}
              selected={stagedFilters.department_name}
              onSelect={(value) => handleStagedChange("department_name", value)}
            />
          )}
        </div>
        <div className={styles.dropdownSection}>
          <div className={styles.dropdownSectionHeader}>Date Range</div>
          <div className={styles.filterField}>
            <label className={styles.filterLabel}>Date From</label>
            <input
              type="date"
              className={styles.dateInput}
              value={stagedFilters.date_from}
              onChange={(e) => handleStagedChange("date_from", e.target.value)}
            />
          </div>
          <div className={styles.filterField}>
            <label className={styles.filterLabel}>Date To</label>
            <input
              type="date"
              className={styles.dateInput}
              value={stagedFilters.date_to}
              onChange={(e) => handleStagedChange("date_to", e.target.value)}
            />
          </div>
        </div>
      </div>
      <div className={styles.dropdownFooter}>
        <IAFButton
          type="secondary"
          onClick={handleClearFilters}
          disabled={Object.values(stagedFilters).every((v) => !v)}
          className={styles.footerBtn}
        >
          Clear
        </IAFButton>
        <IAFButton type="primary" onClick={handleApply} loading={loadingData} className={styles.footerBtn}>
          Apply
        </IAFButton>
      </div>
    </div>
  );

  const headerToolbar = (
    <div className={styles.headerActions}>
      <div className={styles.filterContainer}>
        <button
          ref={buttonRef}
          type="button"
          className={`${styles.filterButton} ${filterOpen ? styles.filterButtonActive : ""}`}
          onClick={() => {
            setStagedFilters({ ...filters });
            setFilterOpen(!filterOpen);
          }}
          aria-haspopup="menu"
          aria-expanded={filterOpen}
          aria-label="Open filters"
        >
          <SVGIcons icon="funnel" width={16} height={16} color="var(--content-color)" />
          {activeFilterCount > 0 && (
            <span className={styles.badge}>{activeFilterCount}</span>
          )}
        </button>
        {filterOpen && createPortal(filterDropdown, document.body)}
      </div>
    </div>
  );

  return (
    <>
      {actionsSlot && createPortal(headerToolbar, actionsSlot)}
      <div className={styles.container}>

        {loadingData && (
          <div className={styles.loadingOverlay}>
            <Loader />
          </div>
        )}

        {!loadingData && isEmpty && (
          <EmptyState
            message="No data found for the selected filters."
            showClearFilter={false}
            showCreateButton={false}
          />
        )}

        {!loadingData && summary && !isEmpty && (
          <>
            {/* Usage Summary */}
            <section className={styles.section}>
              <div className={styles.sectionHeader}>
                <h2 className={styles.sectionTitle}>Usage Summary</h2>
                {activeFilterChips.length > 0 && (
                  <div className={styles.filterChips}>
                    {activeFilterChips.map((chip) => (
                      <span key={chip} className={styles.filterChip}>{chip}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className={styles.statsGrid}>
                {SUMMARY_FIELDS.map(({ key, label, format }) => (
                  <StatCard
                    key={key}
                    label={label}
                    value={formatSummaryValue(summary[key], format)}
                  />
                ))}
              </div>
            </section>

            {/* Daily trend — full width */}
            <div className={`${styles.panelCard} ${styles.panelCardFull}`}>
              <div className={styles.panelHeader}>
                <h3 className={styles.panelTitle}>Daily Query Trend</h3>
                <p className={styles.panelSubtitle}>Queries and cost over time</p>
              </div>
              {dailyTrendData.length > 0 ? (
                <ResponsiveContainer width="100%" height={280}>
                  <ComposedChart data={dailyTrendData} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} vertical={false} />
                    <XAxis
                      dataKey="dateLabel"
                      tick={{ fill: chartTheme.muted, fontSize: 11 }}
                      tickLine={false}
                      axisLine={{ stroke: chartTheme.grid }}
                    />
                    <YAxis
                      yAxisId="left"
                      tick={{ fill: chartTheme.muted, fontSize: 11 }}
                      tickLine={false}
                      axisLine={false}
                      width={48}
                    />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      tick={{ fill: chartTheme.muted, fontSize: 11 }}
                      tickFormatter={(v) => formatCurrency(v)}
                      tickLine={false}
                      axisLine={false}
                      width={64}
                    />
                    <Tooltip content={<DailyTrendTooltip />} />
                    <Legend wrapperStyle={{ fontSize: 12, paddingTop: 8 }} />
                    <Bar yAxisId="left" dataKey="queries" name="Queries" fill={CHART_COLORS[0]} radius={[4, 4, 0, 0]} maxBarSize={40} />
                    <Line yAxisId="right" type="monotone" dataKey="cost" name="Cost" stroke={CHART_COLORS[2]} strokeWidth={2} dot={{ r: 3 }} activeDot={{ r: 5 }} />
                  </ComposedChart>
                </ResponsiveContainer>
              ) : (
                <ChartEmpty message="No trend data for the selected period" />
              )}
            </div>

            {/* Secondary charts */}
            <div className={styles.twoColGrid}>
              <div className={styles.panelCard}>
                <div className={styles.panelHeader}>
                  <h3 className={styles.panelTitle}>Cost Over Time by Agent</h3>
                  <p className={styles.panelSubtitle}>Stacked cost per agent</p>
                </div>
                {agentCostChartData.length > 0 ? (
                  <div className={styles.agentCostChartWrap}>
                    <ResponsiveContainer width="100%" height={220}>
                      <AreaChart data={agentCostChartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} vertical={false} />
                        <XAxis
                          dataKey="date"
                          tickFormatter={formatChartDate}
                          tick={{ fill: chartTheme.muted, fontSize: 11 }}
                          tickLine={false}
                          axisLine={{ stroke: chartTheme.grid }}
                        />
                        <YAxis
                          tick={{ fill: chartTheme.muted, fontSize: 11 }}
                          tickFormatter={(v) => formatCurrency(v)}
                          tickLine={false}
                          axisLine={false}
                          width={64}
                        />
                        <Tooltip content={<AgentCostTooltip />} />
                        {agentChartSeries.map((name, i) => (
                          <Area
                            key={name}
                            type="monotone"
                            dataKey={name}
                            name={name}
                            stackId="1"
                            stroke={CHART_COLORS[i % CHART_COLORS.length]}
                            fill={CHART_COLORS[i % CHART_COLORS.length]}
                            fillOpacity={0.5}
                          />
                        ))}
                      </AreaChart>
                    </ResponsiveContainer>
                    <div className={styles.chartLegendScroll}>
                      {agentChartSeries.map((name, i) => (
                        <div key={name} className={styles.chartLegendItem} title={name}>
                          <span
                            className={styles.chartLegendSwatch}
                            style={{ background: CHART_COLORS[i % CHART_COLORS.length] }}
                          />
                          <span className={styles.chartLegendLabel}>{name}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : (
                  <ChartEmpty message="No agent cost data" />
                )}
              </div>

              <div className={styles.panelCard}>
                <div className={styles.panelHeader}>
                  <h3 className={styles.panelTitle}>Cost by Model</h3>
                  <p className={styles.panelSubtitle}>Breakdown by LLM model</p>
                </div>
                {modelBarData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={260}>
                    <BarChart data={modelBarData} layout="vertical" margin={{ left: 8, right: 16, top: 0, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={chartTheme.grid} horizontal={false} />
                      <XAxis
                        type="number"
                        tick={{ fill: chartTheme.muted, fontSize: 11 }}
                        tickFormatter={(v) => formatCurrency(v)}
                        tickLine={false}
                        axisLine={{ stroke: chartTheme.grid }}
                      />
                      <YAxis
                        type="category"
                        dataKey="model"
                        tick={{ fill: chartTheme.muted, fontSize: 11 }}
                        width={120}
                        tickLine={false}
                        axisLine={false}
                      />
                      <Tooltip
                        contentStyle={{ background: chartTheme.cardBg, border: `1px solid ${chartTheme.border}`, borderRadius: 8, fontSize: 12 }}
                        formatter={(val, name) => {
                          if (name === "cost") return formatCurrency(val);
                          return formatNumber(val);
                        }}
                      />
                      <Bar dataKey="cost" name="Cost" fill={CHART_COLORS[4]} radius={[0, 4, 4, 0]} maxBarSize={24} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <ChartEmpty message="No model data" />
                )}
              </div>
            </div>

            {/* Breakdown tables */}
            <div className={styles.twoColGrid}>
              <DataTable
                title="Agent Performance"
                subtitle="Usage and cost per agent"
                headers={["Agent Name", "Queries", "LLM Calls", "Tokens", "Cost"]}
                numericColumns={[1, 2, 3, 4]}
                rows={dashboardData?.agent_breakdown || []}
                scrollable
                renderRow={(row) => (
                  <tr key={row.agent_name}>
                    <td className={styles.truncateCell} title={row.agent_name}>{row.agent_name}</td>
                    <td className={styles.numCell}>{formatNumber(row.queries)}</td>
                    <td className={styles.numCell}>{formatNumber(row.llm_calls)}</td>
                    <td className={styles.numCell}>{formatNumber(row.tokens)}</td>
                    <td className={styles.numCell}>{formatCurrency(row.cost)}</td>
                  </tr>
                )}
              />

              <DataTable
                title="Top Users by Cost"
                subtitle="Highest spenders in selected period"
                headers={["User ID", "Queries", "Tokens", "Cost"]}
                numericColumns={[1, 2, 3]}
                rows={dashboardData?.top_users || []}
                scrollable
                renderRow={(row) => (
                  <tr key={row.user_id}>
                    <td className={styles.truncateCell} title={row.user_id}>{row.user_id}</td>
                    <td className={styles.numCell}>{formatNumber(row.queries)}</td>
                    <td className={styles.numCell}>{formatNumber(row.tokens)}</td>
                    <td className={styles.numCell}>{formatCurrency(row.cost)}</td>
                  </tr>
                )}
              />
            </div>

            {/* Query details — full width */}
            <DataTable
              title="Query Usage Details"
              subtitle="Recent queries with token and cost breakdown"
              headers={[
                "Created At", "User ID", "Agent Name", "Query",
                "Prompt", "Completion", "Cached", "Total Cost",
              ]}
              numericColumns={[4, 5, 6, 7]}
              rows={dashboardData?.recent_queries || []}
              scrollable
              fullWidth
              emptyMessage="No query records found"
              renderRow={(row, i) => (
                <tr key={`${row.created_at}-${i}`}>
                  <td className={styles.nowrapCell}>{formatDateTime(row.created_at)}</td>
                  <td className={styles.truncateCell} title={row.user_id}>{row.user_id}</td>
                  <td className={styles.truncateCell} title={row.agent_name}>{row.agent_name}</td>
                  <td className={styles.queryCell} title={row.query}>{row.query}</td>
                  <td className={styles.numCell}>{formatNumber(row.prompt_tokens)}</td>
                  <td className={styles.numCell}>{formatNumber(row.completion_tokens)}</td>
                  <td className={styles.numCell}>{formatNumber(row.cached_tokens)}</td>
                  <td className={styles.numCell}>{formatCurrency(row.total_cost)}</td>
                </tr>
              )}
            />
          </>
        )}
      </div>
    </>
  );
};

export default TokenUsageTracking;
