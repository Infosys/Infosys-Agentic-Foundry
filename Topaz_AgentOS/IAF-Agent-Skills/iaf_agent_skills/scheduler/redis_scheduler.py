"""
Redis Scheduler - Enterprise Distributed Job Scheduler

Lightweight scheduler process that:
1. Checks for due jobs every N seconds
2. Acquires distributed lock to prevent duplicate scheduling
3. Pushes due jobs to the TaskQueue for workers to execute

This is the "beat" process - it only schedules, never executes.
Execution is done by separate worker processes.

Usage:
    # Run as scheduler (only 1 instance)
    python -m iaf_agent_skills.scheduler.worker --mode=scheduler
    
    # Run as worker (many instances)
    python -m iaf_agent_skills.scheduler.worker --mode=worker
"""

from __future__ import annotations
import asyncio
import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Optional, Callable, Any

from .models import Job, JobRun, RunStatus
from .redis_store import RedisJobStore
from ..task_system import TaskQueue, TaskDefinition, TaskPriority, TaskContext

logger = logging.getLogger(__name__)


class RedisScheduler:
    """
    Distributed job scheduler using Redis.
    
    Architecture:
    - ONE scheduler process checks due jobs and enqueues them
    - MANY worker processes execute tasks from the queue
    - Redis provides distributed locking to ensure single-scheduler
    
    Scheduler Loop:
    1. Acquire "scheduler" lock (prevents multiple schedulers)
    2. Query due jobs from RedisJobStore
    3. For each due job:
       - Acquire job-specific lock
       - Create TaskDefinition
       - Submit to TaskQueue
       - Update job's next_run_at
    4. Sleep for check_interval
    5. Repeat
    
    Features:
    - Single-scheduler guarantee via distributed lock
    - Job-level locking prevents duplicate runs
    - Heartbeat extends lock for long check cycles
    - Graceful shutdown on SIGTERM/SIGINT
    """
    
    def __init__(
        self,
        store: Optional[RedisJobStore] = None,
        queue: Optional[TaskQueue] = None,
        redis_url: str = "redis://localhost:6379",
        check_interval: int = 10,  # How often to check for due jobs
        lock_ttl: int = 30,  # Scheduler lock TTL
        worker_id: str = "",
    ):
        """
        Initialize scheduler.
        
        Args:
            store: RedisJobStore for job persistence
            queue: TaskQueue for submitting jobs to workers
            redis_url: Redis connection URL
            check_interval: Seconds between due-job checks
            lock_ttl: TTL for scheduler lock (should be > check_interval)
            worker_id: Unique ID for this scheduler instance
        """
        self.redis_url = redis_url
        self.store = store or RedisJobStore(redis_url=redis_url)
        self.queue = queue or TaskQueue(redis_url=redis_url, key_prefix="iaf:scheduler:queue")
        self.check_interval = check_interval
        self.lock_ttl = lock_ttl
        self.worker_id = worker_id or f"scheduler-{int(time.time())}"
        
        # Runtime state
        self._running = False
        self._shutdown_event = asyncio.Event()
        
        # APScheduler for cron parsing
        self._cron_trigger = None
    
    def _get_cron_trigger(self):
        """Lazy-load APScheduler's CronTrigger."""
        if self._cron_trigger is None:
            try:
                from apscheduler.triggers.cron import CronTrigger
                self._cron_trigger = CronTrigger
            except ImportError:
                logger.warning("APScheduler not installed. Using fallback cron parsing.")
                self._cron_trigger = False
        return self._cron_trigger
    
    def _calculate_next_run(self, job: Job, after: Optional[datetime] = None) -> datetime:
        """Calculate next run time from cron expression."""
        after = after or datetime.now(timezone.utc)
        
        CronTrigger = self._get_cron_trigger()
        
        if CronTrigger:
            try:
                trigger = CronTrigger.from_crontab(job.cron)
                next_fire = trigger.get_next_fire_time(None, after)
                if next_fire:
                    return next_fire.replace(tzinfo=None)
            except Exception as e:
                logger.warning(f"Failed to parse cron '{job.cron}': {e}")
        
        # Fallback: simple interval parsing
        parts = job.cron.split()
        if len(parts) >= 5:
            minute = parts[0]
            if minute.startswith("*/"):
                interval = int(minute.split("/")[1])
                return after + timedelta(minutes=interval)
        
        # Default: 1 hour
        return after + timedelta(hours=1)
    
    
    async def start(self) -> None:
        """
        Start the scheduler loop.
        
        This runs forever until stop() is called or SIGTERM received.
        """
        logger.info(f"🕐 Starting RedisScheduler ({self.worker_id})")
        logger.info(f"   Check interval: {self.check_interval}s")
        logger.info(f"   Lock TTL: {self.lock_ttl}s")
        
        await self.store.connect()
        await self.queue.connect()
        
        self._running = True
        self._shutdown_event.clear()
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: asyncio.create_task(self._handle_shutdown(s)))
        
        try:
            while self._running:
                # Try to become the active scheduler
                got_lock = await self.store.acquire_lock(
                    resource="scheduler",
                    ttl_seconds=self.lock_ttl,
                    holder=self.worker_id
                )
                
                if got_lock:
                    try:
                        await self._check_and_schedule()
                        
                        # Extend lock for next cycle
                        await self.store.extend_lock(
                            resource="scheduler",
                            ttl_seconds=self.lock_ttl,
                            holder=self.worker_id
                        )
                    except Exception as e:
                        logger.error(f"Error in scheduler loop: {e}", exc_info=True)
                else:
                    logger.debug(f"Another scheduler is active, waiting...")
                
                # Sleep with early wake on shutdown
                try:
                    await asyncio.wait_for(
                        self._shutdown_event.wait(),
                        timeout=self.check_interval
                    )
                    # If we get here, shutdown was requested
                    break
                except asyncio.TimeoutError:
                    # Normal case - timeout means continue loop
                    pass
                    
        finally:
            # Release lock on exit
            await self.store.release_lock("scheduler", self.worker_id)
            logger.info(f"🛑 RedisScheduler stopped ({self.worker_id})")
    
    async def stop(self) -> None:
        """Stop the scheduler gracefully."""
        logger.info("Stopping scheduler...")
        self._running = False
        self._shutdown_event.set()
    
    async def _handle_shutdown(self, signum: int) -> None:
        """Handle shutdown signal."""
        logger.info(f"Received signal {signum}, shutting down...")
        await self.stop()
    
    async def _check_and_schedule(self) -> None:
        """Check for due jobs and enqueue them."""
        now = datetime.now(timezone.utc)
        
        # Get jobs due to run
        due_jobs = await self.store.get_due_jobs(before=now)
        
        if due_jobs:
            logger.info(f"📋 Found {len(due_jobs)} due job(s)")
        
        for job in due_jobs:
            try:
                # Try to lock this specific job (prevents duplicate runs)
                job_lock = await self.store.acquire_lock(
                    resource=f"job:{job.id}",
                    ttl_seconds=job.max_runtime_seconds + 60,  # Job runtime + buffer
                    holder=self.worker_id
                )
                
                if not job_lock:
                    logger.debug(f"Job {job.name} already locked, skipping")
                    continue

                try:
                    run = JobRun(
                        job_id=job.id,
                        job_name=job.name,
                        status=RunStatus.PENDING,
                        input_task=job.task,
                        triggered_by="scheduler",
                        scheduled_time=job.next_run_at,
                    )
                    await self.store.save_run(run)

                    task = TaskDefinition(
                        id=run.id,  # Use run ID as task ID
                        task_type="skill",
                        payload={
                            "skill_name": job.skill_name,
                            "input": job.task,
                            "job_id": job.id,
                            "job_name": job.name,
                            "run_id": run.id,
                            "scheduled_time": job.next_run_at.isoformat() if job.next_run_at else None,
                            "params": job.params,
                            "lock_holder": self.worker_id,
                        },
                        context=TaskContext(
                            tenant_id=job.tenant_id,
                            user_id=job.user_id,
                            session_id=f"cron-{run.id}",
                            agent_id=job.agent_id,
                        ),
                        priority=TaskPriority.MEDIUM,
                        max_retries=job.retry_policy.max_retries if job.retry_policy else 0,
                    )

                    # Submit to queue
                    await self.queue.submit(task)

                    next_run = self._calculate_next_run(job, after=now)
                    await self.store.update_job_runtime(
                        job_id=job.id,
                        last_run_at=now,
                        next_run_at=next_run,
                    )

                    logger.info(f"✅ Scheduled job '{job.name}' (run: {run.id[:8]}), next: {next_run}")

                except Exception as dispatch_err:
                    logger.error(f"Failed to dispatch job {job.name}: {dispatch_err}", exc_info=True)
                    await self.store.release_lock(f"job:{job.id}", self.worker_id)

            except Exception as e:
                logger.error(f"Failed to schedule job {job.name}: {e}", exc_info=True)
    
    
    async def add_job(self, job: Job) -> Job:
        """Add a new job to the scheduler."""
        await self.store.connect()
        
        if not job.next_run_at:
            job.next_run_at = self._calculate_next_run(job)
        
        return await self.store.save_job(job)
    
    async def remove_job(self, job_id: str) -> bool:
        """Remove a job from the scheduler."""
        await self.store.connect()
        return await self.store.delete_job(job_id)
    
    async def enable_job(self, job_id: str) -> bool:
        """Enable a job."""
        await self.store.connect()
        job = await self.store.get_job(job_id)
        if job:
            job.enabled = True
            job.next_run_at = self._calculate_next_run(job)
            await self.store.save_job(job)
            return True
        return False
    
    async def disable_job(self, job_id: str) -> bool:
        """Disable a job."""
        await self.store.connect()
        job = await self.store.get_job(job_id)
        if job:
            job.enabled = False
            await self.store.save_job(job)
            return True
        return False
    
    async def trigger_job(self, job_id: str) -> Optional[str]:
        """Manually trigger a job immediately."""
        await self.store.connect()
        await self.queue.connect()
        
        job = await self.store.get_job(job_id)
        if not job:
            return None
        
        run = JobRun(
            job_id=job.id,
            job_name=job.name,
            status=RunStatus.PENDING,
            input_task=job.task,
            triggered_by="manual",
            scheduled_time=datetime.now(timezone.utc),
        )
        await self.store.save_run(run)
        
        task = TaskDefinition(
            id=run.id,
            task_type="skill",
            payload={
                "skill_name": job.skill_name,
                "input": job.task,
                "job_id": job.id,
                "job_name": job.name,
                "run_id": run.id,
                "params": job.params,
            },
            context=TaskContext(
                tenant_id=job.tenant_id,
                user_id=job.user_id,
                session_id=f"manual-{run.id}",
                agent_id=job.agent_id,
            ),
            priority=TaskPriority.HIGH,  # Manual triggers get high priority
        )
        
        await self.queue.submit(task)
        logger.info(f"🔧 Manually triggered job '{job.name}' (run: {run.id[:8]})")
        
        return run.id
    
    async def list_jobs(self, enabled_only: bool = False) -> list:
        """List all scheduled jobs."""
        await self.store.connect()
        return await self.store.list_jobs(enabled_only=enabled_only)
    
    async def get_job_runs(self, job_id: str, limit: int = 10) -> list:
        """Get recent runs for a job."""
        await self.store.connect()
        return await self.store.list_runs(job_id=job_id, limit=limit)
