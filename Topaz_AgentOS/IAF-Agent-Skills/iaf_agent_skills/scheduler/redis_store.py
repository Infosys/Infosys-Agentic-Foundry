"""
Redis Job Store - Enterprise-scalable Job Storage

Replaces SQLiteJobStore for distributed deployments.
Stores jobs and runs in Redis with efficient indexing.

Key Structure:
    {prefix}:job:{id}           - HASH: Job definition
    {prefix}:job:name:{name}    - STRING: Job ID lookup by name
    {prefix}:jobs               - SET: All job IDs
    {prefix}:jobs:tenant:{id}   - SET: Job IDs by tenant
    {prefix}:jobs:enabled       - SET: Enabled job IDs
    {prefix}:jobs:due           - ZSET: Jobs by next_run_at (for scheduling)
    
    {prefix}:run:{id}           - HASH: Run record
    {prefix}:runs:job:{job_id}  - LIST: Run IDs for a job (newest first)
    {prefix}:runs:recent        - ZSET: Recent runs by timestamp
    
    {prefix}:lock:{resource}    - STRING: Distributed lock
"""

from __future__ import annotations
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from .models import Job, JobRun, RunStatus

logger = logging.getLogger(__name__)

_LUA_RELEASE_LOCK = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""


class RedisJobStore:
    """
    Redis-backed job store for enterprise deployments.
    
    Features:
    - Distributed access from multiple servers
    - Efficient indexing by tenant, enabled state, due time
    - Run history with automatic cleanup
    - Distributed locking support
    
    Usage:
        store = RedisJobStore(redis_url="redis://localhost:6379")
        await store.connect()
        
        job = Job(name="daily_report", skill_name="reporting", ...)
        await store.save_job(job)
        
        # Get jobs due to run
        due_jobs = await store.get_due_jobs()
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
        self._redis = None
        self._connected = False
    
    
    async def connect(self) -> None:
        """Connect to Redis."""
        if self._connected:
            return
        
        import redis.asyncio as aioredis
        self._redis = aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
        await self._redis.ping()
        self._connected = True
        logger.info("RedisJobStore connected to configured endpoint")
    
    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._redis:
            await self._redis.aclose()
            self._connected = False
            logger.info("RedisJobStore disconnected")
    
    async def __aenter__(self) -> 'RedisJobStore':
        await self.connect()
        return self
    
    async def __aexit__(self, *args) -> None:
        await self.disconnect()
    
    
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
    
    
    async def save_job(self, job: Job) -> Job:
        """
        Create or update a job.
        
        Maintains all indexes for efficient queries.
        """
        await self.connect()
        
        job.updated_at = datetime.now(timezone.utc)
        job_data = job.to_dict()
        
        # Convert dict/list fields to JSON strings for HASH storage
        job_hash = {
            k: json.dumps(v) if isinstance(v, (dict, list)) else (str(v) if v is not None else "")
            for k, v in job_data.items()
        }
        
        pipe = self._redis.pipeline()
        
        pipe.hset(self._job_key(job.id), mapping=job_hash)
        
        # Name lookup index
        pipe.set(self._job_name_key(job.name, job.tenant_id), job.id)
        
        # All jobs set
        pipe.sadd(self._all_jobs_key(), job.id)
        
        # Tenant index
        pipe.sadd(self._tenant_jobs_key(job.tenant_id), job.id)
        
        # Enabled index
        if job.enabled:
            pipe.sadd(self._enabled_jobs_key(), job.id)
        else:
            pipe.srem(self._enabled_jobs_key(), job.id)
        
        # Due jobs index (for scheduler to poll)
        if job.enabled and job.next_run_at:
            score = job.next_run_at.timestamp()
            pipe.zadd(self._due_jobs_key(), {job.id: score})
        else:
            pipe.zrem(self._due_jobs_key(), job.id)
        
        await pipe.execute()
        logger.debug(f"Saved job {job.id}: {job.name}")
        
        return job
    
    async def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        await self.connect()
        
        data = await self._redis.hgetall(self._job_key(job_id))
        if not data:
            return None
        
        return self._hash_to_job(data)
    
    async def get_job_by_name(self, name: str, tenant_id: str = "company") -> Optional[Job]:
        """Get job by name within a tenant."""
        await self.connect()
        
        job_id = await self._redis.get(self._job_name_key(name, tenant_id))
        if not job_id:
            return None
        
        return await self.get_job(job_id)
    
    async def list_jobs(
        self,
        tenant_id: Optional[str] = None,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Job]:
        """List jobs with optional filters."""
        await self.connect()
        
        # Get candidate job IDs
        if tenant_id and enabled_only:
            # Intersection of tenant and enabled
            job_ids = await self._redis.sinter(
                self._tenant_jobs_key(tenant_id),
                self._enabled_jobs_key()
            )
        elif tenant_id:
            job_ids = await self._redis.smembers(self._tenant_jobs_key(tenant_id))
        elif enabled_only:
            job_ids = await self._redis.smembers(self._enabled_jobs_key())
        else:
            job_ids = await self._redis.smembers(self._all_jobs_key())
        
        job_ids = list(job_ids)[offset:offset + limit]
        
        jobs = []
        for job_id in job_ids:
            job = await self.get_job(job_id)
            if job:
                if tags and not any(t in job.tags for t in tags):
                    continue
                jobs.append(job)
        
        return jobs
    
    async def delete_job(self, job_id: str) -> bool:
        """Delete a job and its indexes."""
        await self.connect()
        
        # Get job first for index cleanup
        job = await self.get_job(job_id)
        if not job:
            return False
        
        pipe = self._redis.pipeline()
        
        # Remove from all indexes
        pipe.delete(self._job_key(job_id))
        pipe.delete(self._job_name_key(job.name, job.tenant_id))
        pipe.srem(self._all_jobs_key(), job_id)
        pipe.srem(self._tenant_jobs_key(job.tenant_id), job_id)
        pipe.srem(self._enabled_jobs_key(), job_id)
        pipe.zrem(self._due_jobs_key(), job_id)
        
        await pipe.execute()
        logger.info(f"Deleted job {job_id}: {job.name}")
        
        return True
    
    async def update_job_runtime(
        self,
        job_id: str,
        last_run_at: Optional[datetime] = None,
        next_run_at: Optional[datetime] = None,
        consecutive_failures: Optional[int] = None
    ) -> None:
        """Update job runtime state (separate from config)."""
        await self.connect()
        
        updates = {"updated_at": datetime.now(timezone.utc).isoformat()}
        
        if last_run_at is not None:
            updates["last_run_at"] = last_run_at.isoformat()
        if next_run_at is not None:
            updates["next_run_at"] = next_run_at.isoformat()
        if consecutive_failures is not None:
            updates["consecutive_failures"] = str(consecutive_failures)
        
        await self._redis.hset(self._job_key(job_id), mapping=updates)
        
        # Update due jobs index
        if next_run_at is not None:
            job = await self.get_job(job_id)
            if job and job.enabled:
                await self._redis.zadd(self._due_jobs_key(), {job_id: next_run_at.timestamp()})
    
    
    async def save_run(self, run: JobRun) -> JobRun:
        """Create or update a run."""
        await self.connect()
        
        run_data = run.to_dict()
        
        # Convert for HASH storage
        run_hash = {
            k: str(v) if v is not None else ""
            for k, v in run_data.items()
        }
        
        pipe = self._redis.pipeline()
        
        pipe.hset(self._run_key(run.id), mapping=run_hash)
        
        # Add to job's run list (newest first)
        pipe.lpush(self._job_runs_key(run.job_id), run.id)
        pipe.ltrim(self._job_runs_key(run.job_id), 0, 99)  # Keep last 100
        
        # Add to recent runs (for global queries)
        timestamp = (run.started_at or datetime.now(timezone.utc)).timestamp()
        pipe.zadd(self._recent_runs_key(), {run.id: timestamp})
        
        # Cleanup old runs from recent index
        cutoff = (datetime.now(timezone.utc).timestamp() - (self.run_retention_days * 86400))
        pipe.zremrangebyscore(self._recent_runs_key(), 0, cutoff)
        
        await pipe.execute()
        
        return run
    
    async def get_run(self, run_id: str) -> Optional[JobRun]:
        """Get run by ID."""
        await self.connect()
        
        data = await self._redis.hgetall(self._run_key(run_id))
        if not data:
            return None
        
        return self._hash_to_run(data)
    
    async def list_runs(
        self,
        job_id: Optional[str] = None,
        status: Optional[RunStatus] = None,
        since: Optional[datetime] = None,
        until: Optional[datetime] = None,
        limit: int = 50,
        offset: int = 0
    ) -> List[JobRun]:
        """List runs with optional filters."""
        await self.connect()
        
        if job_id:
            # Get from job's run list
            run_ids = await self._redis.lrange(
                self._job_runs_key(job_id),
                offset,
                offset + limit - 1
            )
        else:
            # Get from recent runs index
            min_score = since.timestamp() if since else "-inf"
            max_score = until.timestamp() if until else "+inf"
            run_ids = await self._redis.zrevrangebyscore(
                self._recent_runs_key(),
                max_score,
                min_score,
                start=offset,
                num=limit
            )
        
        runs = []
        for run_id in run_ids:
            run = await self.get_run(run_id)
            if run:
                if status and run.status != status:
                    continue
                runs.append(run)
        
        return runs
    
    async def get_latest_run(self, job_id: str) -> Optional[JobRun]:
        """Get the most recent run for a job."""
        await self.connect()
        
        run_ids = await self._redis.lrange(self._job_runs_key(job_id), 0, 0)
        if not run_ids:
            return None
        
        return await self.get_run(run_ids[0])
    
    
    async def get_due_jobs(self, before: Optional[datetime] = None) -> List[Job]:
        """Get jobs that are due to run (next_run_at <= before)."""
        await self.connect()
        
        before = before or datetime.now(timezone.utc)
        
        # Get job IDs from due jobs ZSET
        job_ids = await self._redis.zrangebyscore(
            self._due_jobs_key(),
            "-inf",
            before.timestamp()
        )
        
        jobs = []
        for job_id in job_ids:
            job = await self.get_job(job_id)
            if job and job.enabled:
                jobs.append(job)
        
        return jobs
    
    async def get_stuck_runs(self, max_age_minutes: int = 30) -> List[JobRun]:
        """Get runs stuck in 'running' state longer than max_age_minutes."""
        await self.connect()
        
        cutoff = datetime.now(timezone.utc).timestamp() - (max_age_minutes * 60)
        
        run_ids = await self._redis.zrangebyscore(
            self._recent_runs_key(),
            cutoff - 86400,  # Look back a day max
            "+inf"
        )
        
        stuck = []
        for run_id in run_ids:
            run = await self.get_run(run_id)
            if run and run.status == RunStatus.RUNNING:
                if run.started_at and run.started_at.timestamp() < cutoff:
                    stuck.append(run)
        
        return stuck
    
    async def get_job_stats(self, job_id: str, days: int = 7) -> Dict[str, Any]:
        """Get run statistics for a job."""
        await self.connect()
        
        runs = await self.list_runs(job_id=job_id, limit=100)
        
        if not runs:
            return {"total_runs": 0}
        
        success_count = sum(1 for r in runs if r.status == RunStatus.SUCCESS)
        failure_count = sum(1 for r in runs if r.status == RunStatus.FAILED)
        durations = [r.duration_seconds for r in runs if r.duration_seconds]
        
        return {
            "total_runs": len(runs),
            "success_count": success_count,
            "failure_count": failure_count,
            "success_rate": success_count / len(runs) if runs else 0,
            "avg_duration": sum(durations) / len(durations) if durations else 0,
            "min_duration": min(durations) if durations else 0,
            "max_duration": max(durations) if durations else 0,
            "last_run": runs[0].to_dict() if runs else None,
        }
    
    
    async def acquire_lock(
        self,
        resource: str,
        ttl_seconds: int = 60,
        holder: str = ""
    ) -> bool:
        """
        Acquire a distributed lock.
        
        Uses Redis SET NX PX pattern for atomic locking.
        """
        await self.connect()
        
        holder = holder or f"worker-{time.time()}"
        result = await self._redis.set(
            self._lock_key(resource),
            holder,
            nx=True,  # Only set if not exists
            px=ttl_seconds * 1000  # Expire in milliseconds
        )
        
        return result is not None
    
    async def release_lock(self, resource: str, holder: str = "") -> bool:
        """Release a distributed lock (only if we hold it)."""
        if not holder:
            logger.warning("release_lock called without holder — refusing unconditional delete")
            return False
        await self.connect()
        result = await self._redis.eval(_LUA_RELEASE_LOCK, 1, self._lock_key(resource), holder)
        return bool(result)
    
    async def extend_lock(
        self,
        resource: str,
        ttl_seconds: int = 60,
        holder: str = ""
    ) -> bool:
        """Extend lock TTL (for long-running jobs)."""
        await self.connect()
        
        current = await self._redis.get(self._lock_key(resource))
        if current == holder or not holder:
            await self._redis.pexpire(self._lock_key(resource), ttl_seconds * 1000)
            return True
        
        return False
    
    
    def _hash_to_job(self, data: Dict[str, str]) -> Job:
        """Convert Redis HASH to Job object."""
        parsed = {}
        for k, v in data.items():
            if k in ("params", "tags"):
                parsed[k] = json.loads(v) if v else ([] if k == "tags" else {})
            elif k == "retry_policy":
                parsed[k] = json.loads(v) if v else None
            elif k in ("enabled",):
                parsed[k] = v.lower() == "true" if v else True
            elif k in ("max_runtime_seconds", "consecutive_failures"):
                parsed[k] = int(v) if v else 0
            else:
                parsed[k] = v if v else None
        
        return Job.from_dict(parsed)
    
    def _hash_to_run(self, data: Dict[str, str]) -> JobRun:
        """Convert Redis HASH to JobRun object."""
        parsed = {}
        for k, v in data.items():
            if k == "attempt":
                parsed[k] = int(v) if v else 1
            elif k == "duration_seconds":
                parsed[k] = float(v) if v else None
            else:
                parsed[k] = v if v else None
        
        return JobRun.from_dict(parsed)
