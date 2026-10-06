import React, { useState, useEffect, useCallback, forwardRef } from "react";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import { TextField } from "../../iafComponents/GlobalComponents/TextField";
import CheckBox from "../../iafComponents/GlobalComponents/CheckBox/CheckBox";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import DatePicker from "react-datepicker";
import "react-datepicker/dist/react-datepicker.css";
import styles from "./Scheduler.module.css";
import SVGIcons from "../../Icons/SVGIcons";
import UnconfiguredModelCostWarning from "../commonComponents/UnconfiguredModelCostWarning";

const DatePickerCustomInput = forwardRef(({ value, placeholder, onClick, onClear }, ref) => (
  <div className={styles.dateInputContainer} ref={ref}>
    <input
      className={styles.datePickerInput}
      value={value}
      placeholder={placeholder}
      readOnly
      onClick={onClick}
    />
    {value && (
      <button
        type="button"
        className={styles.dateClearBtn}
        onClick={(e) => { e.stopPropagation(); onClear(); }}
        aria-label="Clear date"
      >
        &times;
      </button>
    )}
    <span className={styles.dateCalendarIcon} onClick={onClick}>
      <SVGIcons icon="calendar" width={16} height={16} />
    </span>
  </div>
));

// Allowed agent types per framework
const FRAMEWORK_AGENT_TYPES = {
  langgraph: ["react_agent", "multi_agent", "planner_executor_agent", "react_critic_agent", "meta_agent", "planner_meta_agent"],
  LangGraph: ["react_agent", "multi_agent", "planner_executor_agent", "react_critic_agent", "meta_agent", "planner_meta_agent"],
  google_adk: ["react_agent", "multi_agent", "planner_executor_agent", "react_critic_agent", "meta_agent", "planner_meta_agent"],
  GoogleADK: ["react_agent", "multi_agent", "planner_executor_agent", "react_critic_agent", "meta_agent", "planner_meta_agent"],
  pure_python: ["hybrid_agent"],
  Hybrid: ["hybrid_agent"],
};

const FREQUENCY_OPTIONS = ["minutely", "hourly", "daily", "weekly", "monthly", "yearly"];
const DAY_OPTIONS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"];
const MONTH_OPTIONS = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"];

const DEFAULT_FORM = {
  schedule_name: "",
  description: "",
  agentic_application_id: "",
  query: "",
  model_name: "",
  framework_type: "langgraph",
  timezone: "Asia/Kolkata",
  is_active: true,
  max_runs: "",
  end_date: "",
  max_consecutive_failures: 5,
  // Timing
  timing_mode: "structured",
  cron_expression: "",
  frequency: "daily",
  interval: 1,
  hour: 9,
  minute: 0,
  days_of_week: ["MON", "TUE", "WED", "THU", "FRI"],
  days_of_month: "1,15",
  month: "JAN",
  day_of_month: 1,
  // Flags
  evaluation_flag: false,
  validator_flag: false,
  context_flag: true,
  file_context_management_flag: false,
  response_formatting_flag: false,
  temperature: 0,
};

const CreateScheduleModal = ({
  isOpen,
  onClose,
  onSubmit,
  onDelete,
  onValidate,
  enums,
  agents = [],
  models = [],
  unconfiguredCostModels = [],
  editData,
  saving,
}) => {
  const [form, setForm] = useState({ ...DEFAULT_FORM });
  const [preview, setPreview] = useState(null);
  const [validating, setValidating] = useState(false);
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  const isEdit = !!editData;

  useEffect(() => {
    if (isOpen) {
      if (editData) {
        setForm(mapEditDataToForm(editData));
        setShowAdvanced(true);
      } else {
        setForm({ ...DEFAULT_FORM });
        setShowAdvanced(false);
      }
      setPreview(null);
    }
  }, [isOpen, editData]);

  const mapEditDataToForm = (data) => {
    const sched = data.schedule;
    const isStructured = sched !== null && sched !== undefined;

    return {
      schedule_name: data.schedule_name || "",
      description: data.description || "",
      agentic_application_id: data.agentic_application_id || "",
      query: data.query || "",
      model_name: data.model_name || "",
      framework_type: data.framework_type || "langgraph",
      timezone: data.timezone || "Asia/Kolkata",
      is_active: data.is_active ?? true,
      max_runs: data.max_runs ?? "",
      end_date: data.end_date || "",
      max_consecutive_failures: data.max_consecutive_failures ?? 5,
      timing_mode: isStructured ? "structured" : "raw",
      cron_expression: data.cron_expression || "",
      frequency: sched?.frequency || "daily",
      interval: sched?.interval ?? 1,
      hour: sched?.hour ?? 0,
      minute: sched?.minute ?? 0,
      days_of_week: sched?.days_of_week ?? ["MON", "TUE", "WED", "THU", "FRI"],
      days_of_month: Array.isArray(sched?.days_of_month)
        ? sched.days_of_month.join(",")
        : sched?.days_of_month || "1,15",
      month: sched?.month || "JAN",
      day_of_month: sched?.day_of_month ?? 1,
      evaluation_flag: data.inference_flags?.evaluation_flag ?? false,
      validator_flag: data.inference_flags?.validator_flag ?? false,
      context_flag: data.inference_flags?.context_flag ?? true,
      file_context_management_flag: data.inference_flags?.file_context_management_flag ?? false,
      response_formatting_flag: data.inference_flags?.response_formatting_flag ?? false,
      temperature: data.inference_flags?.temperature ?? 0,
    };
  };

  const updateField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  const toggleDayOfWeek = (day) => {
    setForm((prev) => {
      const days = prev.days_of_week.includes(day)
        ? prev.days_of_week.filter((d) => d !== day)
        : [...prev.days_of_week, day];
      return { ...prev, days_of_week: days };
    });
  };

  const buildPayload = () => {
    const payload = {
      schedule_name: form.schedule_name.trim(),
      description: form.description.trim() || null,
      agentic_application_id: form.agentic_application_id.trim(),
      query: form.query.trim(),
      model_name: form.model_name.trim(),
      framework_type: form.framework_type,
      timezone: form.timezone,
      is_active: form.is_active,
      max_consecutive_failures: parseInt(form.max_consecutive_failures, 10) || 5,
      inference_flags: {
        evaluation_flag: form.evaluation_flag,
        validator_flag: form.validator_flag,
        context_flag: form.context_flag,
        file_context_management_flag: form.file_context_management_flag,
        response_formatting_flag: form.response_formatting_flag,
        temperature: parseFloat(form.temperature) || 0,
      },
    };

    if (form.max_runs) payload.max_runs = parseInt(form.max_runs, 10);
    if (form.end_date) payload.end_date = form.end_date;

    if (form.timing_mode === "raw") {
      payload.cron_expression = form.cron_expression.trim();
    } else {
      payload.schedule = buildStructured();
    }

    return payload;
  };

  const buildStructured = () => {
    const out = {
      frequency: form.frequency,
      interval: parseInt(form.interval, 10) || 1,
      hour: parseInt(form.hour, 10) || 0,
      minute: parseInt(form.minute, 10) || 0,
    };
    if (form.frequency === "weekly") {
      out.days_of_week = form.days_of_week;
    }
    if (form.frequency === "monthly") {
      out.days_of_month = form.days_of_month
        .split(",")
        .map((s) => parseInt(s.trim(), 10))
        .filter((n) => !isNaN(n));
    }
    if (form.frequency === "yearly") {
      out.month = form.month;
      out.day_of_month = parseInt(form.day_of_month, 10) || 1;
    }
    return out;
  };

  const handleValidate = useCallback(async () => {
    setValidating(true);
    try {
      const body = { timezone: form.timezone };
      if (form.timing_mode === "raw") {
        body.cron_expression = form.cron_expression.trim();
      } else {
        body.schedule = buildStructured();
      }
      const result = await onValidate(body);
      setPreview(result);
    } catch {
      setPreview({ valid: false, error: "Validation request failed" });
    } finally {
      setValidating(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.timing_mode, form.cron_expression, form.timezone, form.frequency, form.interval, form.hour, form.minute, form.days_of_week, form.days_of_month, form.month, form.day_of_month, onValidate]);

  const handleSubmit = () => {
    const payload = buildPayload();
    onSubmit(payload);
  };

  const timezones = enums?.timezones || [
    "UTC", "Asia/Kolkata", "Asia/Dubai", "Asia/Singapore",
    "Europe/London", "America/New_York", "America/Los_Angeles",
  ];
  const frameworkTypes = enums?.framework_types || ["LangGraph", "GoogleADK", "Hybrid"];

  const canSubmit =
    form.schedule_name.trim() &&
    form.agentic_application_id.trim() &&
    form.query.trim() &&
    form.model_name.trim() &&
    (form.timing_mode === "raw" ? form.cron_expression.trim() : true);

  const footer = (
    <div className={styles.modalFooter}>
      <IAFButton type="secondary" onClick={onClose} disabled={saving}>
        Cancel
      </IAFButton>
      {isEdit && onDelete && (
        <IAFButton
          type="primary"
          onClick={() => setShowDeleteConfirm(true)}
          disabled={saving}
          aria-label="Delete this schedule"
        >
          Delete
        </IAFButton>
      )}
      <IAFButton
        type="secondary"
        onClick={handleValidate}
        loading={validating}
        disabled={saving}
      >
        Validate
      </IAFButton>
      <IAFButton
        type="primary"
        onClick={handleSubmit}
        loading={saving}
        disabled={!canSubmit || saving}
      >
        {isEdit ? "Update Schedule" : "Create Schedule"}
      </IAFButton>
    </div>
  );

  return (
    <>
      <FullModal
        isOpen={isOpen}
        onClose={onClose}
        title={isEdit ? "Edit Schedule" : "New Schedule"}
        headerInfo={isEdit && editData?.created_by ? [{ label: "Created by", value: editData.created_by }] : undefined}
        footer={footer}
      >
        <div className={styles.formGrid}>
          {/* Basic fields */}
          <div className={styles.formField}>
            <TextField
              label="Schedule Name *"
              value={form.schedule_name}
              onChange={(e) => updateField("schedule_name", e.target.value)}
              placeholder="e.g. Daily morning report"
            />
          </div>
          <div className={styles.formField}>
            <TextField
              label="Description"
              value={form.description}
              onChange={(e) => updateField("description", e.target.value)}
              placeholder="Optional description"
            />
          </div>

          <div className={styles.formField}>
            <label className={styles.formLabel}>Model Name *</label>
            <NewCommonDropdown
              options={models}
              selected={form.model_name}
              onSelect={(val) => updateField("model_name", val)}
              placeholder="Select model"
              showSearch={true}
            />
            <UnconfiguredModelCostWarning
              selectedModel={form.model_name}
              unconfiguredCostModels={unconfiguredCostModels}
            />
          </div>
          <div className={styles.formField}>
            <label className={styles.formLabel}>Framework</label>
            <NewCommonDropdown
              options={frameworkTypes}
              selected={form.framework_type}
              onSelect={(val) => {
                updateField("framework_type", val);
                updateField("agentic_application_id", "");
              }}
              placeholder="Select framework"
              showSearch={false}
            />
          </div>

          <div className={styles.formField}>
            <label className={styles.formLabel}>Agent *</label>
            <NewCommonDropdown
              options={agents
                .filter((a) => {
                  const allowed = FRAMEWORK_AGENT_TYPES[form.framework_type];
                  return allowed ? allowed.includes(a.agentic_application_type) : true;
                })
                .map((a) => a.agentic_application_name)}
              selected={
                agents.find((a) => a.agentic_application_id === form.agentic_application_id)
                  ?.agentic_application_name || ""
              }
              onSelect={(name) => {
                const match = agents.find((a) => a.agentic_application_name === name);
                if (match) updateField("agentic_application_id", match.agentic_application_id);
              }}
              placeholder="Select agent"
              showSearch={true}
              disabled={isEdit}
            />
          </div>

          <div className={`${styles.formField} ${styles.formGridFull}`}>
            <TextareaWithActions
              label="Query *"
              value={form.query}
              onChange={(e) => updateField("query", e.target.value)}
              placeholder="Enter the prompt / query for the agent"
              rows={3}
              showCopy={false}
              showExpand={true}
            />
          </div>

          {/* Timing section */}
          <div className={styles.sectionTitle}>Timing</div>

          <div className={styles.formField}>
            <label className={styles.formLabel}>Timezone</label>
            <NewCommonDropdown
              options={timezones}
              selected={form.timezone}
              onSelect={(val) => updateField("timezone", val)}
              placeholder="Select timezone"
              showSearch={true}
            />
          </div>

          <div className={styles.formField}>
            <label className={styles.formLabel}>Mode</label>
            <NewCommonDropdown
              options={["structured", "raw"]}
              selected={form.timing_mode}
              onSelect={(val) => updateField("timing_mode", val)}
              placeholder="Select mode"
              showSearch={false}
            />
          </div>

          {form.timing_mode === "raw" ? (
            <div className={styles.formField}>
              <TextField
                label="Cron Expression (m h dom mon dow) *"
                value={form.cron_expression}
                onChange={(e) => updateField("cron_expression", e.target.value)}
                placeholder="*/5 * * * *"
              />
            </div>
          ) : (
            <>
              <div className={styles.formField}>
                <label className={styles.formLabel}>Frequency</label>
                <NewCommonDropdown
                  options={FREQUENCY_OPTIONS}
                  selected={form.frequency}
                  onSelect={(val) => updateField("frequency", val)}
                  placeholder="Select frequency"
                  showSearch={false}
                />
              </div>

              <div className={`${styles.formGridFull}`}>
                <div className={styles.formRow}>
                  {(form.frequency === "minutely" || form.frequency === "hourly" || form.frequency === "daily") && (
                    <div className={styles.formField}>
                      <TextField
                        label="Interval"
                        type="number"
                        value={String(form.interval)}
                        onChange={(e) => updateField("interval", e.target.value)}
                        min={1}
                        max={59}
                      />
                    </div>
                  )}
                  {(form.frequency === "hourly" || form.frequency === "daily" || form.frequency === "weekly" || form.frequency === "monthly" || form.frequency === "yearly") && (
                    <div className={styles.formField}>
                      <TextField
                        label="Minute (0-59)"
                        type="number"
                        value={String(form.minute)}
                        onChange={(e) => updateField("minute", e.target.value)}
                        min={0}
                        max={59}
                      />
                    </div>
                  )}
                  {(form.frequency === "daily" || form.frequency === "weekly" || form.frequency === "monthly" || form.frequency === "yearly") && (
                    <div className={styles.formField}>
                      <TextField
                        label="Hour (0-23)"
                        type="number"
                        value={String(form.hour)}
                        onChange={(e) => updateField("hour", e.target.value)}
                        min={0}
                        max={23}
                      />
                    </div>
                  )}
                </div>
              </div>

              {form.frequency === "weekly" && (
                <div className={`${styles.formField} ${styles.formGridFull}`}>
                  <label className={styles.formLabel}>Days of Week</label>
                  <div className={styles.checkboxRow}>
                    {DAY_OPTIONS.map((day) => (
                      <div
                        key={day}
                        className={styles.checkboxLabel}
                        onClick={() => toggleDayOfWeek(day)}
                      >
                        <CheckBox
                          checked={form.days_of_week.includes(day)}
                          onChange={() => toggleDayOfWeek(day)}
                          label={day}
                        />
                        <span>{day}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {form.frequency === "monthly" && (
                <div className={`${styles.formField} ${styles.formGridFull}`}>
                  <TextField
                    label="Days of Month (comma-separated, 1-31)"
                    value={form.days_of_month}
                    onChange={(e) => updateField("days_of_month", e.target.value)}
                    placeholder="1,15"
                  />
                </div>
              )}

              {form.frequency === "yearly" && (
                <div className={`${styles.formGridFull}`}>
                  <div className={styles.formRow}>
                    <div className={styles.formField}>
                      <label className={styles.formLabel}>Month</label>
                      <NewCommonDropdown
                        options={MONTH_OPTIONS}
                        selected={form.month}
                        onSelect={(val) => updateField("month", val)}
                        placeholder="Select month"
                        showSearch={false}
                      />
                    </div>
                    <div className={styles.formField}>
                      <TextField
                        label="Day of Month"
                        type="number"
                        value={String(form.day_of_month)}
                        onChange={(e) => updateField("day_of_month", e.target.value)}
                        min={1}
                        max={31}
                      />
                    </div>
                  </div>
                </div>
              )}
            </>
          )}

          {/* Validate preview */}
          {preview && (
            <div className={styles.previewPanel}>
              {preview.valid ? (
                <>
                  <div className={styles.previewValid}>
                    <span className={styles.previewDot} style={{ background: "#22c55e" }} />
                    Valid: {preview.cron_expression} [{preview.timezone}]
                  </div>
                  {preview.human_readable && (
                    <div className={styles.previewHuman}>{preview.human_readable}</div>
                  )}
                  {preview.next_runs?.length > 0 && (
                    <div className={styles.previewRunList}>
                      <div className={styles.previewRunHeader}>Upcoming Runs</div>
                      {preview.next_runs.map((t, i) => (
                        <div key={i} className={styles.previewRun}>
                          <span className={styles.previewRunIndex}>{i + 1}</span>
                          {new Date(t).toLocaleString()}
                        </div>
                      ))}
                    </div>
                  )}
                </>
              ) : (
                <div className={styles.previewInvalid}>
                  <span className={styles.previewDot} style={{ background: "#ef4444" }} />
                  {preview.error || "Invalid cron expression"}
                </div>
              )}
            </div>
          )}

          {/* Advanced section */}
          <div
            className={styles.advancedToggle}
            onClick={() => setShowAdvanced(!showAdvanced)}
          >
            {showAdvanced ? "▾" : "▸"} Advanced Settings
          </div>

          {showAdvanced && (
            <>
              <div className={styles.formField}>
                <TextField
                  label="Max Runs"
                  type="number"
                  value={String(form.max_runs)}
                  onChange={(e) => updateField("max_runs", e.target.value)}
                  placeholder="∞ (unlimited)"
                  min={1}
                />
              </div>
              <div className={styles.formField}>
                <TextField
                  label="Max Consecutive Failures"
                  type="number"
                  value={String(form.max_consecutive_failures)}
                  onChange={(e) => updateField("max_consecutive_failures", e.target.value)}
                  min={1}
                  max={100}
                />
              </div>
              <div className={styles.formField}>
                <label className={styles.formLabel}>End Date</label>
                <div className={styles.datePickerWrapper}>
                  <DatePicker
                    selected={form.end_date ? new Date(form.end_date) : null}
                    onChange={(date) => {
                      if (date) {
                        updateField("end_date", date.toISOString());
                      } else {
                        updateField("end_date", "");
                      }
                    }}
                    showTimeSelect
                    timeFormat="HH:mm"
                    timeIntervals={15}
                    dateFormat="yyyy-MM-dd HH:mm"
                    timeCaption="Time"
                    placeholderText="Select end date & time"
                    customInput={
                      <DatePickerCustomInput
                        onClear={() => updateField("end_date", "")}
                      />
                    }
                    minDate={new Date()}
                  />
                </div>
              </div>
              <div className={styles.formField}>
                <TextField
                  label="Temperature (0-1)"
                  type="number"
                  value={String(form.temperature)}
                  onChange={(e) => updateField("temperature", e.target.value)}
                  min={0}
                  max={1}
                  step={0.1}
                />
              </div>

              <div className={styles.sectionTitle}>Inference Flags</div>
              <div className={styles.checkboxRow}>
                <div className={styles.checkboxLabel} onClick={() => updateField("evaluation_flag", !form.evaluation_flag)}>
                  <CheckBox
                    checked={form.evaluation_flag}
                    onChange={() => updateField("evaluation_flag", !form.evaluation_flag)}
                    label="Evaluation"
                  />
                  <span>Evaluation</span>
                </div>
                <div className={styles.checkboxLabel} onClick={() => updateField("validator_flag", !form.validator_flag)}>
                  <CheckBox
                    checked={form.validator_flag}
                    onChange={() => updateField("validator_flag", !form.validator_flag)}
                    label="Validator"
                  />
                  <span>Validator</span>
                </div>
                <div className={styles.checkboxLabel} onClick={() => updateField("context_flag", !form.context_flag)}>
                  <CheckBox
                    checked={form.context_flag}
                    onChange={() => updateField("context_flag", !form.context_flag)}
                    label="Context"
                  />
                  <span>Context</span>
                </div>
                <div className={styles.checkboxLabel} onClick={() => updateField("response_formatting_flag", !form.response_formatting_flag)}>
                  <CheckBox
                    checked={form.response_formatting_flag}
                    onChange={() => updateField("response_formatting_flag", !form.response_formatting_flag)}
                    label="Response Formatting"
                  />
                  <span>Response Formatting</span>
                </div>
              </div>
            </>
          )}
        </div>
      </FullModal>

      {showDeleteConfirm && (
        <ConfirmationModal
          message={`Are you sure you want to delete "${form.schedule_name}"? This action cannot be undone.`}
          onConfirm={async () => {
            await onDelete(editData.job_id);
            setShowDeleteConfirm(false);
          }}
          setShowConfirmation={setShowDeleteConfirm}
          loading={saving}
        />
      )}
    </>
  );
};

export default CreateScheduleModal;
