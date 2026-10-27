"""
Sync Redis Job Store - Thread-safe synchronous wrapper for RedisJobStore

This wrapper allows using the async RedisJobStore with the synchronous
CronScheduler class. It creates a dedicated event loop in a background
thread to handle async operations.

Usage:
    # Drop-in replacement for SQLiteJobStore
    store = SyncRedisJobStore(redis_url="redis://localhost:6379")
    scheduler = CronScheduler(store=store, executor=my_executor)
    scheduler.start()

Key Differences from Async Version:
- All methods are synchronous (blocking)
- Thread-safe for multi-threaded schedulers
- Creates its own event loop for Redis operations
- Connection is automatically established on first use
"""

from __future__ import annotations
import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Optional, List

from .models import Job, JobRun, RunStatus
from .store import JobStore

logger = logging.getLogger(__name__)

# Atomic check-and-delete: only removes the lock if the caller still holds it.
_LUA_RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class SyncRedisJobStore(JobStore):
    """
    Synchronous Redis-backed job store.
    
    Wraps async Redis operations to work with sync CronScheduler.
    Thread-safe for concurrent access from scheduler threads.
    
    Features:
    - Same data structure as RedisJobStore
    - Compatible with CronScheduler (sync interface)
    - Thread-safe operations
    - Automatic reconnection
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        key_prefix: str = "iaf:scheduler",
        run_retention_days: int = 30,
    ):
        self.redis_url = redis_url
        self.key_prefix = key_prefix
        self.run_retention_days = run_retention_days
        
        # Sync Redis client
        self._redis = None
        self._lock = threading.Lock()
        self._connected = False
    
    def _ensure_connected(self) -> None:
        """Ensure Redis connection is established."""
        if self._connected:
            return
        
        with self._lock:
            if self._connected:
                return
            
            import redis
            self._redis = redis.Redis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
            self._redis.ping()
            self._connected = True
            logger.info("SyncRedisJobStore connected to configured endpoint")
    
    def disconnect(self) -> None:
        """Disconnect from Redis."""
        with self._lock:
            if self._redis:
                self._redis.close()
                self._connected = False
                logger.info("SyncRedisJobStore disconnected")
    
    
    def _job_key(self, job_id: str) -> str:
        return f"{self.key_prefix}:job:{job_id}"
    
    def _job_name_key(self, name: str, tenant_id: str) -> str:
        return f"{self.key_prefix}:job:name:{tenant_id}:{name}"
    
    def _all_jobs_key(self) -> str:
        return f"{self.key_prefix}:jobs"
    
    def _tenant_jobs_key(self, tenant_id: str) -> str:
        return f"{self.key_prefix}:jobs:tenant:{tenant_id}"
    
    def _enabled_jobs_key(self) -> str:
        return f"{self.key_prefix}:jobs:enabled"
    
    def _due_jobs_key(self) -> str:
        return f"{self.key_prefix}:jobs:due"
    
    def _run_key(self, run_id: str) -> str:
        return f"{self.key_prefix}:run:{run_id}"
    
    def _job_runs_key(self, job_id: str) -> str:
        return f"{self.key_prefix}:runs:job:{job_id}"
    
    def _recent_runs_key(self) -> str:
        return f"{self.key_prefix}:runs:recent"
    
    def _lock_key(self, resource: str) -> str:
        return f"{self.key_prefix}:lock:{resource}"
    
    
    def save_job(self, job: Job) -> Job:
        """Create or update a job."""
        self._ensure_connected()
        
        job.updated_at = datetime.now(timezone.utc)
        job_data = job.to_dict()
        
        # Convert complex fields to JSON for HASH storage
        job_hash = {}
        for key, value in job_data.items():
            if value is None:
                job_hash[key] = ""
            elif isinstance(value, (dict, list)):
                job_hash[key] = json.dumps(value)
            elif isinstance(value, bool):
                job_hash[key] = "1" if value else "0"
            elif isinstance(value, datetime):
                job_hash[key] = value.isoformat()
            else:
                job_hash[key] = str(value)
        
        pipe = self._redis.pipeline()
        
        pipe.hset(self._job_key(job.id), mapping=job_hash)
        
        pipe.set(self._job_name_key(job.name, job.tenant_id), job.id)
        pipe.sadd(self._all_jobs_key(), job.id)
        pipe.sadd(self._tenant_jobs_key(job.tenant_id), job.id)
        
        # Enabled index
        if job.enabled:
            pipe.sadd(self._enabled_jobs_key(), job.id)
        else:
            pipe.srem(self._enabled_jobs_key(), job.id)
        
        # Due jobs index (ZSET by next_run_at timestamp)
        if job.enabled and job.next_run_at:
            score = job.next_run_at.timestamp()
            pipe.zadd(self._due_jobs_key(), {job.id: score})
        else:
            pipe.zrem(self._due_jobs_key(), job.id)
        
        pipe.execute()
        
        logger.debug(f"Saved job {job.id} ({job.name})")
        return job
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        self._ensure_connected()
        
        job_data = self._redis.hgetall(self._job_key(job_id))
        if not job_data:
            return None
        
        return self._parse_job(job_data)
    
    def get_job_by_name(self, name: str, tenant_id: str = "company") -> Optional[Job]:
        """Get job by name within a tenant."""
        self._ensure_connected()
        
        job_id = self._redis.get(self._job_name_key(name, tenant_id))
        if not job_id:
            return None
        
        return self.get_job(job_id)
    
    def list_jobs(
        self,
        tenant_id: Optional[str] = None,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Job]:
        """List jobs with optional filters.

        Fetches every job HASH in a SINGLE Redis pipeline round-trip instead of a
        per-job blocking ``hgetall`` loop. ``/api/cron`` is polled from the UI (and
        read by the ops-summary provider); the old ``1 + N`` per-call round-trips
        serialized the single API event loop and were the biggest navigation
        loop-blocker (see docs/PERF_NAVIGATION_INVESTIGATION.md, Evidence 6).
        """
        self._ensure_connected()
        
        # Determine which set to query
        if tenant_id:
            job_ids = self._redis.smembers(self._tenant_jobs_key(tenant_id))
        else:
            job_ids = self._redis.smembers(self._all_jobs_key())
        
        if enabled_only:
            enabled_ids = self._redis.smembers(self._enabled_jobs_key())
            job_ids = job_ids & enabled_ids
        
        # Sort for consistent pagination
        job_ids = sorted(job_ids)
        
        job_ids = list(job_ids)[offset:offset + limit]
        if not job_ids:
            return []
        
        # Batch-fetch every job HASH in ONE pipeline round-trip (was: an hgetall
        # per job — an N+1 that stalled the async API loop under UI polling).
        pipe = self._redis.pipeline()
        for job_id in job_ids:
            pipe.hgetall(self._job_key(job_id))
        raw_jobs = pipe.execute()
        
        # Parse + apply optional tag filter (order preserved from job_ids)
        jobs = []
        for job_data in raw_jobs:
            if not job_data:
                continue
            job = self._parse_job(job_data)
            if not job:
                continue
            if tags:
                if not job.tags or not set(tags).issubset(set(job.tags)):
                    continue
            jobs.append(job)
        
        return jobs
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job and its runs."""
        self._ensure_connected()
        
        job = self.get_job(job_id)
        if not job:
            return False
        
        pipe = self._redis.pipeline()
        
        pipe.delete(self._job_key(job_id))
        
        pipe.delete(self._job_name_key(job.name, job.tenant_id))
        pipe.srem(self._all_jobs_key(), job_id)
        pipe.srem(self._tenant_jobs_key(job.tenant_id), job_id)
        pipe.srem(self._enabled_jobs_key(), job_id)
        pipe.zrem(self._due_jobs_key(), job_id)
        
        # Remove runs (get all run IDs first)
        run_ids = self._redis.lrange(self._job_runs_key(job_id), 0, -1)
        for run_id in run_ids:
            pipe.delete(self._run_key(run_id))
            pipe.zrem(self._recent_runs_key(), run_id)
        pipe.delete(self._job_runs_key(job_id))
        
        pipe.execute()
        
        logger.info(f"Deleted job {job_id} ({job.name})")
        return True
    
    def update_job_runtime(
        self,
        job_id: str,
        last_run_at: Optional[datetime] = None,
        next_run_at: Optional[datetime] = None,
        consecutive_failures: Optional[int] = None
    ) -> None:
        """Update job runtime state."""
        self._ensure_connected()
        
        updates = {}
        if last_run_at:
            updates["last_run_at"] = last_run_at.isoformat()
        if next_run_at:
            updates["next_run_at"] = next_run_at.isoformat()
        if consecutive_failures is not None:
            updates["consecutive_failures"] = str(consecutive_failures)
        
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        
        if updates:
            self._redis.hset(self._job_key(job_id), mapping=updates)
            
            if next_run_at:
                job = self.get_job(job_id)
                if job and job.enabled:
                    self._redis.zadd(self._due_jobs_key(), {job_id: next_run_at.timestamp()})
    
    
    def save_run(self, run: JobRun) -> JobRun:
        """Create or update a run record."""
        self._ensure_connected()
        
        run.updated_at = datetime.now(timezone.utc)
        run_data = run.to_dict()
        
        # Convert to hash format
        run_hash = {}
        for key, value in run_data.items():
            if value is None:
                run_hash[key] = ""
            elif isinstance(value, RunStatus):
                run_hash[key] = value.value
            elif isinstance(value, datetime):
                run_hash[key] = value.isoformat()
            else:
                run_hash[key] = str(value)
        
        pipe = self._redis.pipeline()
        
        pipe.hset(self._run_key(run.id), mapping=run_hash)
        
        # Add to job's runs list (newest first)
        pipe.lpush(self._job_runs_key(run.job_id), run.id)
        
        # Add to recent runs (for global queries)
        score = run.started_at.timestamp() if run.started_at else time.time()
        pipe.zadd(self._recent_runs_key(), {run.id: score})
        
        # Trim old runs (keep last 100 per job)
        pipe.ltrim(self._job_runs_key(run.job_id), 0, 99)
        
        pipe.execute()
        
        return run
    
    def get_run(self, run_id: str) -> Optional[JobRun]:
        """Get run by ID."""
        self._ensure_connected()
        
        run_data = self._redis.hgetall(self._run_key(run_id))
        if not run_data:
            return None
        
        return self._parse_run(run_data)
    
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
        self._ensure_connected()
        
        if job_id:
            # Get runs for specific job
            run_ids = self._redis.lrange(
                self._job_runs_key(job_id),
                offset,
                offset + limit * 2  # Fetch extra to account for duplicates
            )
        else:
            # Get from recent runs (time-sorted)
            if since or until:
                min_score = since.timestamp() if since else "-inf"
                max_score = until.timestamp() if until else "+inf"
                run_ids = self._redis.zrangebyscore(
                    self._recent_runs_key(),
                    min_score,
                    max_score,
                    start=offset,
                    num=limit * 2
                )
            else:
                run_ids = self._redis.zrevrange(
                    self._recent_runs_key(),
                    offset,
                    offset + limit * 2 - 1
                )
        
        # Deduplicate run IDs while preserving order
        seen = set()
        unique_run_ids = []
        for run_id in run_ids:
            if run_id not in seen:
                seen.add(run_id)
                unique_run_ids.append(run_id)
        
        runs = []
        for run_id in unique_run_ids:
            if len(runs) >= limit:
                break
            run = self.get_run(run_id)
            if run:
                if status and run.status != status:
                    continue
                runs.append(run)
        
        return runs
    
    def get_due_jobs(self, before: Optional[datetime] = None) -> List[Job]:
        """Get enabled jobs that are due to run."""
        self._ensure_connected()
        
        before = before or datetime.now(timezone.utc)
        max_score = before.timestamp()
        
        # Get job IDs from due index
        job_ids = self._redis.zrangebyscore(
            self._due_jobs_key(),
            "-inf",
            max_score,
            start=0,
            num=100  # Limit batch size
        )
        
        jobs = []
        for job_id in job_ids:
            job = self.get_job(job_id)
            if job and job.enabled:
                jobs.append(job)
        
        return jobs
    
    
    def acquire_lock(
        self,
        resource: str,
        ttl_seconds: int = 30,
        holder: str = ""
    ) -> bool:
        """Acquire a distributed lock."""
        self._ensure_connected()
        
        key = self._lock_key(resource)
        # SET NX PX - only set if not exists, with expiry
        result = self._redis.set(
            key,
            holder or "locked",
            nx=True,
            px=ttl_seconds * 1000
        )
        return result is True
    
    def release_lock(self, resource: str, holder: str = "") -> bool:
        """Release a distributed lock (only if we hold it)."""
        if not holder:
            logger.warning("release_lock called without holder — refusing unconditional delete")
            return False
        self._ensure_connected()
        result = self._redis.eval(_LUA_RELEASE_LOCK, 1, self._lock_key(resource), holder)
        return bool(result)
    
    def extend_lock(self, resource: str, ttl_seconds: int, holder: str = "") -> bool:
        """Extend lock TTL if we hold it."""
        self._ensure_connected()
        
        key = self._lock_key(resource)
        
        # Verify ownership
        if holder:
            current = self._redis.get(key)
            if current != holder:
                return False
        
        return self._redis.pexpire(key, ttl_seconds * 1000)
    
    
    def _parse_job(self, data: dict) -> Job:
        """Parse job data from Redis hash."""
        if data.get("retry_policy"):
            try:
                data["retry_policy"] = json.loads(data["retry_policy"])
            except Exception:
                data["retry_policy"] = None
        
        if data.get("tags"):
            try:
                data["tags"] = json.loads(data["tags"])
            except Exception:
                data["tags"] = []
        
        if data.get("context"):
            try:
                data["context"] = json.loads(data["context"])
            except Exception:
                data["context"] = {}
        
        if "enabled" in data:
            data["enabled"] = data["enabled"] in ("1", "true", "True", True)
        
        # Handle empty strings as None
        for key in ["last_run_at", "next_run_at", "created_at", "updated_at"]:
            if key in data and data[key] == "":
                data[key] = None
        
        for key in ["consecutive_failures", "max_runtime_seconds"]:
            if key in data and data[key]:
                try:
                    data[key] = int(data[key])
                except Exception:
                    data[key] = 0
        
        return Job.from_dict(data)
    
    def _parse_run(self, data: dict) -> JobRun:
        """Parse run data from Redis hash."""
        # Handle status - keep as string for from_dict (it will convert to enum)
        # Don't convert to enum here since from_dict expects string
        
        # Handle empty strings as None
        for key in ["started_at", "completed_at", "scheduled_time"]:
            if key in data and data[key] == "":
                data[key] = None
        
        if "duration_seconds" in data and data["duration_seconds"]:
            try:
                data["duration_seconds"] = float(data["duration_seconds"])
            except Exception:
                data["duration_seconds"] = None
        
        if "attempt" in data and data["attempt"]:
            try:
                data["attempt"] = int(data["attempt"])
            except Exception:
                data["attempt"] = 1
        
        return JobRun.from_dict(data)
    
    
    def get_stats(self) -> dict:
        """Get scheduler statistics."""
        self._ensure_connected()
        
        return {
            "total_jobs": self._redis.scard(self._all_jobs_key()),
            "enabled_jobs": self._redis.scard(self._enabled_jobs_key()),
            "due_jobs": self._redis.zcount(self._due_jobs_key(), "-inf", datetime.now(timezone.utc).timestamp()),
            "total_runs": self._redis.zcard(self._recent_runs_key()),
            "backend": "redis",
            "redis_url": self.redis_url.replace(":6379", ":****") if ":" in self.redis_url else self.redis_url,
        }
    
    
    def get_latest_run(self, job_id: str) -> Optional[JobRun]:
        """Get the most recent run for a job."""
        runs = self.list_runs(job_id=job_id, limit=1)
        return runs[0] if runs else None
    
    def get_job_stats(self, job_id: str, days: int = 7) -> dict:
        """Get run statistics for a job over the past N days."""
        from datetime import timedelta
        
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        since = since - timedelta(days=days)
        
        runs = self.list_runs(job_id=job_id, since=since, limit=1000)
        
        total = len(runs)
        success = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
        failed = sum(1 for r in runs if r.status == RunStatus.FAILED)
        
        # Ensure durations are floats (Redis may return strings)
        durations = []
        for r in runs:
            if r.duration_seconds is not None:
                try:
                    durations.append(float(r.duration_seconds))
                except (TypeError, ValueError):
                    pass
        
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
    
    def get_stuck_runs(self, max_age_minutes: int = 30) -> List[JobRun]:
        """
        Get runs stuck in 'running' state longer than max_age_minutes.
        
        Used for recovery after server restart.
        """
        self._ensure_connected()
        from datetime import timedelta
        
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        
        # Get recent runs and filter for stuck ones
        # We check runs from the recent runs ZSET
        run_ids = self._redis.zrangebyscore(
            self._recent_runs_key(),
            "-inf",
            cutoff.timestamp(),
            start=0,
            num=100
        )
        
        stuck_runs = []
        for run_id in run_ids:
            run = self.get_run(run_id)
            if run and run.status == RunStatus.RUNNING:
                stuck_runs.append(run)
        
        return stuck_runs
