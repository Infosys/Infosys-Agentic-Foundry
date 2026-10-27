"""SQLite store for framework-neutral RL/eval capture data."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
try:
    from iaf_agent_skills.sqlite_util import connect as _sqlite_connect
except ImportError:
    _sqlite_connect = None
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from rl_capture.core.schema import (
    CandidateOutput,
    DatasetExport,
    EvaluatorResult,
    ModelCall,
    Observation,
    PreferenceSignal,
    RewardEvent,
    ShadowRun,
    TraceRouteDecision,
    TraceValueAssessment,
    ToolCall,
    Trajectory,
    to_jsonable,
)


DB_NAME = "rl.db"
STORE_SCHEMA_VERSION = 3

_VALID_RL_TABLES = frozenset({
    "trajectories", "trajectory_steps", "model_calls", "tool_calls",
    "observations", "reward_events", "preference_signals",
    "candidate_outputs", "evaluator_results", "shadow_runs", "exports",
    "schema_migrations",
    "trace_value_assessments", "trace_route_decisions",
})


def _validated_rl_table(name: str) -> str:
    """Validate table name against allowlist to prevent SQL injection."""
    if name not in _VALID_RL_TABLES:
        raise ValueError("Invalid table name: %s" % name)
    return name


def _sql_where(conditions: list) -> str:
    """Build a WHERE clause from validated condition strings."""
    if not conditions:
        return ""
    return "WHERE " + " AND ".join(conditions)


def tenant_rl_db_path(data_root: str | Path, tenant_id: str) -> Path:
    return (
        Path(data_root)
        / "tenants"
        / tenant_id
        / "shared"
        / "databases"
        / DB_NAME
    ).resolve()


@dataclass
class RLStore:
    db_path: Path

    def __post_init__(self) -> None:
        self.db_path = Path(self.db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ensure_schema()

    def _connect(self) -> sqlite3.Connection:
        if _sqlite_connect is not None:
            conn = _sqlite_connect(self.db_path)
        else:
            conn = sqlite3.connect(str(self.db_path), timeout=30)
            conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _ensure_schema(self) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS schema_migrations (
                        version INTEGER PRIMARY KEY,
                        applied_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS trajectories (
                        id TEXT PRIMARY KEY,
                        tenant_id TEXT,
                        agent_id TEXT,
                        session_id TEXT,
                        task TEXT,
                        fidelity TEXT,
                        terminal_status TEXT,
                        started_at TEXT,
                        ended_at TEXT,
                        capture_time TEXT,
                        trajectory_json TEXT NOT NULL,
                        metadata_json TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_trajectories_tenant ON trajectories(tenant_id);
                    CREATE INDEX IF NOT EXISTS idx_rl_trajectories_session ON trajectories(session_id);

                    CREATE TABLE IF NOT EXISTS trajectory_steps (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT NOT NULL,
                        step_index INTEGER,
                        kind TEXT,
                        target_json TEXT NOT NULL,
                        metadata_json TEXT,
                        FOREIGN KEY (trajectory_id) REFERENCES trajectories(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_steps_trajectory ON trajectory_steps(trajectory_id);

                    CREATE TABLE IF NOT EXISTS model_calls (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        provider TEXT,
                        model TEXT,
                        fidelity TEXT,
                        prompt_tokens INTEGER,
                        completion_tokens INTEGER,
                        cost_usd REAL,
                        latency_ms INTEGER,
                        model_call_json TEXT NOT NULL,
                        FOREIGN KEY (trajectory_id) REFERENCES trajectories(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_model_calls_trajectory ON model_calls(trajectory_id);

                    CREATE TABLE IF NOT EXISTS tool_calls (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        name TEXT,
                        status TEXT,
                        duration_ms INTEGER,
                        tool_call_json TEXT NOT NULL,
                        FOREIGN KEY (trajectory_id) REFERENCES trajectories(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_tool_calls_trajectory ON tool_calls(trajectory_id);

                    CREATE TABLE IF NOT EXISTS observations (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        source TEXT,
                        observation_json TEXT NOT NULL,
                        FOREIGN KEY (trajectory_id) REFERENCES trajectories(id)
                    );

                    CREATE TABLE IF NOT EXISTS reward_events (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        target_type TEXT,
                        target_id TEXT,
                        channel TEXT,
                        raw_label TEXT,
                        raw_value REAL,
                        confidence REAL,
                        reward_json TEXT NOT NULL,
                        created_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_rewards_trajectory ON reward_events(trajectory_id);
                    CREATE INDEX IF NOT EXISTS idx_rl_rewards_channel ON reward_events(channel);

                    CREATE TABLE IF NOT EXISTS preference_signals (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        provenance TEXT,
                        channel TEXT,
                        preference_json TEXT NOT NULL,
                        created_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_preferences_trajectory ON preference_signals(trajectory_id);

                    CREATE TABLE IF NOT EXISTS candidate_outputs (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT NOT NULL,
                        kind TEXT,
                        source TEXT,
                        candidate_json TEXT NOT NULL,
                        created_at TEXT,
                        FOREIGN KEY (trajectory_id) REFERENCES trajectories(id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_candidates_trajectory ON candidate_outputs(trajectory_id);
                    CREATE INDEX IF NOT EXISTS idx_rl_candidates_kind ON candidate_outputs(kind);

                    CREATE TABLE IF NOT EXISTS evaluator_results (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        rubric TEXT,
                        evaluator_json TEXT NOT NULL,
                        created_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_evaluators_trajectory ON evaluator_results(trajectory_id);

                    CREATE TABLE IF NOT EXISTS trace_value_assessments (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        input_hash TEXT,
                        rubric TEXT,
                        quality_score REAL,
                        quality_verdict TEXT,
                        top_destination TEXT,
                        debug_only INTEGER DEFAULT 0,
                        assessment_json TEXT NOT NULL,
                        created_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_trace_value_trajectory ON trace_value_assessments(trajectory_id);
                    CREATE INDEX IF NOT EXISTS idx_rl_trace_value_destination ON trace_value_assessments(top_destination);
                    CREATE UNIQUE INDEX IF NOT EXISTS idx_rl_trace_value_hash ON trace_value_assessments(trajectory_id, input_hash, rubric);

                    CREATE TABLE IF NOT EXISTS trace_route_decisions (
                        id TEXT PRIMARY KEY,
                        trajectory_id TEXT,
                        assessment_id TEXT,
                        destination TEXT,
                        action TEXT,
                        status TEXT,
                        reviewer TEXT,
                        target_ref TEXT,
                        decision_json TEXT NOT NULL,
                        created_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_rl_trace_routes_trajectory ON trace_route_decisions(trajectory_id);
                    CREATE INDEX IF NOT EXISTS idx_rl_trace_routes_destination ON trace_route_decisions(destination);

                    CREATE TABLE IF NOT EXISTS shadow_runs (
                        id TEXT PRIMARY KEY,
                        baseline_trajectory_id TEXT,
                        candidate_provider TEXT,
                        candidate_model TEXT,
                        shadow_json TEXT NOT NULL,
                        created_at TEXT
                    );

                    CREATE TABLE IF NOT EXISTS exports (
                        id TEXT PRIMARY KEY,
                        kind TEXT,
                        params_json TEXT,
                        file_path TEXT,
                        checksum TEXT,
                        row_count INTEGER,
                        export_json TEXT NOT NULL,
                        created_at TEXT
                    );
                    """
                )
                conn.execute(
                    "INSERT OR IGNORE INTO schema_migrations (version, applied_at) VALUES (?, datetime('now'))",
                    (STORE_SCHEMA_VERSION,),
                )
                conn.commit()
            finally:
                conn.close()

    def record_trajectory(self, trajectory: Trajectory) -> None:
        payload = to_jsonable(trajectory)
        tenant_id = trajectory.capture.tenant_id or trajectory.tenant or ""
        agent_id = trajectory.capture.agent_id or ""
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO trajectories (
                        id, tenant_id, agent_id, session_id, task, fidelity,
                        terminal_status, started_at, ended_at, capture_time,
                        trajectory_json, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        trajectory.id,
                        tenant_id,
                        agent_id,
                        trajectory.session_id,
                        trajectory.task,
                        trajectory.fidelity.value,
                        trajectory.terminal_status,
                        trajectory.started_at,
                        trajectory.ended_at,
                        trajectory.capture.capture_time,
                        json.dumps(payload, ensure_ascii=False, default=str),
                        json.dumps(trajectory.metadata, ensure_ascii=False, default=str),
                    ),
                )
                self._replace_children(conn, trajectory)
                conn.commit()
            finally:
                conn.close()

    def _replace_children(self, conn: sqlite3.Connection, trajectory: Trajectory) -> None:
        # Steps are owned by this write; model/tool rows may arrive incrementally, so INSERT OR REPLACE below.
        conn.execute("DELETE FROM trajectory_steps WHERE trajectory_id = ?", (trajectory.id,))
        for step in trajectory.steps:
            conn.execute(
                """
                INSERT INTO trajectory_steps (id, trajectory_id, step_index, kind, target_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    step.id,
                    trajectory.id,
                    step.index,
                    step.kind.value,
                    json.dumps(to_jsonable(step), ensure_ascii=False, default=str),
                    json.dumps(step.metadata, ensure_ascii=False, default=str),
                ),
            )
        for model_call in trajectory.model_calls:
            conn.execute(
                """
                INSERT OR REPLACE INTO model_calls (
                    id, trajectory_id, provider, model, fidelity, prompt_tokens,
                    completion_tokens, cost_usd, latency_ms, model_call_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    model_call.id,
                    trajectory.id,
                    model_call.policy.provider,
                    model_call.policy.model,
                    model_call.fidelity.value,
                    model_call.prompt_tokens,
                    model_call.completion_tokens,
                    model_call.cost_usd,
                    model_call.latency_ms,
                    json.dumps(to_jsonable(model_call), ensure_ascii=False, default=str),
                ),
            )
        for tool_call in trajectory.tool_calls:
            conn.execute(
                """
                INSERT OR REPLACE INTO tool_calls (id, trajectory_id, name, status, duration_ms, tool_call_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    tool_call.id,
                    trajectory.id,
                    tool_call.name,
                    tool_call.status,
                    tool_call.duration_ms,
                    json.dumps(to_jsonable(tool_call), ensure_ascii=False, default=str),
                ),
            )
        for observation in trajectory.observations:
            conn.execute(
                """
                INSERT OR REPLACE INTO observations (id, trajectory_id, source, observation_json)
                VALUES (?, ?, ?, ?)
                """,
                (
                    observation.id,
                    trajectory.id,
                    observation.source,
                    json.dumps(to_jsonable(observation), ensure_ascii=False, default=str),
                ),
            )

    def record_model_call(self, trajectory_id: str, model_call: ModelCall) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO trajectories (
                        id, tenant_id, agent_id, session_id, task, fidelity,
                        terminal_status, started_at, ended_at, capture_time,
                        trajectory_json, metadata_json
                    ) VALUES (?, '', '', '', '', ?, 'partial', NULL, NULL, datetime('now'), ?, '{}')
                    """,
                    (
                        trajectory_id,
                        model_call.fidelity.value,
                        json.dumps({"id": trajectory_id, "terminal_status": "partial"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO model_calls (
                        id, trajectory_id, provider, model, fidelity, prompt_tokens,
                        completion_tokens, cost_usd, latency_ms, model_call_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        model_call.id,
                        trajectory_id,
                        model_call.policy.provider,
                        model_call.policy.model,
                        model_call.fidelity.value,
                        model_call.prompt_tokens,
                        model_call.completion_tokens,
                        model_call.cost_usd,
                        model_call.latency_ms,
                        json.dumps(to_jsonable(model_call), ensure_ascii=False, default=str),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def record_tool_call(self, trajectory_id: str, tool_call: ToolCall) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO trajectories (
                        id, tenant_id, agent_id, session_id, task, fidelity,
                        terminal_status, started_at, ended_at, capture_time,
                        trajectory_json, metadata_json
                    ) VALUES (?, '', '', '', '', 'text_only', 'partial', NULL, NULL, datetime('now'), ?, '{}')
                    """,
                    (
                        trajectory_id,
                        json.dumps({"id": trajectory_id, "terminal_status": "partial"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO tool_calls (id, trajectory_id, name, status, duration_ms, tool_call_json)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tool_call.id,
                        trajectory_id,
                        tool_call.name,
                        tool_call.status,
                        tool_call.duration_ms,
                        json.dumps(to_jsonable(tool_call), ensure_ascii=False, default=str),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def record_observation(self, trajectory_id: str, observation: Observation) -> None:
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO trajectories (
                        id, tenant_id, agent_id, session_id, task, fidelity,
                        terminal_status, started_at, ended_at, capture_time,
                        trajectory_json, metadata_json
                    ) VALUES (?, '', '', '', '', 'text_only', 'partial', NULL, NULL, datetime('now'), ?, '{}')
                    """,
                    (
                        trajectory_id,
                        json.dumps({"id": trajectory_id, "terminal_status": "partial"}, ensure_ascii=False),
                    ),
                )
                conn.execute(
                    """
                    INSERT OR REPLACE INTO observations (id, trajectory_id, source, observation_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        observation.id,
                        trajectory_id,
                        observation.source,
                        json.dumps(to_jsonable(observation), ensure_ascii=False, default=str),
                    ),
                )
                conn.commit()
            finally:
                conn.close()

    def record_reward_event(self, reward: RewardEvent) -> None:
        self._insert_json_row(
            "reward_events",
            (
                "id",
                "trajectory_id",
                "target_type",
                "target_id",
                "channel",
                "raw_label",
                "raw_value",
                "confidence",
                "reward_json",
                "created_at",
            ),
            (
                reward.id,
                reward.target.trajectory_id,
                reward.target.target_type.value,
                reward.target.target_id,
                reward.channel.value,
                reward.raw_label,
                reward.raw_value,
                reward.confidence,
                json.dumps(to_jsonable(reward), ensure_ascii=False, default=str),
                reward.created_at,
            ),
        )

    def record_preference_signal(self, preference: PreferenceSignal) -> None:
        self._insert_json_row(
            "preference_signals",
            ("id", "trajectory_id", "provenance", "channel", "preference_json", "created_at"),
            (
                preference.id,
                preference.context_ref.trajectory_id,
                preference.provenance.value,
                preference.channel.value,
                json.dumps(to_jsonable(preference), ensure_ascii=False, default=str),
                preference.created_at,
            ),
        )

    def record_candidate_output(self, candidate: CandidateOutput) -> None:
        self._insert_json_row(
            "candidate_outputs",
            ("id", "trajectory_id", "kind", "source", "candidate_json", "created_at"),
            (
                candidate.id,
                candidate.trajectory_id,
                candidate.kind.value,
                candidate.source,
                json.dumps(to_jsonable(candidate), ensure_ascii=False, default=str),
                candidate.created_at,
            ),
        )

    def record_evaluator_result(self, evaluator_result: EvaluatorResult) -> None:
        self._insert_json_row(
            "evaluator_results",
            ("id", "trajectory_id", "rubric", "evaluator_json", "created_at"),
            (
                evaluator_result.id,
                evaluator_result.target.trajectory_id,
                evaluator_result.rubric,
                json.dumps(to_jsonable(evaluator_result), ensure_ascii=False, default=str),
                evaluator_result.created_at,
            ),
        )

    def record_trace_value_assessment(self, assessment: TraceValueAssessment | dict) -> None:
        payload = to_jsonable(assessment)
        destinations = payload.get("destinations") or {}
        top_destination = _top_destination(destinations)
        quality = payload.get("quality") or {}
        self._insert_json_row(
            "trace_value_assessments",
            (
                "id",
                "trajectory_id",
                "input_hash",
                "rubric",
                "quality_score",
                "quality_verdict",
                "top_destination",
                "debug_only",
                "assessment_json",
                "created_at",
            ),
            (
                payload.get("id"),
                payload.get("trajectory_id"),
                payload.get("input_hash"),
                payload.get("rubric"),
                quality.get("score"),
                quality.get("verdict"),
                top_destination,
                1 if float(destinations.get("debug_only") or 0) >= 0.5 else 0,
                json.dumps(payload, ensure_ascii=False, default=str),
                payload.get("created_at"),
            ),
        )

    def record_trace_route_decision(self, decision: TraceRouteDecision | dict) -> None:
        payload = to_jsonable(decision)
        self._insert_json_row(
            "trace_route_decisions",
            (
                "id",
                "trajectory_id",
                "assessment_id",
                "destination",
                "action",
                "status",
                "reviewer",
                "target_ref",
                "decision_json",
                "created_at",
            ),
            (
                payload.get("id"),
                payload.get("trajectory_id"),
                payload.get("assessment_id"),
                payload.get("destination"),
                payload.get("action"),
                payload.get("status"),
                payload.get("reviewer"),
                payload.get("target_ref"),
                json.dumps(payload, ensure_ascii=False, default=str),
                payload.get("created_at"),
            ),
        )

    def record_shadow_run(self, shadow_run: ShadowRun) -> None:
        self._insert_json_row(
            "shadow_runs",
            (
                "id",
                "baseline_trajectory_id",
                "candidate_provider",
                "candidate_model",
                "shadow_json",
                "created_at",
            ),
            (
                shadow_run.id,
                shadow_run.baseline_trajectory_id,
                shadow_run.candidate_policy.provider,
                shadow_run.candidate_policy.model,
                json.dumps(to_jsonable(shadow_run), ensure_ascii=False, default=str),
                shadow_run.created_at,
            ),
        )

    def record_export(self, dataset_export: DatasetExport) -> None:
        self._insert_json_row(
            "exports",
            ("id", "kind", "params_json", "file_path", "checksum", "row_count", "export_json", "created_at"),
            (
                dataset_export.id,
                dataset_export.kind,
                json.dumps(dataset_export.params, ensure_ascii=False, default=str),
                dataset_export.file_path,
                dataset_export.checksum,
                dataset_export.row_count,
                json.dumps(to_jsonable(dataset_export), ensure_ascii=False, default=str),
                dataset_export.created_at,
            ),
        )

    def _insert_json_row(self, table: str, columns: Iterable[str], values: tuple) -> None:
        validated_table = _validated_rl_table(table)
        column_list = list(columns)
        placeholders = ",".join("?" for _ in column_list)
        with self._lock:
            conn = self._connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO " + validated_table
                    + " (" + ",".join(column_list) + ") VALUES (" + placeholders + ")",
                    values,
                )
                conn.commit()
            finally:
                conn.close()

    def list_trajectories(
        self,
        *,
        limit: int = 100,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        fidelity: str | None = None,
    ) -> list[dict]:
        conn = self._connect()
        try:
            where: list[str] = []
            params: list[object] = []
            if tenant_id:
                where.append("tenant_id = ?")
                params.append(tenant_id)
            if agent_id:
                where.append("agent_id = ?")
                params.append(agent_id)
            if session_id:
                where.append("session_id = ?")
                params.append(session_id)
            if fidelity:
                where.append("fidelity = ?")
                params.append(fidelity)
            sql = "SELECT trajectory_json FROM trajectories"
            where_clause = _sql_where(where)
            if where_clause:
                sql += " " + where_clause
            sql += " ORDER BY capture_time DESC LIMIT ?"
            params.append(int(limit))
            rows = conn.execute(sql, params).fetchall()
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()

    def list_trajectories_with_trace_filters(
        self,
        *,
        limit: int = 100,
        tenant_id: str | None = None,
        session_id: str | None = None,
        assessment_status: str | None = None,
        destination: str | None = None,
        route_status: str | None = None,
        min_destination_score: float = 0.0,
        include_debug: bool = False,
    ) -> list[dict]:
        """Return trajectories joined to their latest Trace Value read model.

        With no minimum score, ``destination`` means the assessment's top
        destination (the same semantics as Trace Value queues). With a positive
        threshold, it matches the named destination's JSON score.
        """
        where: list[str] = []
        params: list[object] = []
        if tenant_id:
            where.append("t.tenant_id = ?")
            params.append(tenant_id)
        if session_id:
            where.append("t.session_id = ?")
            params.append(session_id)
        if assessment_status == "unassessed":
            where.append("a.id IS NULL")
        elif assessment_status == "debug_only":
            where.append("a.id IS NOT NULL AND a.debug_only = 1")
        elif assessment_status == "assessed":
            where.append("a.id IS NOT NULL AND a.debug_only = 0")
        if not include_debug and assessment_status != "debug_only":
            where.append("(a.id IS NULL OR a.debug_only = 0)")
        if destination:
            if float(min_destination_score or 0) > 0:
                where.append("CAST(json_extract(a.assessment_json, ?) AS REAL) >= ?")
                params.extend((f"$.destinations.{destination}", float(min_destination_score)))
            else:
                where.append("a.top_destination = ?")
                params.append(destination)
        if route_status:
            route_filter = [
                "r.trajectory_id = t.id",
                "LOWER(r.status) = LOWER(?)",
            ]
            params.append(route_status)
            if destination:
                route_filter.append("r.destination = ?")
                params.append(destination)
            where.append(
                "EXISTS (SELECT 1 FROM trace_route_decisions r WHERE "
                + " AND ".join(route_filter)
                + ")"
            )
        decision_filter: list[str] = ["r2.trajectory_id = t.id"]
        decision_params: list[object] = []
        if destination:
            decision_filter.append("r2.destination = ?")
            decision_params.append(destination)
        if route_status:
            decision_filter.append("LOWER(r2.status) = LOWER(?)")
            decision_params.append(route_status)
        sql = """
            WITH latest_assessment AS (
                SELECT *
                FROM (
                    SELECT a.*, ROW_NUMBER() OVER (
                        PARTITION BY a.trajectory_id
                        ORDER BY a.created_at DESC, a.id DESC
                    ) AS row_num
                    FROM trace_value_assessments a
                )
                WHERE row_num = 1
            )
            SELECT
                t.trajectory_json,
                a.assessment_json,
                (
                    SELECT r2.decision_json
                    FROM trace_route_decisions r2
                    WHERE %s
                    ORDER BY r2.created_at DESC, r2.id DESC
                    LIMIT 1
                ) AS decision_json
            FROM trajectories t
            LEFT JOIN latest_assessment a ON a.trajectory_id = t.id
        """ % " AND ".join(decision_filter)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY t.capture_time DESC LIMIT ?"
        query_params = [*decision_params, *params, int(limit)]
        conn = self._connect()
        try:
            rows = conn.execute(sql, query_params).fetchall()
            return [
                {
                    "trajectory": json.loads(row[0]),
                    "trace_value": json.loads(row[1]) if row[1] else None,
                    "route_decisions": [json.loads(row[2])] if row[2] else [],
                }
                for row in rows
            ]
        finally:
            conn.close()

    def get_trajectory(self, trajectory_id: str) -> dict | None:
        return self._get_json_by_id("trajectories", "id", trajectory_id, "trajectory_json")

    def get_model_call(self, model_call_id: str) -> dict | None:
        return self._get_json_by_id("model_calls", "id", model_call_id, "model_call_json")

    def get_tool_call(self, tool_call_id: str) -> dict | None:
        return self._get_json_by_id("tool_calls", "id", tool_call_id, "tool_call_json")

    def get_observation(self, observation_id: str) -> dict | None:
        return self._get_json_by_id("observations", "id", observation_id, "observation_json")

    def get_candidate_output(self, candidate_id: str) -> dict | None:
        return self._get_json_by_id("candidate_outputs", "id", candidate_id, "candidate_json")

    def list_model_calls(self, *, trajectory_id: str, limit: int = 500) -> list[dict]:
        return self._list_json_rows(
            "model_calls",
            "model_call_json",
            filters={"trajectory_id": trajectory_id},
            order_by="id ASC",
            limit=limit,
        )

    def list_tool_calls(self, *, trajectory_id: str, limit: int = 500) -> list[dict]:
        return self._list_json_rows(
            "tool_calls",
            "tool_call_json",
            filters={"trajectory_id": trajectory_id},
            order_by="id ASC",
            limit=limit,
        )

    def list_observations(self, *, trajectory_id: str, limit: int = 500) -> list[dict]:
        return self._list_json_rows(
            "observations",
            "observation_json",
            filters={"trajectory_id": trajectory_id},
            order_by="id ASC",
            limit=limit,
        )

    def list_reward_events(
        self,
        *,
        trajectory_id: str | None = None,
        channel: str | None = None,
        raw_label: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        return self._list_json_rows(
            "reward_events",
            "reward_json",
            filters={
                "trajectory_id": trajectory_id,
                "channel": channel,
                "raw_label": raw_label,
            },
            order_by="created_at DESC",
            limit=limit,
        )

    def list_preference_signals(
        self,
        *,
        trajectory_id: str | None = None,
        channel: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        return self._list_json_rows(
            "preference_signals",
            "preference_json",
            filters={"trajectory_id": trajectory_id, "channel": channel},
            order_by="created_at DESC",
            limit=limit,
        )

    def list_candidate_outputs(
        self,
        *,
        trajectory_id: str | None = None,
        kind: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        return self._list_json_rows(
            "candidate_outputs",
            "candidate_json",
            filters={"trajectory_id": trajectory_id, "kind": kind},
            order_by="created_at DESC",
            limit=limit,
        )

    def list_exports(self, *, kind: str | None = None, limit: int = 100) -> list[dict]:
        return self._list_json_rows(
            "exports",
            "export_json",
            filters={"kind": kind},
            order_by="created_at DESC",
            limit=limit,
        )

    def dataset_health(self) -> dict[str, int]:
        tables = [
            "trajectories",
            "trajectory_steps",
            "model_calls",
            "tool_calls",
            "observations",
            "candidate_outputs",
            "reward_events",
            "preference_signals",
            "evaluator_results",
            "trace_value_assessments",
            "trace_route_decisions",
            "shadow_runs",
            "exports",
        ]
        conn = self._connect()
        try:
            return {
                t: int(conn.execute(
                    "SELECT COUNT(*) FROM " + _validated_rl_table(t)
                ).fetchone()[0])
                for t in tables
            }
        finally:
            conn.close()

    def time_series(self, *, hours: int = 24) -> dict[str, list[dict]]:
        """Return hourly bucketed counts for the last ``hours`` window.

        Buckets are ISO-formatted hour markers (``YYYY-MM-DDTHH:00:00``) so
        clients can render sparklines without inventing a time grid. Empty
        hours are included as zero counts so the array length is stable.
        """
        hours = max(1, min(int(hours), 24 * 14))
        buckets = _hour_buckets(hours)
        empty = {b: 0 for b in buckets}
        series: dict[str, list[dict]] = {}
        conn = self._connect()
        try:
            queries: list[tuple[str, str, str]] = [
                ("trajectories", "capture_time", "trajectories"),
                ("reward_events", "created_at", "reward_events"),
                ("preference_signals", "created_at", "preference_signals"),
                ("candidate_outputs", "created_at", "candidate_outputs"),
            ]
            for label, column, table in queries:
                validated_table = _validated_rl_table(table)
                counts = dict(empty)
                rows = conn.execute(
                    "SELECT strftime('%Y-%m-%dT%H:00:00', " + column + ") AS bucket, COUNT(*)"
                    " FROM " + validated_table +
                    " WHERE " + column + " IS NOT NULL"
                    " AND " + column + " >= datetime('now', ?)"
                    " GROUP BY bucket"
                    " ORDER BY bucket ASC",
                    ("-{} hours".format(hours),),
                ).fetchall()
                for bucket, count in rows:
                    if bucket in counts:
                        counts[bucket] = int(count)
                series[label] = [{"bucket": bucket, "count": counts[bucket]} for bucket in buckets]
            # model_calls has no timestamp column of its own, so bucket by the
            # parent trajectory's capture_time via a join.
            model_counts = dict(empty)
            rows = conn.execute(
                """
                SELECT strftime('%Y-%m-%dT%H:00:00', t.capture_time) AS bucket, COUNT(*)
                FROM model_calls mc
                JOIN trajectories t ON mc.trajectory_id = t.id
                WHERE t.capture_time IS NOT NULL
                  AND t.capture_time >= datetime('now', ?)
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                (f"-{hours} hours",),
            ).fetchall()
            for bucket, count in rows:
                if bucket in model_counts:
                    model_counts[bucket] = int(count)
            series["model_calls"] = [{"bucket": bucket, "count": model_counts[bucket]} for bucket in buckets]
        finally:
            conn.close()
        return series

    def trajectory_detail(self, trajectory_id: str) -> dict | None:
        """Full trajectory detail for the drill-down UI.

        Combines the stored trajectory row with per-target rewards,
        preferences, candidates, and evaluator results. Returns ``None``
        when the trajectory id is unknown.
        """
        base = self.get_trajectory(trajectory_id)
        if not base:
            return None
        model_calls = self.list_model_calls(trajectory_id=trajectory_id, limit=500)
        tool_calls = self.list_tool_calls(trajectory_id=trajectory_id, limit=500)
        observations = self.list_observations(trajectory_id=trajectory_id, limit=500)
        trajectory = {
            **base,
            "model_calls": model_calls or base.get("model_calls") or [],
            "tool_calls": tool_calls or base.get("tool_calls") or [],
            "observations": observations or base.get("observations") or [],
        }
        rewards = self.list_reward_events(trajectory_id=trajectory_id, limit=500)
        preferences = self.list_preference_signals(trajectory_id=trajectory_id, limit=200)
        candidates = self.list_candidate_outputs(trajectory_id=trajectory_id, limit=200)
        evaluator_results = self._list_json_rows(
            "evaluator_results",
            "evaluator_json",
            filters={"trajectory_id": trajectory_id},
            order_by="created_at DESC",
            limit=200,
        )
        trace_value = self.latest_trace_value_assessment(trajectory_id)
        route_decisions = self.list_trace_route_decisions(trajectory_id=trajectory_id, limit=200)
        return {
            "trajectory": trajectory,
            "rewards": rewards,
            "preferences": preferences,
            "candidates": candidates,
            "evaluator_results": evaluator_results,
            "trace_value": trace_value,
            "route_decisions": route_decisions,
        }

    def latest_trace_value_assessment(self, trajectory_id: str) -> dict | None:
        rows = self._list_json_rows(
            "trace_value_assessments",
            "assessment_json",
            filters={"trajectory_id": trajectory_id},
            order_by="created_at DESC",
            limit=1,
        )
        return rows[0] if rows else None

    def list_trace_value_assessments(
        self,
        *,
        destination: str | None = None,
        verdict: str | None = None,
        include_debug: bool = False,
        limit: int = 100,
    ) -> list[dict]:
        where: list[str] = []
        params: list[object] = []
        if destination:
            where.append("top_destination = ?")
            params.append(destination)
        if verdict:
            where.append("quality_verdict = ?")
            params.append(verdict)
        if not include_debug:
            where.append("debug_only = 0")
        sql = "SELECT assessment_json FROM trace_value_assessments"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(int(limit))
        conn = self._connect()
        try:
            return [json.loads(row[0]) for row in conn.execute(sql, params).fetchall()]
        finally:
            conn.close()

    def list_trace_route_decisions(
        self,
        *,
        trajectory_id: str | None = None,
        destination: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self._list_json_rows(
            "trace_route_decisions",
            "decision_json",
            filters={"trajectory_id": trajectory_id, "destination": destination},
            order_by="created_at DESC",
            limit=limit,
        )

    def trace_value_summary(self) -> dict:
        conn = self._connect()
        try:
            totals = {
                "assessments": int(conn.execute("SELECT COUNT(*) FROM trace_value_assessments").fetchone()[0]),
                "debug_only": int(conn.execute("SELECT COUNT(*) FROM trace_value_assessments WHERE debug_only = 1").fetchone()[0]),
                "route_decisions": int(conn.execute("SELECT COUNT(*) FROM trace_route_decisions").fetchone()[0]),
            }
            by_destination = {
                str(row[0] or "unknown"): int(row[1])
                for row in conn.execute(
                    """
                    SELECT top_destination, COUNT(*)
                    FROM trace_value_assessments
                    GROUP BY top_destination
                    """
                ).fetchall()
            }
            pending = int(conn.execute(
                """
                SELECT COUNT(*)
                FROM trajectories t
                LEFT JOIN trace_value_assessments a ON a.trajectory_id = t.id
                WHERE COALESCE(t.task, '') != ''
                  AND t.terminal_status IN ('success', 'done')
                  AND a.id IS NULL
                """
            ).fetchone()[0])
            return {"totals": totals, "by_destination": by_destination, "pending_assessment": pending}
        finally:
            conn.close()

    def list_unassessed_trajectories(self, *, limit: int = 50) -> list[dict]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT t.trajectory_json
                FROM trajectories t
                LEFT JOIN trace_value_assessments a ON a.trajectory_id = t.id
                WHERE COALESCE(t.task, '') != ''
                  AND t.terminal_status IN ('success', 'done')
                  AND a.id IS NULL
                ORDER BY t.capture_time DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()

    def _get_json_by_id(self, table: str, id_column: str, value: str, json_column: str) -> dict | None:
        validated_table = _validated_rl_table(table)
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT " + json_column + " FROM " + validated_table + " WHERE " + id_column + " = ?",
                (value,),
            ).fetchone()
            return json.loads(row[0]) if row else None
        finally:
            conn.close()

    def _list_json_rows(
        self,
        table: str,
        json_column: str,
        *,
        filters: dict[str, str | None],
        order_by: str,
        limit: int,
    ) -> list[dict]:
        where: list[str] = []
        params: list[object] = []
        validated_table = _validated_rl_table(table)
        for column, value in filters.items():
            if value:
                where.append(column + " = ?")
                params.append(value)
        sql = "SELECT " + json_column + " FROM " + validated_table
        where_clause = _sql_where(where)
        if where_clause:
            sql += " " + where_clause
        sql += " ORDER BY " + order_by + " LIMIT ?"
        params.append(int(limit))
        conn = self._connect()
        try:
            rows = conn.execute(sql, params).fetchall()
            return [json.loads(row[0]) for row in rows]
        finally:
            conn.close()


def _hour_buckets(hours: int) -> list[str]:
    """Return ordered ISO hour buckets ending at the current UTC hour."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        (now - timedelta(hours=hours - 1 - offset)).strftime("%Y-%m-%dT%H:00:00")
        for offset in range(hours)
    ]


def _top_destination(destinations: dict) -> str:
    if not destinations:
        return ""
    return str(max(destinations.items(), key=lambda item: float(item[1] or 0))[0])


_stores: dict[str, RLStore] = {}
_pg_store: object | None = None
_RL_PATH_RE = re.compile(r'^[A-Za-z0-9 _/\\:.\-]+$')


def _resolve_backend() -> str:
    """Return 'postgres' or 'sqlite' based on config/env."""
    import os
    try:
        from iaf_agent_skills.storage.engine import resolve_backend
        return resolve_backend()
    except ImportError:
        pass
    return (os.getenv("DB_BACKEND") or "sqlite").strip().lower()


def get_rl_store(*, data_root: str | Path = "", tenant_id: str = "company", db_path: str | Path | None = None):
    """Return the RL store for the configured backend.

    When DB_BACKEND=postgres, returns a PGRLStore backed by the shared
    PostgresEngine (DATABASE_URL). Otherwise returns the SQLite RLStore.
    """
    global _pg_store

    if _resolve_backend() == "postgres":
        if _pg_store is None:
            from iaf_agent_skills.storage.engine import get_engine
            from rl_capture.store.pg_store import PGRLStore
            engine = get_engine()
            _pg_store = PGRLStore(engine)
        return _pg_store

    if db_path is not None:
        db_path_str = str(db_path).strip()
        if not _RL_PATH_RE.fullmatch(db_path_str):
            raise ValueError("RL_DB_PATH contains disallowed characters")
        db_path_str = db_path_str.encode("utf-8").decode("utf-8")
        resolved = Path(db_path_str).resolve()
    else:
        resolved = tenant_rl_db_path(data_root, tenant_id)
    key = str(resolved)
    if key not in _stores:
        _stores[key] = RLStore(resolved)
    return _stores[key]


def reset_rl_stores() -> None:
    global _pg_store
    _stores.clear()
    _pg_store = None
