"""
Job Store - Persistent Storage for Jobs and Runs

Abstract interface with SQLite implementation.
Upgrade path: SQLite → Redis → Postgres
"""

import json
import sqlite3
from abc import ABC, abstractmethod
try:
    from ..sqlite_util import connect as _sqlite_connect
except ImportError:
    from sqlite_util import connect as _sqlite_connect
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any
from contextlib import contextmanager
import threading

# Support both relative import (when used as package) and direct import (when testing)
try:
    from .models import Job, JobRun, RunStatus
except ImportError:
    from scheduler_models import Job, JobRun, RunStatus


class JobStore(ABC):
    """
    Abstract job store interface.
    
    Implement this for different backends (SQLite, Redis, Postgres, etc.)
    """
    
    
    @abstractmethod
    def save_job(self, job: Job) -> Job:
        """Create or update a job. Returns the saved job."""
        pass
    
    @abstractmethod
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        pass
    
    @abstractmethod
    def get_job_by_name(self, name: str, tenant_id: str = "company") -> Optional[Job]:
        """Get job by name within a tenant."""
        pass
    
    @abstractmethod
    def list_jobs(
        self,
        tenant_id: Optional[str] = None,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Job]:
        """List jobs with optional filters."""
        pass
    
    @abstractmethod
    def delete_job(self, job_id: str) -> bool:
        """Delete a job. Returns True if deleted."""
        pass
    
    @abstractmethod
    def update_job_runtime(
        self,
        job_id: str,
        last_run_at: Optional[datetime] = None,
        next_run_at: Optional[datetime] = None,
        consecutive_failures: Optional[int] = None
    ) -> None:
        """Update job runtime state (separate from config)."""
        pass
    
    
    @abstractmethod
    def save_run(self, run: JobRun) -> JobRun:
        """Create or update a run. Returns the saved run."""
        pass
    
    @abstractmethod
    def get_run(self, run_id: str) -> Optional[JobRun]:
        """Get run by ID."""
        pass
    
    @abstractmethod
    def list_runs(
        self,
        job_id: Optional[str] = None,
        status: Optional[RunStatus] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[JobRun]:
        """List runs with optional filters."""
        pass
    
    @abstractmethod
    def get_latest_run(self, job_id: str) -> Optional[JobRun]:
        """Get the most recent run for a job."""
        pass
    
    
    @abstractmethod
    def get_job_stats(self, job_id: str, days: int = 7) -> Dict[str, Any]:
        """Get run statistics for a job."""
        pass
    
    @abstractmethod
    def get_due_jobs(self, before: datetime) -> List[Job]:
        """Get jobs that are due to run (next_run_at <= before)."""
        pass
    
    @abstractmethod
    def get_stuck_runs(self, max_age_minutes: int = 30) -> List[JobRun]:
        """Get runs stuck in 'running' state longer than max_age_minutes."""
        pass


class SQLiteJobStore(JobStore):
    """
    SQLite-based job store.
    
    Good for:
    - Single-server deployments
    - Development/testing
    - Low-to-medium volume (< 1000 jobs)
    
    Upgrade to Redis/Postgres for:
    - Multi-server deployments
    - High volume (> 1000 jobs)
    - Need for distributed locking
    """
    
    def __init__(self, db_path: str = None):
        """
        Initialize SQLite store.
        
        Args:
            db_path: Path to SQLite database file.
                     Default: <project_root>/.iaf/scheduler.db
        """
        if db_path is None:
            _project_root = Path(__file__).resolve().parents[2]
            db_path = str(_project_root / ".iaf" / "scheduler.db")
        
        # Validate path does not escape expected directory structure
        resolved = Path(db_path).resolve()
        if ".." in str(db_path):
            raise ValueError("db_path must not contain path traversal")
        
        self.db_path = str(resolved)
        resolved.parent.mkdir(parents=True, exist_ok=True)
        
        # Thread-local connections (SQLite isn't thread-safe by default)
        self._local = threading.local()
        
        self._init_schema()
    
    @contextmanager
    def _get_connection(self):
        """Get thread-local connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = _sqlite_connect(self.db_path, row_factory=sqlite3.Row)
            self._local.conn.execute("PRAGMA synchronous=NORMAL")
            self._local.conn.execute("PRAGMA busy_timeout=30000")
        
        try:
            yield self._local.conn
        except Exception:
            self._local.conn.rollback()
            raise
    
    def _init_schema(self):
        """Create tables if they don't exist."""
        with self._get_connection() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    data TEXT NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    next_run_at TEXT,
                    last_run_at TEXT,
                    consecutive_failures INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(name, tenant_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON jobs(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_jobs_enabled ON jobs(enabled);
                CREATE INDEX IF NOT EXISTS idx_jobs_next_run ON jobs(next_run_at);
                
                CREATE TABLE IF NOT EXISTS job_runs (
                    id TEXT PRIMARY KEY,
                    job_id TEXT NOT NULL,
                    job_name TEXT,
                    status TEXT NOT NULL,
                    data TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (job_id) REFERENCES jobs(id) ON DELETE CASCADE
                );
                
                CREATE INDEX IF NOT EXISTS idx_runs_job ON job_runs(job_id);
                CREATE INDEX IF NOT EXISTS idx_runs_status ON job_runs(status);
                CREATE INDEX IF NOT EXISTS idx_runs_started ON job_runs(started_at);
            """)
            conn.commit()
    
    
    def save_job(self, job: Job) -> Job:
        """Create or update a job."""
        job.updated_at = datetime.now(timezone.utc)
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM jobs WHERE id = ?",
                (job.id,)
            )
            exists = cursor.fetchone() is not None
            
            if exists:
                conn.execute("""
                    UPDATE jobs SET
                        name = ?,
                        tenant_id = ?,
                        data = ?,
                        enabled = ?,
                        next_run_at = ?,
                        last_run_at = ?,
                        consecutive_failures = ?,
                        updated_at = ?
                    WHERE id = ?
                """, (
                    job.name,
                    job.tenant_id,
                    json.dumps(job.to_dict()),
                    1 if job.enabled else 0,
                    job.next_run_at.isoformat() if job.next_run_at else None,
                    job.last_run_at.isoformat() if job.last_run_at else None,
                    job.consecutive_failures,
                    job.updated_at.isoformat(),
                    job.id
                ))
            else:
                conn.execute("""
                    INSERT INTO jobs (id, name, tenant_id, data, enabled, next_run_at, last_run_at, consecutive_failures, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job.id,
                    job.name,
                    job.tenant_id,
                    json.dumps(job.to_dict()),
                    1 if job.enabled else 0,
                    job.next_run_at.isoformat() if job.next_run_at else None,
                    job.last_run_at.isoformat() if job.last_run_at else None,
                    job.consecutive_failures,
                    job.created_at.isoformat(),
                    job.updated_at.isoformat()
                ))
            
            conn.commit()
        
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT data FROM jobs WHERE id = ?",
                (job_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return Job.from_dict(json.loads(row["data"]))
            return None
    
    def get_job_by_name(self, name: str, tenant_id: str = "company") -> Optional[Job]:
        """Get job by name within a tenant."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT data FROM jobs WHERE name = ? AND tenant_id = ?",
                (name, tenant_id)
            )
            row = cursor.fetchone()
            
            if row:
                return Job.from_dict(json.loads(row["data"]))
            return None
    
    def list_jobs(
        self,
        tenant_id: Optional[str] = None,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Job]:
        """List jobs with optional filters."""
        conditions = []
        params = []
        
        if tenant_id:
            conditions.append("tenant_id = ?")
            params.append(tenant_id)
        
        if enabled_only:
            conditions.append("enabled = 1")
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"SELECT data FROM jobs WHERE {where_clause} ORDER BY name LIMIT ? OFFSET ?",
                params + [limit, offset]
            )
            
            jobs = [Job.from_dict(json.loads(row["data"])) for row in cursor.fetchall()]
            
            # Filter by tags in Python (SQLite JSON support is limited)
            if tags:
                jobs = [j for j in jobs if any(t in j.tags for t in tags)]
            
            return jobs
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM jobs WHERE id = ?",
                (job_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def update_job_runtime(
        self,
        job_id: str,
        last_run_at: Optional[datetime] = None,
        next_run_at: Optional[datetime] = None,
        consecutive_failures: Optional[int] = None
    ) -> None:
        """Update job runtime state."""
        updates = []
        params = []
        
        if last_run_at is not None:
            updates.append("last_run_at = ?")
            params.append(last_run_at.isoformat())
        
        if next_run_at is not None:
            updates.append("next_run_at = ?")
            params.append(next_run_at.isoformat())
        
        if consecutive_failures is not None:
            updates.append("consecutive_failures = ?")
            params.append(consecutive_failures)
        
        if not updates:
            return
        
        updates.append("updated_at = ?")
        params.append(datetime.now(timezone.utc).isoformat())
        params.append(job_id)
        
        with self._get_connection() as conn:
            # Update the jobs table columns
            conn.execute(
                f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?",
                params
            )
            
            # Also update the JSON data blob
            cursor = conn.execute("SELECT data FROM jobs WHERE id = ?", (job_id,))
            row = cursor.fetchone()
            if row:
                data = json.loads(row["data"])
                if last_run_at is not None:
                    data["last_run_at"] = last_run_at.isoformat()
                if next_run_at is not None:
                    data["next_run_at"] = next_run_at.isoformat()
                if consecutive_failures is not None:
                    data["consecutive_failures"] = consecutive_failures
                data["updated_at"] = datetime.now(timezone.utc).isoformat()
                
                conn.execute(
                    "UPDATE jobs SET data = ? WHERE id = ?",
                    (json.dumps(data), job_id)
                )
            
            conn.commit()
    
    
    def save_run(self, run: JobRun) -> JobRun:
        """Create or update a run."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT id FROM job_runs WHERE id = ?",
                (run.id,)
            )
            exists = cursor.fetchone() is not None
            
            if exists:
                conn.execute("""
                    UPDATE job_runs SET
                        status = ?,
                        data = ?,
                        started_at = ?,
                        completed_at = ?
                    WHERE id = ?
                """, (
                    run.status.value,
                    json.dumps(run.to_dict()),
                    run.started_at.isoformat() if run.started_at else None,
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.id
                ))
            else:
                conn.execute("""
                    INSERT INTO job_runs (id, job_id, job_name, status, data, started_at, completed_at, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    run.id,
                    run.job_id,
                    run.job_name,
                    run.status.value,
                    json.dumps(run.to_dict()),
                    run.started_at.isoformat() if run.started_at else None,
                    run.completed_at.isoformat() if run.completed_at else None,
                    datetime.now(timezone.utc).isoformat()
                ))
            
            conn.commit()
        
        return run
    
    def get_run(self, run_id: str) -> Optional[JobRun]:
        """Get run by ID."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT data FROM job_runs WHERE id = ?",
                (run_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return JobRun.from_dict(json.loads(row["data"]))
            return None
    
    def list_runs(
        self,
        job_id: Optional[str] = None,
        status: Optional[RunStatus] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[JobRun]:
        """List runs with optional filters."""
        conditions = []
        params = []
        
        if job_id:
            conditions.append("job_id = ?")
            params.append(job_id)
        
        if status:
            conditions.append("status = ?")
            params.append(status.value)
        
        if since:
            conditions.append("started_at >= ?")
            params.append(since.isoformat())
        
        if until:
            conditions.append("started_at <= ?")
            params.append(until.isoformat())
        
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                f"SELECT data FROM job_runs WHERE {where_clause} ORDER BY started_at DESC LIMIT ? OFFSET ?",
                params + [limit, offset]
            )
            
            return [JobRun.from_dict(json.loads(row["data"])) for row in cursor.fetchall()]
    
    def get_latest_run(self, job_id: str) -> Optional[JobRun]:
        """Get the most recent run for a job."""
        runs = self.list_runs(job_id=job_id, limit=1)
        return runs[0] if runs else None
    
    
    def get_job_stats(self, job_id: str, days: int = 7) -> Dict[str, Any]:
        """Get run statistics for a job."""
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        from datetime import timedelta
        since = since - timedelta(days=days)
        
        runs = self.list_runs(job_id=job_id, since=since, limit=1000)
        
        total = len(runs)
        success = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
        failed = sum(1 for r in runs if r.status == RunStatus.FAILED)
        durations = [r.duration_seconds for r in runs if r.duration_seconds is not None]
        
        return {
            "job_id": job_id,
            "period_days": days,
            "total_runs": total,
            "success": success,
            "failed": failed,
            "success_rate": success / total if total > 0 else 0,
            "avg_duration_seconds": sum(durations) / len(durations) if durations else None,
            "min_duration_seconds": min(durations) if durations else None,
            "max_duration_seconds": max(durations) if durations else None,
        }
    
    def get_due_jobs(self, before: datetime) -> List[Job]:
        """Get jobs that are due to run."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT data FROM jobs WHERE enabled = 1 AND next_run_at IS NOT NULL AND next_run_at <= ?",
                (before.isoformat(),)
            )
            
            return [Job.from_dict(json.loads(row["data"])) for row in cursor.fetchall()]
    
    def get_stuck_runs(self, max_age_minutes: int = 30) -> List[JobRun]:
        """
        Get runs stuck in 'running' state longer than max_age_minutes.
        
        Used for recovery after server restart.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)).isoformat()
        
        with self._get_connection() as conn:
            cursor = conn.execute(
                """SELECT data FROM job_runs 
                   WHERE status = 'running' 
                   AND started_at < ?
                   ORDER BY started_at DESC""",
                (cutoff,)
            )
            
            return [JobRun.from_dict(json.loads(row["data"])) for row in cursor.fetchall()]
