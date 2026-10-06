import React, { useState, useEffect, useCallback, useRef } from "react";
import Cookies from "js-cookie";
import { useHookRepositoryService } from "../../services/hookRepositoryService";
import { useMessage } from "../../Hooks/MessageContext";
import SVGIcons from "../../Icons/SVGIcons";
import IAFButton from "../../iafComponents/GlobalComponents/Buttons/Button";
import TextField from "../../iafComponents/GlobalComponents/TextField/TextField";
import { FullModal } from "../../iafComponents/GlobalComponents/FullModal";
import EmptyState from "../commonComponents/EmptyState";
import ConfirmationModal from "../commonComponents/ToastMessages/ConfirmationPopup";
import CodeEditor from "../commonComponents/CodeEditor";
import Loader from "../commonComponents/Loader";
import NewCommonDropdown from "../commonComponents/NewCommonDropdown";
import SubHeader from "../commonComponents/SubHeader";
import PageLayout from "../../iafComponents/GlobalComponents/PageLayout";
import SummaryLine from "../../iafComponents/GlobalComponents/SummaryLine";
import DisplayCard1 from "../../iafComponents/GlobalComponents/DisplayCard/DisplayCard1";
import TextareaWithActions from "../commonComponents/TextareaWithActions";
import { useActiveNavClick } from "../../events/navigationEvents";
import { copyToClipboard, downloadAsFile } from "../../utils/clipboardUtils";
import SampleHooksModal from "./SampleHooksModal";
import ZoomPopup from "../commonComponents/ZoomPopup";
import styles from "./HookRepository.module.css";

/**
 * HOOK_EVENTS — user-configurable lifecycle events.
 * System events (OnAgentStart/End/Error, PostSampling) are auto-managed and not shown.
 */
const HOOK_EVENTS = [
  "PreToolUse",
  "PostToolUse",
  "PreResponse",
];

const TEST_TOOLS = [
  "run_shell_command",
  "database_query_tool",
  "execute_python_code",
];

const EMPTY_FORM = {
  name: "",
  code: "",
  description: "",
};

/**
 * HookRepository — Standalone page for managing hook scripts.
 *
 * CRUD: List → Create / Edit / Delete via FullModal.
 * Test: Dry-run a hook with sample data.
 * Follows KnowledgeBase page pattern with SubHeader + PageLayout.
 */
const HookRepository = () => {
  // ── State ──────────────────────────────────────────
  const [hooks, setHooks] = useState([]);
  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [formData, setFormData] = useState({ ...EMPTY_FORM });
  const [isEditMode, setIsEditMode] = useState(false);
  const [editHookId, setEditHookId] = useState(null);
  const [editHookMeta, setEditHookMeta] = useState(null);
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

  // Test panel state
  const [showTestPanel, setShowTestPanel] = useState(false);
  const [testInput, setTestInput] = useState({ tool_name: "", tool_input: "", event: "PreToolUse" });
  const [testResult, setTestResult] = useState(null);
  const [testing, setTesting] = useState(false);

  // Sample hooks modal state
  const [showSampleHooks, setShowSampleHooks] = useState(false);

  // Zoom popup state
  const [showZoomPopup, setShowZoomPopup] = useState(false);

  // Copy feedback state
  const [codeCopied, setCodeCopied] = useState(false);
  const COPY_FEEDBACK_MS = 2000;

  // File upload ref
  const codeFileInputRef = useRef(null);

  // ── Service & messages ─────────────────────────────
  const { listHooks, getHookById, createHook, updateHook, deleteHook, testHook } =
    useHookRepositoryService();
  const { addMessage } = useMessage();
  const userName = Cookies.get("userName") || Cookies.get("email") || "";

  // ── Fetch hooks on mount ───────────────────────────
  const fetchHooks = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listHooks();
      setHooks(data);
    } catch {
      // empty state renders naturally
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    fetchHooks();
  }, [fetchHooks]);

  // Reset state on nav click (same tab re-click)
  useActiveNavClick("/hooks", () => {
    setSearchTerm("");
    setModalOpen(false);
  });

  // ── SubHeader handlers ─────────────────────────────
  const handleSearch = (value) => setSearchTerm(value);
  const clearSearch = () => setSearchTerm("");

  // ── Modal handlers ─────────────────────────────────
  const openCreateModal = useCallback(() => {
    setFormData({ ...EMPTY_FORM });
    setIsEditMode(false);
    setEditHookId(null);
    setEditHookMeta(null);
    setShowDeleteConfirm(false);
    setShowTestPanel(false);
    setTestResult(null);
    setModalOpen(true);
  }, []);

  const openEditModal = async (hook) => {
    setIsEditMode(true);
    setEditHookId(hook.hook_id);
    setEditHookMeta(hook);
    setShowDeleteConfirm(false);
    setShowTestPanel(false);
    setTestResult(null);
    // Pre-fill with card data, then fetch full details (includes code)
    setFormData({
      name: hook.name || "",
      code: hook.code || "",
      description: hook.description || "",
    });
    setModalOpen(true);

    // Fetch full hook detail (includes code)
    try {
      const full = await getHookById(hook.hook_id);
      setFormData((prev) => ({
        ...prev,
        code: full.code || prev.code,
        name: full.name || prev.name,
        description: full.description || prev.description,
      }));
    } catch {
      // keep card-level data
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    setFormData({ ...EMPTY_FORM });
    setIsEditMode(false);
    setEditHookId(null);
    setEditHookMeta(null);
    setShowDeleteConfirm(false);
    setShowTestPanel(false);
    setTestResult(null);
  };

  const handleFieldChange = (field, value) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
  };

  // ── Copy code handler ──────────────────────────────
  const handleCopyCode = async () => {
    if (!formData.code || !formData.code.trim()) return;
    const result = await copyToClipboard(formData.code);
    if (result === "success") {
      setCodeCopied(true);
      setTimeout(() => setCodeCopied(false), COPY_FEEDBACK_MS);
    } else if (result === "too_large") {
      addMessage("Code is too large to copy. Downloading as file instead...", "error");
      downloadAsFile(formData.code, `${formData.name || "hook"}.py`);
    } else {
      addMessage("Failed to copy text to clipboard", "error");
    }
  };

  // ── Upload .py file handler ────────────────────────
  const handleUploadClick = () => {
    codeFileInputRef.current?.click();
  };

  const handleFileUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".py")) {
      addMessage("Please upload a valid .py file", "error");
      e.target.value = "";
      return;
    }
    const reader = new FileReader();
    reader.onload = (event) => {
      const content = event.target.result;
      handleFieldChange("code", content);
      addMessage(`Loaded ${file.name}`, "success");
    };
    reader.readAsText(file);
    e.target.value = "";
  };


  // ── CRUD operations ────────────────────────────────
  const handleCreate = async () => {
    if (!formData.name.trim()) {
      addMessage("Hook name is required", "error");
      return;
    }
    if (!formData.code.trim()) {
      addMessage("Hook code is required", "error");
      return;
    }
    setSaving(true);
    try {
      const payload = {
        name: formData.name.trim(),
        code: formData.code,
        description: formData.description.trim(),
      };
      const response = await createHook(payload);
      if (response) {
        addMessage(
          response.message || `Hook "${formData.name}" created (${response.hook_id || ""})`,
          "success"
        );
      }
      closeModal();
      fetchHooks();
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || "Failed to create hook";
      addMessage(detail, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleUpdate = async () => {
    if (!editHookId) return;
    setSaving(true);
    try {
      const payload = {
        name: formData.name.trim(),
        code: formData.code,
        description: formData.description.trim(),
      };
      const response = await updateHook(editHookId, payload);
      if (response) {
        addMessage(response.message || "Hook updated successfully", "success");
      }
      closeModal();
      fetchHooks();
    } catch (err) {
      const detail = err?.response?.data?.detail || err?.message || "Failed to update hook";
      addMessage(detail, "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!editHookId) return;
    setDeleting(true);
    try {
      await deleteHook(editHookId);
      addMessage("Hook deleted successfully", "success");
      closeModal();
      fetchHooks();
    } catch {
      addMessage("Failed to delete hook", "error");
    } finally {
      setDeleting(false);
      setShowDeleteConfirm(false);
    }
  };

  // ── Test hook ──────────────────────────────────────
  const handleTest = async () => {
    if (!editHookId) return;
    setTesting(true);
    setTestResult(null);
    try {
      const payload = {
        tool_name: testInput.tool_name.trim(),
        tool_input: testInput.tool_input.trim(),
        event: testInput.event,
      };
      const result = await testHook(editHookId, payload);
      setTestResult(result);
    } catch {
      addMessage("Hook test failed", "error");
    } finally {
      setTesting(false);
    }
  };

  // ── Filter by search ──────────────────────────────
  const filteredHooks = hooks.filter((h) => {
    if (!searchTerm) return true;
    const term = searchTerm.toLowerCase();
    return (
      (h.name || "").toLowerCase().includes(term) ||
      (h.hook_id || "").toLowerCase().includes(term) ||
      (h.description || "").toLowerCase().includes(term) ||
      (h.department || "").toLowerCase().includes(term)
    );
  });

  const hooksForCards = filteredHooks.map((hook) => ({
    ...hook,
    card_tag: "Hook",
  }));

  // ── Helpers ────────────────────────────────────────
  const formatDate = (dateStr) => {
    if (!dateStr) return "";
    try {
      return new Date(dateStr).toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
        year: "numeric",
      });
    } catch {
      return dateStr;
    }
  };

  const getInterpretClass = (interpretation) => {
    switch (interpretation) {
      case "ALLOW":
        return styles.interpretAllow;
      case "BLOCKED":
        return styles.interpretBlocked;
      case "APPROVAL_REQUIRED":
        return styles.interpretApproval;
      case "TIMEOUT":
        return styles.interpretTimeout;
      default:
        return "";
    }
  };

  const isFormValid = formData.name.trim() && formData.code.trim();

  // ── Footer (matches Tool page: left toggle + right buttons) ──
  const renderFooter = () => (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "flex-end", width: "100%", gap: "12px" }}>
      <IAFButton type="secondary" onClick={closeModal}>
        Cancel
      </IAFButton>
      {isEditMode && (
        <IAFButton type="primary" onClick={() => setShowDeleteConfirm(true)}>
          Delete
        </IAFButton>
      )}
      <IAFButton
        type="primary"
        onClick={isEditMode ? handleUpdate : handleCreate}
        disabled={!isFormValid || saving}
        loading={saving}
      >
        {isEditMode ? "Update Hook" : "Create Hook"}
      </IAFButton>
    </div>
  );

  // ── Test Side Panel (opens on right like Tool page) ──
  const renderTestSidePanel = () => {
    if (!showTestPanel) return null;
    return (
      <div className={styles.testPanel} style={{ height: "100%", margin: 0, borderRadius: 0, border: "none" }}>
        <div className={styles.testPanelHeader}>
          <span className={styles.testPanelTitle}>
            <SVGIcons icon="play" width={14} height={14} /> Dry-Run Test
          </span>
          <button
            type="button"
            onClick={() => setShowTestPanel(false)}
            style={{ background: "none", border: "none", cursor: "pointer", padding: 4, color: "var(--content-color)", display: "flex", alignItems: "center" }}
            title="Close"
          >
            <SVGIcons icon="close-icon" width={16} height={16} />
          </button>
        </div>

        <div className={styles.formRow}>
          <div className="formGroup">
            <NewCommonDropdown
              label="Tool Name"
              options={TEST_TOOLS}
              selected={testInput.tool_name}
              onSelect={(val) => setTestInput((p) => ({ ...p, tool_name: val }))}
              placeholder="Select tool"
              showSearch={false}
            />
          </div>
          <div className="formGroup">
            <NewCommonDropdown
              label="Event"
              options={HOOK_EVENTS}
              selected={testInput.event}
              onSelect={(ev) => setTestInput((p) => ({ ...p, event: ev }))}
              placeholder="Select event"
              showSearch={false}
            />
          </div>
        </div>

        <div className="formGroup" style={{ marginTop: 8 }}>
          <label className="label-desc">Tool Input (JSON)</label>
          <TextField
            placeholder='{"query": "DELETE FROM users WHERE id=1"}'
            value={testInput.tool_input}
            onChange={(e) =>
              setTestInput((p) => ({ ...p, tool_input: e.target.value }))
            }
          />
        </div>

        <div style={{ marginTop: 12 }}>
          <IAFButton
            type="primary"
            onClick={handleTest}
            disabled={testing || !testInput.tool_name.trim()}
            loading={testing}
          >
            Run Test
          </IAFButton>
        </div>

        {testResult && (
          <div className={styles.testResult}>
            <div className={styles.testResultRow}>
              <span className={styles.testResultLabel}>Exit Code</span>
              <span className={styles.testResultValue}>{testResult.exit_code}</span>
            </div>
            <div className={styles.testResultRow}>
              <span className={styles.testResultLabel}>Interpretation</span>
              <span className={`${styles.interpretBadge} ${getInterpretClass(testResult.interpretation)}`}>
                {testResult.interpretation}
              </span>
            </div>
            {testResult.stdout && (
              <div className={styles.testResultRow}>
                <span className={styles.testResultLabel}>stdout</span>
                <span className={styles.testResultValue}>{testResult.stdout}</span>
              </div>
            )}
            {testResult.stderr && (
              <div className={styles.testResultRow}>
                <span className={styles.testResultLabel}>stderr</span>
                <span className={styles.testResultValue}>{testResult.stderr}</span>
              </div>
            )}
          </div>
        )}
      </div>
    );
  };

  // ── Render ─────────────────────────────────────────
  return (
    <div className="pageContainer">
      <SubHeader
        heading="Hooks"
        activeTab="hooks"
        onSearch={handleSearch}
        searchValue={searchTerm}
        clearSearch={clearSearch}
        handleRefresh={fetchHooks}
        onPlusClick={openCreateModal}
        plusButtonLabel="New Hook"
      />

      <SummaryLine visibleCount={filteredHooks.length} totalCount={hooks.length} />

      <PageLayout>
        {loading ? (
          <div className={styles.loadingWrap}>
            <Loader />
          </div>
        ) : filteredHooks.length > 0 ? (
          <DisplayCard1
            data={hooksForCards}
            onCardClick={(name, item) => openEditModal(item)}
            cardNameKey="name"
            cardDescriptionKey="description"
            cardCategoryKey="card_tag"
            cardOwnerKey="created_by"
            contextType="hook"
            idKey="hook_id"
            showCreateCard={false}
            showCheckbox={false}
            showDeleteButton={false}
            hideActions={false}
            onInfoClick={(item) => openEditModal(item)}
            loading={false}
          />
        ) : searchTerm.trim() ? (
          <EmptyState
            filters={[`Search: ${searchTerm}`]}
            onClearFilters={clearSearch}
            onCreateClick={openCreateModal}
            createButtonLabel="New Hook"
          />
        ) : (
          <EmptyState
            message="No hooks in the repository"
            subMessage="Get started by creating your first hook"
            onCreateClick={openCreateModal}
            createButtonLabel="New Hook"
            showClearFilter={false}
          />
        )}
      </PageLayout>

      {/* ── Create / Edit FullModal ─────────────────── */}
      <FullModal
        isOpen={modalOpen}
        onClose={closeModal}
        title={isEditMode ? (formData.name || "Update Hook") : "Create Hook"}
        headerInfo={[
          ...(isEditMode ? [{ label: "Type", value: "Hook" }] : []),
          { label: "Created By", value: isEditMode ? (editHookMeta?.created_by || "") : userName },
        ]}
        loading={saving}
        footer={renderFooter()}
        splitLayout={showTestPanel}
        sidePanel={renderTestSidePanel()}
        splitHeaderLabels={showTestPanel ? { left: "Configuration", right: "Dry-Run Test" } : null}
      >
        <form className="form-section" onSubmit={(e) => e.preventDefault()}>
          <div className="formContent" style={{ paddingTop: 0 }}>
            <div className="form" style={{ gap: "4px" }}>

              {/* ── Basic Info ── */}
              {!isEditMode && (
                <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                  <div className={`${styles.formRow} ${styles.fullWidth}`}>
                    <div className="formGroup">
                      <label className="label-desc">
                        Name <span className="required">*</span>
                      </label>
                      <TextField
                        placeholder="e.g. SQL Injection Scanner"
                        value={formData.name}
                        onChange={(e) => handleFieldChange("name", e.target.value)}
                      />
                    </div>
                  </div>
                </div>
              )}

              <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                <TextareaWithActions
                  name="description"
                  value={formData.description}
                  onChange={(e) => handleFieldChange("description", e.target.value)}
                  label="Description"
                  placeholder="What does this hook do?"
                  rows={3}
                  onZoomSave={(updatedContent) => handleFieldChange("description", updatedContent)}
                />
              </div>

              {/* ── Code Editor (matches ToolOnBoarding layout) ── */}
              <div className="formGroup" style={{ marginTop: 0, marginBottom: 0 }}>
                {/* Editor Header Row — mimics CodeEditor native labelContainer */}
                <div className={styles.editorHeaderRow}>
                  <div className={styles.editorHeaderLeft}>
                    <span className={styles.editorLabel}>Hook Script (Python)</span>
                    <button
                      type="button"
                      className={styles.editorUploadBtn}
                      onClick={handleUploadClick}
                      title="Upload .py file"
                    >
                      +
                    </button>
                    <span className={styles.editorHelperText}>(drag & drop / upload .py file / type directly)</span>
                  </div>
                </div>
                <div className={styles.codeEditorWrapper}>
                  <CodeEditor
                    codeToDisplay={formData.code}
                    onChange={(val) => handleFieldChange("code", val)}
                    mode="python"
                    readOnly={false}
                    enableDragDrop={true}
                    acceptedFileTypes={['.py']}
                    showUploadButton={false}
                    showHelperText={false}
                    showLanguageBadge={true}
                    placeholder="#!/usr/bin/env python3\nimport os, sys, json\n\n# Your hook logic here\nsys.exit(0)  # 0=ALLOW, 1=BLOCK, 2=APPROVAL_REQUIRED"
                    fontSize={13}
                  />
                  {/* Action buttons on the editor's inner header (Python badge row) */}
                  <div className={styles.editorInnerActions}>
                    <button
                      type="button"
                      className={styles.editorHeaderBtn}
                      onClick={() => setShowSampleHooks(true)}
                      title="Browse sample hook templates"
                    >
                      <SVGIcons icon="code" width={13} height={13} />
                      Sample Hooks
                    </button>
                    {isEditMode && (
                      <button
                        type="button"
                        className={styles.playIcon}
                        onClick={() => setShowTestPanel((prev) => !prev)}
                        title={showTestPanel ? "Hide dry-run test" : "Dry-run test"}
                      >
                        <SVGIcons icon="lucide-play" width={16} height={16} stroke="var(--icon-color)" fill="none" />
                      </button>
                    )}
                    <button
                      type="button"
                      className={styles.copyIcon}
                      onClick={handleCopyCode}
                      title="Copy code"
                      disabled={!formData.code || formData.code.trim() === ""}
                      style={{ opacity: !formData.code || formData.code.trim() === "" ? 0.4 : 1, cursor: !formData.code || formData.code.trim() === "" ? "not-allowed" : "pointer" }}
                    >
                      <SVGIcons icon="fa-regular fa-copy" width={16} height={16} fill="var(--icon-color)" />
                    </button>
                  </div>
                  <input
                    ref={codeFileInputRef}
                    type="file"
                    accept=".py"
                    style={{ display: "none" }}
                    onChange={handleFileUpload}
                  />
                  <div className={styles.iconGroup}>
                    <button type="button" className={styles.expandIcon} onClick={() => setShowZoomPopup(true)} title="Expand">
                      <SVGIcons icon="fa-solid fa-up-right-and-down-left-from-center" width={16} height={16} fill="var(--icon-color)" />
                    </button>
                  </div>
                  {codeCopied && (
                    <span className={styles.copiedText}>Copied!</span>
                  )}
                </div>
              </div>

              {/* Test panel moved to right side panel */}

            </div>
          </div>
        </form>
      </FullModal>

      {/* ── Delete Confirm ────────────────────────────── */}
      {showDeleteConfirm && (
        <ConfirmationModal
          message={`Are you sure you want to delete hook "${formData.name || editHookId}"? This action cannot be undone.`}
          onConfirm={handleDelete}
          setShowConfirmation={setShowDeleteConfirm}
          loading={deleting}
        />
      )}

      {/* ── Sample Hooks Modal ────────────────────────── */}
      {/* ── Zoom Popup ─────────────────────────────── */}
      <ZoomPopup
        show={showZoomPopup}
        onClose={() => setShowZoomPopup(false)}
        title="Hook Script (Python)"
        content={formData.code}
        onSave={(updatedContent) => {
          handleFieldChange("code", updatedContent);
          setShowZoomPopup(false);
        }}
        type="code"
        readOnly={false}
      />

      <SampleHooksModal
        isOpen={showSampleHooks}
        onClose={() => setShowSampleHooks(false)}
        onUseTemplate={(template) => {
          setFormData((prev) => ({
            ...prev,
            name: template.name || prev.name,
            code: template.code || prev.code,
            description: template.description || prev.description,
          }));
          addMessage("Template applied! You can edit before saving.", "success");
        }}
      />
    </div >
  );
};

export default HookRepository;
