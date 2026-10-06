import React, { useState, useEffect, useCallback, useRef } from "react";
import Cookies from "js-cookie";
import { useSchedulerService } from "../../services/schedulerService";
import useFetch from "../../Hooks/useAxios";
import { APIs } from "../../constant";
import { useMessage } from "../../Hooks/MessageContext";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import SubHeader from "../commonComponents/SubHeader";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine";
import Loader from "../commonComponents/Loader";
import EmptyState from "../commonComponents/EmptyState";
import SVGIcons from "../../Icons/SVGIcons";

import { useActiveNavClick } from "../../events/navigationEvents";
import CreateScheduleModal from "./CreateScheduleModal";
import ScheduleHistoryModal from "./ScheduleHistoryModal";
import { getUnconfiguredCostModels } from "../../utils/modelUtils";
import styles from "./Scheduler.module.css";

const Scheduler = () => {
  // ── State ───────────────────────────────────────────────
  const [schedules, setSchedules] = useState([]);
  const [loading, setLoading] = useState(false);
  const [enums, setEnums] = useState(null);
  const [onlyMine, setOnlyMine] = useState(false);
  const [onlyActive, setOnlyActive] = useState(false);

  // Create / Edit modal
  const [createOpen, setCreateOpen] = useState(false);
  const [editData, setEditData] = useState(null);
  const [saving, setSaving] = useState(false);

  // History modal
  const [historyOpen, setHistoryOpen] = useState(false);
  const [historyJob, setHistoryJob] = useState(null);

  // Search
  const [searchValue, setSearchValue] = useState("");
  const [agents, setAgents] = useState([]);
  const [models, setModels] = useState([]);
  const [unconfiguredCostModels, setUnconfiguredCostModels] = useState([]);

  const role = (Cookies.get("role") || "").toUpperCase();
  const canCreate = role !== "SUPERADMIN" && role !== "USER";


  const {
    getEnums,
    validateCron,
    createSchedule,
    listSchedules,
    updateSchedule,
    deleteSchedule,
    pauseSchedule,
    resumeSchedule,
    runNow,
    getHistory,
    getExecutionDetail,
  } = useSchedulerService();

  const { fetchData } = useFetch();
  const { addMessage } = useMessage();
  const initialLoad = useRef(false);

  // ── Refresh on nav click ────────────────────────────────
  useActiveNavClick("/scheduler", () => loadSchedules());

  // ── Initial load ────────────────────────────────────────
  useEffect(() => {
    if (!initialLoad.current) {
      initialLoad.current = true;
      loadEnums();
      loadSchedules();
      loadAgents();
      loadModels();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reload when filters or search change
  useEffect(() => {
    if (initialLoad.current) {
      const debounce = setTimeout(() => loadSchedules(), searchValue ? 400 : 0);
      return () => clearTimeout(debounce);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onlyMine, onlyActive, searchValue]);

  // ── Data loading ────────────────────────────────────────
  const loadEnums = async () => {
    try {
      const data = await getEnums();
      setEnums(data);
    } catch {
      // Enums are optional — form has fallback defaults
    }
  };

  const loadAgents = async () => {
    try {
      const data = await fetchData(APIs.GET_AGENTS_BY_DETAILS);
      setAgents(data || []);
    } catch {
      // Agents list is optional — user can still type manually
    }
  };

  const loadModels = async () => {
    try {
      const data = await fetchData(APIs.GET_MODELS);
      setUnconfiguredCostModels(getUnconfiguredCostModels(data));
      if (data?.models && Array.isArray(data.models)) {
        setModels(data.models);
      }
    } catch {
      // Models list is optional
    }
  };

  const loadSchedules = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSchedules({ onlyMine, onlyActive, searchValue });
      setSchedules(data?.schedules || []);
    } catch {
      addMessage("Failed to load schedules", "error");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onlyMine, onlyActive, searchValue]);

  // ── Create / Edit ───────────────────────────────────────
  const handleCreateOpen = () => {
    setEditData(null);
    setCreateOpen(true);
  };

  const handleEditOpen = (schedule) => {
    setEditData(schedule);
    setCreateOpen(true);
  };

  const handleCreateClose = () => {
    setCreateOpen(false);
    setEditData(null);
  };

  const handleDelete = async (jobId) => {
    setSaving(true);
    try {
      await deleteSchedule(jobId);
      addMessage("Schedule deleted successfully", "success");
      handleCreateClose();
      loadSchedules();
    } catch {
      addMessage("Failed to delete schedule", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleCreateSubmit = async (payload) => {
    setSaving(true);
    try {
      if (editData) {
        await updateSchedule(editData.job_id, payload);
        addMessage("Schedule updated successfully", "success");
      } else {
        await createSchedule(payload);
        addMessage("Schedule created successfully", "success");
      }
      handleCreateClose();
      loadSchedules();
    } catch (err) {
      const msg = err?.response?.data?.detail || err?.message || "Operation failed";
      addMessage(msg, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleValidate = async (body) => {
    return await validateCron(body);
  };

  // ── Schedule actions ────────────────────────────────────
  const handlePause = async (jobId) => {
    try {
      await pauseSchedule(jobId);
      addMessage("Schedule paused", "success");
      loadSchedules();
    } catch {
      addMessage("Failed to pause schedule", "error");
    }
  };

  const handleResume = async (jobId) => {
    try {
      await resumeSchedule(jobId);
      addMessage("Schedule resumed", "success");
      loadSchedules();
    } catch {
      addMessage("Failed to resume schedule", "error");
    }
  };

  const handleRunNow = async (jobId) => {
    try {
      const result = await runNow(jobId);
      if (result?.success) {
        addMessage(`Run triggered — task: ${result.task_id}`, "success");
      } else {
        addMessage(`Run failed: ${result?.error || "Unknown error"}`, "error");
      }
      loadSchedules();
    } catch {
      addMessage("Failed to trigger run", "error");
    }
  };

  // ── History ─────────────────────────────────────────────
  const handleHistoryOpen = (schedule) => {
    setHistoryJob(schedule);
    setHistoryOpen(true);
  };

  const handleHistoryClose = () => {
    setHistoryOpen(false);
    setHistoryJob(null);
  };

  // ── Helpers ─────────────────────────────────────────────
  const getBadge = (s) => {
    if (s.is_deleted) return { cls: styles.badgeDeleted, text: "Deleted", dot: "#ef4444" };
    if (s.is_active) return { cls: styles.badgeActive, text: "Active", dot: "#22c55e" };
    return { cls: styles.badgePaused, text: "Paused", dot: "#f59e0b" };
  };

  const hasActiveFilters = Boolean(searchValue.trim() || onlyMine || onlyActive);

  const clearFilters = () => {
    setSearchValue("");
    setOnlyMine(false);
    setOnlyActive(false);
  };

  // ── Render ──────────────────────────────────────────────
  return (
    <div className="pageContainer">
      <SubHeader
        heading="Scheduler"
        onPlusClick={canCreate ? handleCreateOpen : undefined}
        plusButtonLabel="New Schedule"
        handleRefresh={loadSchedules}
        showSearch={true}
        onSearch={(value) => setSearchValue(value)}
        searchValue={searchValue}
        clearSearch={clearFilters}
      />

      <SummaryLine
        visibleCount={schedules.length}
        totalCount={schedules.length}
        itemLabel="schedules"
      />

      <div className={styles.filterBar}>
        <button
          className={`${styles.filterChip} ${onlyMine ? styles.filterChipActive : ""}`}
          onClick={() => setOnlyMine(!onlyMine)}
        >
          My Schedules
        </button>
        <button
          className={`${styles.filterChip} ${onlyActive ? styles.filterChipActive : ""}`}
          onClick={() => setOnlyActive(!onlyActive)}
        >
          Active Only
        </button>
      </div>

      <PageLayout>
        <div className={styles.listWrapper}>
          {loading ? (
            <Loader />
          ) : schedules.length === 0 && hasActiveFilters ? (
            <EmptyState
              filters={[
                ...(searchValue.trim() ? [`Search: ${searchValue}`] : []),
                ...(onlyMine ? ["My Schedules"] : []),
                ...(onlyActive ? ["Active Only"] : []),
              ]}
              onClearFilters={clearFilters}
              onCreateClick={canCreate ? handleCreateOpen : undefined}
              createButtonLabel={canCreate ? "New Schedule" : undefined}
              showCreateButton={canCreate}
            />
          ) : schedules.length === 0 ? (
            <EmptyState
              message="No schedules found"
              subMessage={canCreate ? "Get started by creating your first schedule" : undefined}
              onCreateClick={canCreate ? handleCreateOpen : undefined}
              createButtonLabel={canCreate ? "New Schedule" : undefined}
              showClearFilter={false}
              showCreateButton={canCreate}
            />
          ) : (
            <div className={styles.scheduleGrid}>
              {schedules.map((s) => {
                const badge = getBadge(s);
                return (
                  <div
                    key={s.job_id}
                    className={styles.scheduleCard}
                    onClick={() => handleEditOpen(s)}
                    style={{ cursor: "pointer" }}
                  >
                    {/* Header: title + status badge */}
                    <div className={styles.cardHeader}>
                      <div className={styles.cardTitle}>{s.schedule_name}</div>
                      <span className={`${styles.cardBadge} ${badge.cls}`}>
                        <span className={styles.badgeDot} style={{ background: badge.dot }} />
                        {badge.text}
                      </span>
                    </div>

                    {/* Description: cron + human readable */}
                    <div className={styles.cardDescription}>
                      <code className={styles.cronCode}>{s.cron_expression}</code>
                      {s.human_readable && (
                        <span className={styles.humanText}>{s.human_readable}</span>
                      )}
                    </div>

                    {/* Info row */}
                    <div className={styles.cardInfo}>
                      {s.next_run_at && (
                        <span className={styles.nextRun}>
                          Next: {new Date(s.next_run_at).toLocaleString()}
                        </span>
                      )}
                    </div>

                    {/* Spacer pushes footer down */}
                    <div className={styles.cardSpacer} />

                    {/* Footer: stats left, actions right */}
                    <div className={styles.cardFooter}>
                      <div className={styles.cardStats}>
                        <span className={styles.stat}>{s.run_count || 0} runs</span>
                        <span className={`${styles.stat} ${styles.statSuccess}`}>
                          {s.success_count || 0} ✓
                        </span>
                        <span className={`${styles.stat} ${styles.statFail}`}>
                          {s.failure_count || 0} ✗
                        </span>
                      </div>

                      <div className={styles.cardActionsContainer} onClick={(e) => e.stopPropagation()}>
                        <button
                          className={styles.actionBtn}
                          onClick={() => handleRunNow(s.job_id)}
                          title="Run Now"
                        >
                          <SVGIcons icon="bolt" width={14} height={14} />
                        </button>
                        {s.is_active ? (
                          <button
                            className={styles.actionBtn}
                            onClick={() => handlePause(s.job_id)}
                            title="Pause"
                          >
                            ⏸
                          </button>
                        ) : (
                          <button
                            className={`${styles.actionBtn} ${styles.actionBtnAccent}`}
                            onClick={() => handleResume(s.job_id)}
                            title="Resume"
                          >
                            <SVGIcons icon="play" width={12} height={12} />
                          </button>
                        )}
                        <button
                          className={styles.actionBtn}
                          onClick={() => handleHistoryOpen(s)}
                          title="History"
                        >
                          <SVGIcons icon="history" width={14} height={14} />
                        </button>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      </PageLayout>

      {/* Create / Edit Modal */}
      <CreateScheduleModal
        isOpen={createOpen}
        onClose={handleCreateClose}
        onSubmit={handleCreateSubmit}
        onDelete={handleDelete}
        onValidate={handleValidate}
        enums={enums}
        agents={agents}
        models={models}
        unconfiguredCostModels={unconfiguredCostModels}
        editData={editData}
        saving={saving}
      />

      {/* History Modal */}
      <ScheduleHistoryModal
        isOpen={historyOpen}
        onClose={handleHistoryClose}
        jobId={historyJob?.job_id}
        scheduleName={historyJob?.schedule_name}
        onLoadHistory={getHistory}
        onLoadDetail={getExecutionDetail}
      />

    </div>
  );
};

export default Scheduler;
