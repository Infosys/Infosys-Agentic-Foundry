import React, { useEffect, useState, useRef, useCallback } from "react";
import { useToolsAgentsService } from "../../services/toolService";
import { useMessage } from "../../Hooks/MessageContext";
import styles from "../../css_modules/AgentOnboard.module.css";
import InfoTag from "../commonComponents/InfoTag";


export default function ValidatorPatternsGroup({ value = [], onChange, disabled = false }) {
  const { getValidatorTools } = useToolsAgentsService();
  const { addMessage } = useMessage();
  const [validators, setValidators] = useState([]);
  const [fetchError, setFetchError] = useState(null);
  const [rows, setRows] = useState(() => (value && value.length > 0 ? value : []));
  // Track if user has edited to avoid clobbering manual input with late async prop updates
  const userEditedRef = useRef(false);
  const [loadingValidators, setLoadingValidators] = useState(false);

  // Normalization helpers
  const normalizeArray = (input) => {
    if (Array.isArray(input)) return input;
    if (!input || typeof input !== "object") return [];
    const directKeys = ["data", "details", "validators", "tools", "items", "result", "results", "payload", "list", "validator_tools", "validator_list", "tool_list"];
    for (const k of directKeys) {
      if (Array.isArray(input[k])) return input[k];
    }
    // Deep search arrays
    const collected = [];
    const seen = new Set();
    const q = [input];
    while (q.length) {
      const cur = q.shift();
      if (!cur || typeof cur !== "object" || seen.has(cur)) continue;
      seen.add(cur);
      if (Array.isArray(cur)) {
        if (cur.length) collected.push(cur);
      } else {
        Object.values(cur).forEach(v => {
          if (Array.isArray(v)) collected.push(v);
          else if (v && typeof v === "object") q.push(v);
        });
      }
    }
    // Choose best candidate: one containing tool-like shape
    const toolLike = collected.find(arr => arr.some(o => o && typeof o === "object" && (o.tool_id || o.validator_id || o.id || Object.keys(o).some(k => k.endsWith("_id")))));
    return toolLike || collected[0] || [];
  };

  const standardize = (list) => list
    .map(v => {
      if (!v || typeof v !== "object") return null;
      const dynamicIdKey = Object.keys(v).find(k => k.endsWith("_id"));
      const id = v.tool_id || v.validator_id || v.id || v.server_id || v.mcp_id || (dynamicIdKey ? v[dynamicIdKey] : null);
      const name = v.tool_name || v.validator_name || v.name || v.server_name || v.display_name || id;
      if (!id) return null;
      return { ...v, tool_id: id, tool_name: name };
    })
    .filter(Boolean);

  const fetchedRef = useRef(false);
  // Safe dev detection (no direct process reference that could throw in some bundlers)
  const isDev = typeof window !== "undefined" && (window.__IAF_DEV__ || (typeof process !== "undefined" && process.env && process.env.NODE_ENV !== "production"));

  const fetchValidators = useCallback(async () => {
    setLoadingValidators(true);
    setFetchError(null);
    try {
      const res = await getValidatorTools();
      const raw = res?.data ?? res;
      let arr = normalizeArray(raw);
      arr = standardize(arr);
      if (isDev) console.debug("[ValidatorPatternsGroup] fetched validators", arr);
      setValidators(arr);
    } catch (e) {
      setFetchError(e?.message || "Failed to load validators");
       addMessage("Failed to load validator tools", "error");
    } finally {
      setLoadingValidators(false);
    }
  }, [getValidatorTools, addMessage, isDev]);

  useEffect(() => {
    if (fetchedRef.current) return;
    fetchedRef.current = true;
    fetchValidators();
  }, [fetchValidators]);

  // Removed unconditional echo of rows to parent to prevent infinite loop.
  // We'll only notify parent when user actually edits rows.

  // Prop -> state sync (after async fetch in UpdateAgent). Only apply if user hasn't started editing.
  useEffect(() => {
    // Sync incoming prop only if user hasn't started editing AND it's actually different.
    if (userEditedRef.current) return;
    if (Array.isArray(value) && value.length > 0) {
      const normalized = value.map(v => ({
        query: v.query || "",
        expected_answer: v.expected_answer || "",
        validator: v.validator || null,
      }));
      // Shallow equality check to avoid redundant setState.
      const isSame = normalized.length === rows.length && normalized.every((nv, i) => {
        const rv = rows[i];
        return nv.query === rv.query && nv.expected_answer === rv.expected_answer && nv.validator === rv.validator;
      });
      if (!isSame) {
        setRows(normalized);
      }
    }
  }, [value, rows]);

  const notifyParent = useCallback((next) => {
    if (!onChange) return;
    onChange(next);
  }, [onChange]);

  const addRow = () => {
    userEditedRef.current = true;
    // Only allow one empty row at a time
    if (rows.length === 0 || (rows[rows.length - 1].query && rows[rows.length - 1].expected_answer && rows[rows.length - 1].expected_answer.toLowerCase() !== "none")) {
      setRows(r => [...r, { query: "", expected_answer: "", validator: null }]);
      notifyParent([...rows, { query: "", expected_answer: "", validator: null }]);
    }
  };
  const updateRow = (i, patch) => {
    userEditedRef.current = true;
    setRows(r => {
      const next = r.map((row, idx) => (idx === i ? { ...row, ...patch } : row));
      notifyParent(next);
      return next;
    });
  };
  const removeRow = (i) => {
    userEditedRef.current = true;
    setRows(r => r.filter((_, idx) => idx !== i));
    notifyParent(rows.filter((_, idx) => idx !== i));
  };

  return (
    <div className={styles.validatorGroup} aria-disabled={disabled}>
      <div className={styles.validatorHeader}>
        <h3>Validation Patterns (Optional) 
          <InfoTag message="Provide validator for the agent" />
        </h3>
        {!disabled && (
          <button
            type="button"
            onClick={addRow}
            className={styles.addBtn}
            disabled={
              disabled ||
              (rows.length > 0 && (
                !rows[rows.length - 1].query.trim() ||
                !rows[rows.length - 1].expected_answer.trim() ||
                rows[rows.length - 1].expected_answer.trim().toLowerCase() === "none" ||
                rows.filter(row => !row.query.trim() && (!row.expected_answer.trim() || row.expected_answer.trim().toLowerCase() === "none")).length > 0
              ))
            }
            aria-label="Add validation pattern"
            style={{ alignSelf: "flex-start" }}
          >
            +
          </button>
        )}
      </div>
      {rows.map((row, idx) => (
        <div className={styles.validatorRow} key={idx}>
          <div className={styles.col}>
            <label>Query<span style={{color: "#b91c1c"}}>*</span></label>
            <input
              type="text"
              value={row.query}
              onChange={(e) => updateRow(idx, { query: e.target.value })}
              disabled={disabled}
              placeholder="Enter query"
              required
            />
          </div>
          <div className={styles.col}>
            <label>Expected Answer<span style={{color: "#b91c1c"}}>*</span></label>
            <input
              type="text"
              value={row.expected_answer}
              onChange={(e) => updateRow(idx, { expected_answer: e.target.value })}
              disabled={disabled}
              placeholder="Expected answer"
              required
            />
          </div>
          <div className={styles.col}>
            <label>Validator (Optional)</label>
            <select
              value={row.validator || ""}
              onChange={(e) => updateRow(idx, { validator: e.target.value || null })}
              disabled={disabled || loadingValidators}
              title={loadingValidators ? "Loading validators" : validators.length === 0 ? (fetchError ? fetchError : "No validators found") : "Select validator"}
            >
              <option value="">{loadingValidators ? "Loading..." : validators.length === 0 ? "No validators" : "None"}</option>
              {validators.map(v => (
                <option key={v.tool_id} value={v.tool_id}>{v.tool_name}</option>
              ))}
            </select>
            {fetchError && !loadingValidators && validators.length === 0 && (
              <div style={{ color: "#b91c1c", fontSize: 12, marginTop: 4 }}>{fetchError}</div>
            )}
          </div>
          <div className={styles.colSmall} style={{ display: "flex", alignItems: "flex-end" }}>
            {!disabled && (
              <button
                type="button"
                onClick={() => removeRow(idx)}
                className={styles.removeBtn}
                aria-label="Remove validation pattern"
                style={{ height: 32 }}
              >
                ✕
              </button>
            )}
          </div>
        </div>
      ))}
    </div>
  );
}
