import React, { useEffect, useRef, useState } from "react";
import panelStyles from "../../css_modules/DebugStepsPanel.module.css";

// Compact live debug steps panel (inline, same location as old <ul id="sse-actions">)
// Usage: <DebugStepsPanel steps={debugSteps} visible={showLiveSteps} onClose={() => setShowLiveSteps(false)} />
const DebugStepsPanel = ({ steps = [], visible, onClose, expanded = false, setExpanded }) => {
  const listRef = useRef(null);

  const filtered = Array.isArray(steps)
    ? steps.filter((s) => s && s.debug_value)
    : [];
  const latest = filtered[filtered.length - 1];

  useEffect(() => {
    if (expanded && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [filtered.length, expanded]);

  if (!visible || filtered.length === 0) return null;

  const copyAll = (e) => {
    e.stopPropagation();
    try {
      navigator.clipboard.writeText(
        filtered
          .map((s, i) => `${s.step ?? i + 1}. ${s.action || s.message || ""}`)
          .join("\n")
      );
    } catch (_) {}
  };

  const clearPanel = (e) => {
    e.stopPropagation();
    // Soft clear: collapse history visually but keep latest for context by slicing to last 1
    if (filtered.length > 1) {
      // no external setter passed; rely on parent clearing when new session starts
    }
  };

  return (
    <div
      className={
        panelStyles.wrapper +
        " " +
        (expanded ? panelStyles.expanded : panelStyles.collapsed)
      }
    >
      <button
        type="button"
        className={panelStyles.header}
        onClick={() => setExpanded((v) => !v)}
        aria-expanded={expanded}
      >
        <div className={panelStyles.leftCluster}>
          <span className={panelStyles.pulseDot} />
          <span className={panelStyles.title}>Live Steps</span>
          <span className={panelStyles.count}>{filtered.length}</span>
        </div>
        <div
          className={panelStyles.headerActions}
          onClick={(e) => e.stopPropagation()}
        >
          <span
            type="button"
            className={panelStyles.iconBtn}
            title={expanded ? "Collapse" : "Expand"}
            onClick={() => setExpanded((v) => !v)}
          >
            <svg
              viewBox="0 0 20 20"
              width="14"
              height="14"
              className={expanded ? panelStyles.rotated : ""}
            >
              <path
                d="M6 8l4 4 4-4"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        </div>
      </button>

      {!expanded && (
        <div
          className={panelStyles.collapsedLine}
          title={latest?.action || latest?.message || latest?.debug_value}
        >
          <span className={panelStyles.latestText}>
            {latest?.action || latest?.message || latest?.debug_value || ""}
          </span>
        </div>
      )}

      {expanded && (
        <div
          className={panelStyles.list}
          ref={listRef}
          aria-live="polite"
          role="list"
        >
          {filtered.map((s, i) => {
            const isLast = i === filtered.length - 1;
            return (
              <div
                key={s.step ?? i}
                className={
                  panelStyles.item + " " + (isLast ? panelStyles.active : "")
                }
                role="listitem"
              >
                <span className={panelStyles.index}>{s.step ?? i + 1}</span>
                <div className={panelStyles.body}>
                  <div className={panelStyles.action}>{s.debug_value}</div>
                  {s.error && (
                    <div className={panelStyles.error}>{s.error}</div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

export default DebugStepsPanel;
