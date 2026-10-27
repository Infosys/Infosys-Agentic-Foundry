"""PostgreSQL-backed RL capture store using StorageEngine abstraction.

Drop-in replacement for RLStore (sqlite_store.py) when DB_BACKEND=postgres.
Uses the same interface so callers (API routes, trace emitter) are unchanged.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Iterable

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

logger = logging.getLogger(__name__)

STORE_SCHEMA_VERSION = 3

_VALID_RL_TABLES = frozenset({
    "trajectories", "trajectory_steps", "model_calls", "tool_calls",
    "observations", "reward_events", "preference_signals",
    "candidate_outputs", "evaluator_results", "shadow_runs", "exports",
    "schema_migrations",
    "trace_value_assessments", "trace_route_decisions",
})


def _validated_rl_table(name: str) -> str:
    if name not in _VALID_RL_TABLES:
        raise ValueError("Invalid table name: %s" % name)
    return name


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _sql_where(conditions: list[str]) -> str:
    if not conditions:
        return ""
    return "WHERE " + " AND ".join(conditions)



_SCHEMA_STATEMENTS: list[str] = [
    """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version INTEGER PRIMARY KEY,
        applied_at TEXT NOT NULL
    )
    """,
    """
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_trajectories_tenant ON trajectories(tenant_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_trajectories_session ON trajectories(session_id)",
    """
    CREATE TABLE IF NOT EXISTS trajectory_steps (
        id TEXT PRIMARY KEY,
        trajectory_id TEXT NOT NULL REFERENCES trajectories(id),
        step_index INTEGER,
        kind TEXT,
        target_json TEXT NOT NULL,
        metadata_json TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_steps_trajectory ON trajectory_steps(trajectory_id)",
    """
    CREATE TABLE IF NOT EXISTS model_calls (
        id TEXT PRIMARY KEY,
        trajectory_id TEXT REFERENCES trajectories(id),
        provider TEXT,
        model TEXT,
        fidelity TEXT,
        prompt_tokens INTEGER,
        completion_tokens INTEGER,
        cost_usd REAL,
        latency_ms INTEGER,
        model_call_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_model_calls_trajectory ON model_calls(trajectory_id)",
    """
    CREATE TABLE IF NOT EXISTS tool_calls (
        id TEXT PRIMARY KEY,
        trajectory_id TEXT REFERENCES trajectories(id),
        name TEXT,
        status TEXT,
        duration_ms INTEGER,
        tool_call_json TEXT NOT NULL
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_tool_calls_trajectory ON tool_calls(trajectory_id)",
    """
    CREATE TABLE IF NOT EXISTS observations (
        id TEXT PRIMARY KEY,
        trajectory_id TEXT REFERENCES trajectories(id),
        source TEXT,
        observation_json TEXT NOT NULL
    )
    """,
    """
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_rewards_trajectory ON reward_events(trajectory_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_rewards_channel ON reward_events(channel)",
    """
    CREATE TABLE IF NOT EXISTS preference_signals (
        id TEXT PRIMARY KEY,
        trajectory_id TEXT,
        provenance TEXT,
        channel TEXT,
        preference_json TEXT NOT NULL,
        created_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_preferences_trajectory ON preference_signals(trajectory_id)",
    """
    CREATE TABLE IF NOT EXISTS candidate_outputs (
        id TEXT PRIMARY KEY,
        trajectory_id TEXT NOT NULL REFERENCES trajectories(id),
        kind TEXT,
        source TEXT,
        candidate_json TEXT NOT NULL,
        created_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_candidates_trajectory ON candidate_outputs(trajectory_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_candidates_kind ON candidate_outputs(kind)",
    """
    CREATE TABLE IF NOT EXISTS evaluator_results (
        id TEXT PRIMARY KEY,
        trajectory_id TEXT,
        rubric TEXT,
        evaluator_json TEXT NOT NULL,
        created_at TEXT
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_evaluators_trajectory ON evaluator_results(trajectory_id)",
    """
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_trace_value_trajectory ON trace_value_assessments(trajectory_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_trace_value_destination ON trace_value_assessments(top_destination)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_rl_trace_value_hash ON trace_value_assessments(trajectory_id, input_hash, rubric)",
    """
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
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_rl_trace_routes_trajectory ON trace_route_decisions(trajectory_id)",
    "CREATE INDEX IF NOT EXISTS idx_rl_trace_routes_destination ON trace_route_decisions(destination)",
    """
    CREATE TABLE IF NOT EXISTS shadow_runs (
        id TEXT PRIMARY KEY,
        baseline_trajectory_id TEXT,
        candidate_provider TEXT,
        candidate_model TEXT,
        shadow_json TEXT NOT NULL,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS exports (
        id TEXT PRIMARY KEY,
        kind TEXT,
        params_json TEXT,
        file_path TEXT,
        checksum TEXT,
        row_count INTEGER,
        export_json TEXT NOT NULL,
        created_at TEXT
    )
    """,
]


class PGRLStore:
    """PostgreSQL-backed RL capture store.

    Same public interface as sqlite_store.RLStore so callers
    (API routes, trace emitter, CLI) work unchanged.
    """

    def __init__(self, engine: Any):
        self.engine = engine
        # Compatibility: callers may access .db_path for health/info endpoints
        self.db_path = getattr(engine, 'dsn', 'postgres')
        self._ensure_schema()


    def _ph(self, index: int = 0) -> str:
        return self.engine.placeholder(index)

    def _placeholders(self, count: int) -> str:
        return ", ".join(self.engine.placeholder(i) for i in range(count))

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self.engine.connect() as conn:
            conn.execute(sql, params)

    def _query(self, sql: str, params: tuple = ()) -> list[Any]:
        with self.engine.connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchall()

    def _query_one(self, sql: str, params: tuple = ()) -> Any:
        with self.engine.connect() as conn:
            cur = conn.execute(sql, params)
            return cur.fetchone()

    def _ensure_schema(self) -> None:
        with self.engine.connect() as conn:
            for stmt in _SCHEMA_STATEMENTS:
                conn.execute(stmt)
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_at) "
                "VALUES (%s, %s) ON CONFLICT (version) DO NOTHING",
                (STORE_SCHEMA_VERSION, _now()),
            )
        logger.info("PGRLStore: schema ensured (version %d)", STORE_SCHEMA_VERSION)


    def record_trajectory(self, trajectory: Trajectory) -> None:
        payload = to_jsonable(trajectory)
        tenant_id = trajectory.capture.tenant_id or trajectory.tenant or ""
        agent_id = trajectory.capture.agent_id or ""
        with self.engine.connect() as conn:
            conn.execute(
                """
                INSERT INTO trajectories (
                    id, tenant_id, agent_id, session_id, task, fidelity,
                    terminal_status, started_at, ended_at, capture_time,
                    trajectory_json, metadata_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    agent_id = EXCLUDED.agent_id,
                    session_id = EXCLUDED.session_id,
                    task = EXCLUDED.task,
                    fidelity = EXCLUDED.fidelity,
                    terminal_status = EXCLUDED.terminal_status,
                    started_at = EXCLUDED.started_at,
                    ended_at = EXCLUDED.ended_at,
                    capture_time = EXCLUDED.capture_time,
                    trajectory_json = EXCLUDED.trajectory_json,
                    metadata_json = EXCLUDED.metadata_json
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

    def _replace_children(self, conn: Any, trajectory: Trajectory) -> None:
        conn.execute(
            "DELETE FROM trajectory_steps WHERE trajectory_id = %s",
            (trajectory.id,),
        )
        for step in trajectory.steps:
            conn.execute(
                """
                INSERT INTO trajectory_steps (id, trajectory_id, step_index, kind, target_json, metadata_json)
                VALUES (%s, %s, %s, %s, %s, %s)
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
                INSERT INTO model_calls (
                    id, trajectory_id, provider, model, fidelity, prompt_tokens,
                    completion_tokens, cost_usd, latency_ms, model_call_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    trajectory_id = EXCLUDED.trajectory_id,
                    provider = EXCLUDED.provider,
                    model = EXCLUDED.model,
                    fidelity = EXCLUDED.fidelity,
                    prompt_tokens = EXCLUDED.prompt_tokens,
                    completion_tokens = EXCLUDED.completion_tokens,
                    cost_usd = EXCLUDED.cost_usd,
                    latency_ms = EXCLUDED.latency_ms,
                    model_call_json = EXCLUDED.model_call_json
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
                INSERT INTO tool_calls (id, trajectory_id, name, status, duration_ms, tool_call_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    trajectory_id = EXCLUDED.trajectory_id,
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    duration_ms = EXCLUDED.duration_ms,
                    tool_call_json = EXCLUDED.tool_call_json
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
                INSERT INTO observations (id, trajectory_id, source, observation_json)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    trajectory_id = EXCLUDED.trajectory_id,
                    source = EXCLUDED.source,
                    observation_json = EXCLUDED.observation_json
                """,
                (
                    observation.id,
                    trajectory.id,
                    observation.source,
                    json.dumps(to_jsonable(observation), ensure_ascii=False, default=str),
                ),
            )

    def record_model_call(self, trajectory_id: str, model_call: ModelCall) -> None:
        with self.engine.connect() as conn:
            conn.execute(
                """
                INSERT INTO trajectories (
                    id, tenant_id, agent_id, session_id, task, fidelity,
                    terminal_status, started_at, ended_at, capture_time,
                    trajectory_json, metadata_json
                ) VALUES (%s, '', '', '', '', %s, 'partial', NULL, NULL, %s, %s, '{}')
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    trajectory_id,
                    model_call.fidelity.value,
                    _now(),
                    json.dumps({"id": trajectory_id, "terminal_status": "partial"}, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                INSERT INTO model_calls (
                    id, trajectory_id, provider, model, fidelity, prompt_tokens,
                    completion_tokens, cost_usd, latency_ms, model_call_json
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    trajectory_id = EXCLUDED.trajectory_id,
                    provider = EXCLUDED.provider,
                    model = EXCLUDED.model,
                    fidelity = EXCLUDED.fidelity,
                    prompt_tokens = EXCLUDED.prompt_tokens,
                    completion_tokens = EXCLUDED.completion_tokens,
                    cost_usd = EXCLUDED.cost_usd,
                    latency_ms = EXCLUDED.latency_ms,
                    model_call_json = EXCLUDED.model_call_json
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

    def record_tool_call(self, trajectory_id: str, tool_call: ToolCall) -> None:
        with self.engine.connect() as conn:
            conn.execute(
                """
                INSERT INTO trajectories (
                    id, tenant_id, agent_id, session_id, task, fidelity,
                    terminal_status, started_at, ended_at, capture_time,
                    trajectory_json, metadata_json
                ) VALUES (%s, '', '', '', '', 'text_only', 'partial', NULL, NULL, %s, %s, '{}')
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    trajectory_id,
                    _now(),
                    json.dumps({"id": trajectory_id, "terminal_status": "partial"}, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                INSERT INTO tool_calls (id, trajectory_id, name, status, duration_ms, tool_call_json)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    trajectory_id = EXCLUDED.trajectory_id,
                    name = EXCLUDED.name,
                    status = EXCLUDED.status,
                    duration_ms = EXCLUDED.duration_ms,
                    tool_call_json = EXCLUDED.tool_call_json
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

    def record_observation(self, trajectory_id: str, observation: Observation) -> None:
        with self.engine.connect() as conn:
            conn.execute(
                """
                INSERT INTO trajectories (
                    id, tenant_id, agent_id, session_id, task, fidelity,
                    terminal_status, started_at, ended_at, capture_time,
                    trajectory_json, metadata_json
                ) VALUES (%s, '', '', '', '', 'text_only', 'partial', NULL, NULL, %s, %s, '{}')
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    trajectory_id,
                    _now(),
                    json.dumps({"id": trajectory_id, "terminal_status": "partial"}, ensure_ascii=False),
                ),
            )
            conn.execute(
                """
                INSERT INTO observations (id, trajectory_id, source, observation_json)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    trajectory_id = EXCLUDED.trajectory_id,
                    source = EXCLUDED.source,
                    observation_json = EXCLUDED.observation_json
                """,
                (
                    observation.id,
                    trajectory_id,
                    observation.source,
                    json.dumps(to_jsonable(observation), ensure_ascii=False, default=str),
                ),
            )

    def record_reward_event(self, reward: RewardEvent) -> None:
        self._upsert_row(
            "reward_events",
            ("id", "trajectory_id", "target_type", "target_id", "channel",
             "raw_label", "raw_value", "confidence", "reward_json", "created_at"),
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
        self._upsert_row(
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
        self._upsert_row(
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
        self._upsert_row(
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
        self._upsert_row(
            "trace_value_assessments",
            ("id", "trajectory_id", "input_hash", "rubric", "quality_score",
             "quality_verdict", "top_destination", "debug_only", "assessment_json", "created_at"),
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
        self._upsert_row(
            "trace_route_decisions",
            ("id", "trajectory_id", "assessment_id", "destination", "action",
             "status", "reviewer", "target_ref", "decision_json", "created_at"),
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
        self._upsert_row(
            "shadow_runs",
            ("id", "baseline_trajectory_id", "candidate_provider",
             "candidate_model", "shadow_json", "created_at"),
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
        self._upsert_row(
            "exports",
            ("id", "kind", "params_json", "file_path", "checksum",
             "row_count", "export_json", "created_at"),
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


    def list_trajectories(
        self,
        *,
        limit: int = 100,
        tenant_id: str | None = None,
        agent_id: str | None = None,
        session_id: str | None = None,
        fidelity: str | None = None,
    ) -> list[dict]:
        where: list[str] = []
        params: list[object] = []
        if tenant_id:
            where.append("tenant_id = %s")
            params.append(tenant_id)
        if agent_id:
            where.append("agent_id = %s")
            params.append(agent_id)
        if session_id:
            where.append("session_id = %s")
            params.append(session_id)
        if fidelity:
            where.append("fidelity = %s")
            params.append(fidelity)
        sql = "SELECT trajectory_json FROM trajectories"
        where_clause = _sql_where(where)
        if where_clause:
            sql += " " + where_clause
        sql += " ORDER BY capture_time DESC LIMIT %s"
        params.append(int(limit))
        rows = self._query(sql, tuple(params))
        return [json.loads(row[0]) for row in rows]

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
        """Return trajectories joined to their latest Trace Value read model."""
        where: list[str] = []
        params: list[object] = []
        if tenant_id:
            where.append("t.tenant_id = %s")
            params.append(tenant_id)
        if session_id:
            where.append("t.session_id = %s")
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
                where.append("CAST(assessment_json::json->>'destinations'->%s AS REAL) >= %s")
                params.extend((destination, float(min_destination_score)))
            else:
                where.append("a.top_destination = %s")
                params.append(destination)
        if route_status:
            route_filter = [
                "r.trajectory_id = t.id",
                "LOWER(r.status) = LOWER(%s)",
            ]
            params.append(route_status)
            if destination:
                route_filter.append("r.destination = %s")
                params.append(destination)
            where.append(
                "EXISTS (SELECT 1 FROM trace_route_decisions r WHERE "
                + " AND ".join(route_filter)
                + ")"
            )
        decision_filter: list[str] = ["r2.trajectory_id = t.id"]
        decision_params: list[object] = []
        if destination:
            decision_filter.append("r2.destination = %s")
            decision_params.append(destination)
        if route_status:
            decision_filter.append("LOWER(r2.status) = LOWER(%s)")
            decision_params.append(route_status)
        sql = """
            WITH latest_assessment AS (
                SELECT *
                FROM (
                    SELECT a2.*, ROW_NUMBER() OVER (
                        PARTITION BY a2.trajectory_id
                        ORDER BY a2.created_at DESC, a2.id DESC
                    ) AS row_num
                    FROM trace_value_assessments a2
                ) sub
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
        sql += " ORDER BY t.capture_time DESC LIMIT %s"
        query_params = tuple([*decision_params, *params, int(limit)])
        rows = self._query(sql, query_params)
        return [
            {
                "trajectory": json.loads(row[0]),
                "trace_value": json.loads(row[1]) if row[1] else None,
                "route_decisions": [json.loads(row[2])] if row[2] else [],
            }
            for row in rows
        ]

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
            "model_calls", "model_call_json",
            filters={"trajectory_id": trajectory_id},
            order_by="id ASC", limit=limit,
        )

    def list_tool_calls(self, *, trajectory_id: str, limit: int = 500) -> list[dict]:
        return self._list_json_rows(
            "tool_calls", "tool_call_json",
            filters={"trajectory_id": trajectory_id},
            order_by="id ASC", limit=limit,
        )

    def list_observations(self, *, trajectory_id: str, limit: int = 500) -> list[dict]:
        return self._list_json_rows(
            "observations", "observation_json",
            filters={"trajectory_id": trajectory_id},
            order_by="id ASC", limit=limit,
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
            "reward_events", "reward_json",
            filters={"trajectory_id": trajectory_id, "channel": channel, "raw_label": raw_label},
            order_by="created_at DESC", limit=limit,
        )

    def list_preference_signals(
        self,
        *,
        trajectory_id: str | None = None,
        channel: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        return self._list_json_rows(
            "preference_signals", "preference_json",
            filters={"trajectory_id": trajectory_id, "channel": channel},
            order_by="created_at DESC", limit=limit,
        )

    def list_candidate_outputs(
        self,
        *,
        trajectory_id: str | None = None,
        kind: str | None = None,
        limit: int = 1000,
    ) -> list[dict]:
        return self._list_json_rows(
            "candidate_outputs", "candidate_json",
            filters={"trajectory_id": trajectory_id, "kind": kind},
            order_by="created_at DESC", limit=limit,
        )

    def list_exports(self, *, kind: str | None = None, limit: int = 100) -> list[dict]:
        return self._list_json_rows(
            "exports", "export_json",
            filters={"kind": kind},
            order_by="created_at DESC", limit=limit,
        )

    def dataset_health(self) -> dict[str, int]:
        tables = [
            "trajectories", "trajectory_steps", "model_calls", "tool_calls",
            "observations", "candidate_outputs", "reward_events",
            "preference_signals", "evaluator_results", "trace_value_assessments",
            "trace_route_decisions", "shadow_runs", "exports",
        ]
        result = {}
        with self.engine.connect() as conn:
            for t in tables:
                validated = _validated_rl_table(t)
                cur = conn.execute("SELECT COUNT(*) FROM " + validated)
                result[t] = int(cur.fetchone()[0])
        return result

    def time_series(self, *, hours: int = 24) -> dict[str, list[dict]]:
        """Hourly bucketed counts for the last ``hours`` window (Postgres version)."""
        hours = max(1, min(int(hours), 24 * 14))
        buckets = _hour_buckets(hours)
        empty = {b: 0 for b in buckets}
        series: dict[str, list[dict]] = {}
        with self.engine.connect() as conn:
            queries: list[tuple[str, str, str]] = [
                ("trajectories", "capture_time", "trajectories"),
                ("reward_events", "created_at", "reward_events"),
                ("preference_signals", "created_at", "preference_signals"),
                ("candidate_outputs", "created_at", "candidate_outputs"),
            ]
            for label, column, table in queries:
                validated_table = _validated_rl_table(table)
                counts = dict(empty)
                cur = conn.execute(
                    "SELECT to_char((" + column + ")::timestamp, 'YYYY-MM-DD\"T\"HH24:00:00') AS bucket, COUNT(*)"
                    " FROM " + validated_table +
                    " WHERE " + column + " IS NOT NULL"
                    " AND (" + column + ")::timestamp >= NOW() - INTERVAL '%s hours'"
                    " GROUP BY bucket"
                    " ORDER BY bucket ASC",
                    (hours,),
                )
                for row in cur.fetchall():
                    bucket, count = row[0], row[1]
                    if bucket in counts:
                        counts[bucket] = int(count)
                series[label] = [{"bucket": bucket, "count": counts[bucket]} for bucket in buckets]
            # model_calls via join
            model_counts = dict(empty)
            cur = conn.execute(
                """
                SELECT to_char((t.capture_time)::timestamp, 'YYYY-MM-DD"T"HH24:00:00') AS bucket, COUNT(*)
                FROM model_calls mc
                JOIN trajectories t ON mc.trajectory_id = t.id
                WHERE t.capture_time IS NOT NULL
                  AND (t.capture_time)::timestamp >= NOW() - INTERVAL '%s hours'
                GROUP BY bucket
                ORDER BY bucket ASC
                """,
                (hours,),
            )
            for row in cur.fetchall():
                bucket, count = row[0], row[1]
                if bucket in model_counts:
                    model_counts[bucket] = int(count)
            series["model_calls"] = [{"bucket": bucket, "count": model_counts[bucket]} for bucket in buckets]
        return series

    def trajectory_detail(self, trajectory_id: str) -> dict | None:
        """Full trajectory detail for drill-down UI."""
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
            "evaluator_results", "evaluator_json",
            filters={"trajectory_id": trajectory_id},
            order_by="created_at DESC", limit=200,
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
            "trace_value_assessments", "assessment_json",
            filters={"trajectory_id": trajectory_id},
            order_by="created_at DESC", limit=1,
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
            where.append("top_destination = %s")
            params.append(destination)
        if verdict:
            where.append("quality_verdict = %s")
            params.append(verdict)
        if not include_debug:
            where.append("debug_only = 0")
        sql = "SELECT assessment_json FROM trace_value_assessments"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC LIMIT %s"
        params.append(int(limit))
        rows = self._query(sql, tuple(params))
        return [json.loads(row[0]) for row in rows]

    def list_trace_route_decisions(
        self,
        *,
        trajectory_id: str | None = None,
        destination: str | None = None,
        limit: int = 100,
    ) -> list[dict]:
        return self._list_json_rows(
            "trace_route_decisions", "decision_json",
            filters={"trajectory_id": trajectory_id, "destination": destination},
            order_by="created_at DESC", limit=limit,
        )

    def trace_value_summary(self) -> dict:
        with self.engine.connect() as conn:
            totals = {
                "assessments": int(conn.execute("SELECT COUNT(*) FROM trace_value_assessments").fetchone()[0]),
                "debug_only": int(conn.execute("SELECT COUNT(*) FROM trace_value_assessments WHERE debug_only = 1").fetchone()[0]),
                "route_decisions": int(conn.execute("SELECT COUNT(*) FROM trace_route_decisions").fetchone()[0]),
            }
            by_destination = {
                str(row[0] or "unknown"): int(row[1])
                for row in conn.execute(
                    "SELECT top_destination, COUNT(*) FROM trace_value_assessments GROUP BY top_destination"
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

    def list_unassessed_trajectories(self, *, limit: int = 50) -> list[dict]:
        rows = self._query(
            """
            SELECT t.trajectory_json
            FROM trajectories t
            LEFT JOIN trace_value_assessments a ON a.trajectory_id = t.id
            WHERE COALESCE(t.task, '') != ''
              AND t.terminal_status IN ('success', 'done')
              AND a.id IS NULL
            ORDER BY t.capture_time DESC
            LIMIT %s
            """,
            (int(limit),),
        )
        return [json.loads(row[0]) for row in rows]


    def _upsert_row(self, table: str, columns: Iterable[str], values: tuple) -> None:
        validated_table = _validated_rl_table(table)
        column_list = list(columns)
        placeholders = ", ".join("%s" for _ in column_list)
        # ON CONFLICT (id) DO UPDATE for all non-id columns
        update_cols = [c for c in column_list if c != "id"]
        conflict_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        sql = (
            "INSERT INTO " + validated_table
            + " (" + ", ".join(column_list) + ") VALUES (" + placeholders + ")"
            + " ON CONFLICT (id) DO UPDATE SET " + conflict_clause
        )
        self._execute(sql, values)

    def _get_json_by_id(self, table: str, id_column: str, value: str, json_column: str) -> dict | None:
        validated_table = _validated_rl_table(table)
        row = self._query_one(
            "SELECT " + json_column + " FROM " + validated_table + " WHERE " + id_column + " = %s",
            (value,),
        )
        return json.loads(row[0]) if row else None

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
                where.append(column + " = %s")
                params.append(value)
        sql = "SELECT " + json_column + " FROM " + validated_table
        where_clause = _sql_where(where)
        if where_clause:
            sql += " " + where_clause
        sql += " ORDER BY " + order_by + " LIMIT %s"
        params.append(int(limit))
        rows = self._query(sql, tuple(params))
        return [json.loads(row[0]) for row in rows]


def _top_destination(destinations: dict) -> str:
    if not destinations:
        return ""
    return str(max(destinations.items(), key=lambda item: float(item[1] or 0))[0])


def _hour_buckets(hours: int) -> list[str]:
    from datetime import timedelta
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        (now - timedelta(hours=hours - 1 - offset)).strftime("%Y-%m-%dT%H:00:00")
        for offset in range(hours)
    ]
