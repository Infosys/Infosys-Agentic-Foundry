"""
Cron Scheduler - Core Scheduling Engine

Manages job scheduling, execution, and lifecycle.
Uses APScheduler for cron parsing and timing.
"""

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List, Callable
import logging

# Support both relative import (when used as package) and direct import (when testing)
try:
    from .models import Job, JobRun, RunStatus, RetryPolicy
    from .store import JobStore, SQLiteJobStore
except ImportError:
    from scheduler_models import Job, JobRun, RunStatus, RetryPolicy
    from scheduler_store import JobStore, SQLiteJobStore

logger = logging.getLogger(__name__)


class CronScheduler:
    """
    Enterprise cron scheduler for agent tasks.
    
    Features:
    - Cron expression scheduling
    - Job persistence via JobStore
    - Run tracking with full history
    - Retry policies with backoff
    - Manual trigger support
    - Graceful shutdown
    
    Usage:
        scheduler = CronScheduler()
        
        job = Job(
            name="daily_report",
            skill_name="reporting",
            task="Generate sales report",
            cron="0 9 * * *"
        )
        scheduler.add_job(job)
        scheduler.start()
    """
    
    def __init__(
        self,
        store: Optional[JobStore] = None,
        executor: Optional[Callable] = None,
        check_interval: int = 60,
        max_concurrent_jobs: int = 5
    ):
        """
        Initialize scheduler.
        
        Args:
            store: JobStore for persistence (default: SQLiteJobStore)
            executor: Function to execute jobs. Signature: (job: Job) -> str
                      Should return the response string or raise exception.
            check_interval: How often to check for due jobs (seconds)
            max_concurrent_jobs: Maximum jobs to run simultaneously
        """
        self.store = store or SQLiteJobStore()
        self.executor = executor
        self.check_interval = check_interval
        self.max_concurrent_jobs = max_concurrent_jobs
        
        # Runtime state
        self._running = False
        self._scheduler_thread: Optional[threading.Thread] = None
        self._active_jobs: Dict[str, asyncio.Task] = {}
        self._lock = threading.Lock()
        
        # APScheduler for cron parsing (lazy import)
        self._apscheduler = None
    
    def _get_cron_trigger(self):
        """Lazy-load APScheduler's CronTrigger."""
        if self._apscheduler is None:
            try:
                from apscheduler.triggers.cron import CronTrigger
                self._apscheduler = CronTrigger
            except ImportError:
                logger.warning("APScheduler not installed. Using basic cron parsing.")
                self._apscheduler = False
        return self._apscheduler
    
    def _calculate_next_run(self, job: Job, after: Optional[datetime] = None) -> datetime:
        """
        Calculate the next run time for a job based on its cron expression.
        
        Args:
            job: The job to calculate for
            after: Calculate next run after this time (default: now)
        
        Returns:
            Next run datetime
        """
        after = after or datetime.now(timezone.utc)
        
        CronTrigger = self._get_cron_trigger()
        
        if CronTrigger:
            # Use APScheduler for accurate cron parsing
            try:
                trigger = CronTrigger.from_crontab(job.cron)
                next_fire = trigger.get_next_fire_time(None, after)
                if next_fire:
                    return next_fire.replace(tzinfo=None)
            except Exception as e:
                logger.warning(f"Failed to parse cron '{job.cron}': {e}")
        
        # Fallback: simple interval-based calculation
        # Parse common patterns
        parts = job.cron.split()
        if len(parts) >= 5:
            minute, hour, dom, month, dow = parts[:5]
            
            if minute == "*":
                # Every minute
                return after + timedelta(minutes=1)
            elif minute.startswith("*/"):
                # Every N minutes
                interval = int(minute.split("/")[1])
                return after + timedelta(minutes=interval)
            elif minute == "0" and hour == "*":
                # Every hour
                return after.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            elif minute == "0" and dom == "*" and month == "*" and dow == "*":
                # Daily at specific hour
                next_run = after.replace(hour=int(hour), minute=0, second=0, microsecond=0)
                if next_run <= after:
                    next_run += timedelta(days=1)
                return next_run
        
        # Default: 1 hour from now
        return after + timedelta(hours=1)
    
    
    def add_job(self, job: Job) -> Job:
        """
        Add a new job to the scheduler.
        
        If the job doesn't have a next_run_at, calculates it from the cron expression.
        """
        if job.next_run_at is None:
            job.next_run_at = self._calculate_next_run(job)
        
        saved = self.store.save_job(job)
        logger.info(f"Added job '{saved.name}' (id={saved.id}), next run: {saved.next_run_at}")
        return saved
    
    def get_job(self, job_id: str) -> Optional[Job]:
        """Get job by ID."""
        return self.store.get_job(job_id)
    
    def get_job_by_name(self, name: str, tenant_id: str = "company") -> Optional[Job]:
        """Get job by name."""
        return self.store.get_job_by_name(name, tenant_id)
    
    def list_jobs(
        self,
        tenant_id: Optional[str] = None,
        enabled_only: bool = False,
        tags: Optional[List[str]] = None
    ) -> List[Job]:
        """List jobs with optional filters."""
        return self.store.list_jobs(tenant_id=tenant_id, enabled_only=enabled_only, tags=tags)
    
    def update_job(self, job: Job) -> Job:
        """Update an existing job."""
        job.updated_at = datetime.now(timezone.utc)
        saved = self.store.save_job(job)
        logger.info(f"Updated job '{saved.name}' (id={saved.id})")
        return saved
    
    def delete_job(self, job_id: str) -> bool:
        """Delete a job."""
        job = self.store.get_job(job_id)
        if job:
            logger.info(f"Deleting job '{job.name}' (id={job_id})")
        return self.store.delete_job(job_id)
    
    def enable_job(self, job_id: str) -> Optional[Job]:
        """Enable a disabled job."""
        job = self.store.get_job(job_id)
        if job:
            job.enabled = True
            job.next_run_at = self._calculate_next_run(job)
            return self.update_job(job)
        return None
    
    def disable_job(self, job_id: str) -> Optional[Job]:
        """Disable a job (stops scheduling but preserves config)."""
        job = self.store.get_job(job_id)
        if job:
            job.enabled = False
            return self.update_job(job)
        return None
    
    
    def get_runs(
        self,
        job_id: Optional[str] = None,
        status: Optional[RunStatus] = None,
        limit: int = 50
    ) -> List[JobRun]:
        """Get run history."""
        return self.store.list_runs(job_id=job_id, status=status, limit=limit)
    
    def get_job_stats(self, job_id: str, days: int = 7) -> Dict[str, Any]:
        """Get job statistics."""
        return self.store.get_job_stats(job_id, days)
    
    
    def trigger_now(self, job_id: str, triggered_by: str = "manual") -> Optional[JobRun]:
        """
        Manually trigger a job to run immediately.
        
        Returns the JobRun record.
        """
        job = self.store.get_job(job_id)
        if not job:
            logger.warning(f"Cannot trigger: job {job_id} not found")
            return None
        
        return self._execute_job(job, triggered_by=triggered_by)
    
    def _execute_job(
        self,
        job: Job,
        triggered_by: str = "scheduler",
        scheduled_time: Optional[datetime] = None,
        attempt: int = 1,
        retry_of: Optional[str] = None
    ) -> JobRun:
        """
        Execute a job and record the run.
        
        Args:
            job: Job to execute
            triggered_by: How the job was triggered
            scheduled_time: Original scheduled time (for scheduler runs)
            attempt: Retry attempt number
            retry_of: ID of failed run being retried
        
        Returns:
            JobRun record
        """
        run = JobRun(
            job_id=job.id,
            job_name=job.name,
            status=RunStatus.RUNNING,
            started_at=datetime.now(timezone.utc),
            input_task=job.task,
            triggered_by=triggered_by,
            scheduled_time=scheduled_time or datetime.now(timezone.utc),
            attempt=attempt,
            retry_of=retry_of
        )
        self.store.save_run(run)
        
        logger.info(f"Executing job '{job.name}' (run_id={run.id}, attempt={attempt})")
        
        try:
            if self.executor:
                response = self.executor(job)
            else:
                response = self._default_executor(job)
            
            # Success
            run.status = RunStatus.SUCCESS
            run.output_response = response
            run.completed_at = datetime.now(timezone.utc)
            run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
            
            self.store.update_job_runtime(
                job.id,
                last_run_at=run.started_at,
                next_run_at=self._calculate_next_run(job, run.completed_at),
                consecutive_failures=0
            )
            
            logger.info(f"Job '{job.name}' completed successfully (duration={run.duration_seconds:.2f}s)")
            
        except Exception as e:
            # Failure
            run.status = RunStatus.FAILED
            run.error_message = str(e)
            run.completed_at = datetime.now(timezone.utc)
            run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
            
            job_data = self.store.get_job(job.id)
            consecutive_failures = (job_data.consecutive_failures if job_data else 0) + 1
            
            self.store.update_job_runtime(
                job.id,
                last_run_at=run.started_at,
                next_run_at=self._calculate_next_run(job, run.completed_at),
                consecutive_failures=consecutive_failures
            )
            
            logger.error(f"Job '{job.name}' failed: {e}")
            
            if job.retry_policy and attempt < job.retry_policy.max_retries:
                delay = job.retry_policy.get_delay(attempt)
                logger.info(f"Scheduling retry {attempt + 1}/{job.retry_policy.max_retries} in {delay}s")
                
                # Schedule retry (simplified - real implementation would use async)
                threading.Timer(
                    delay,
                    lambda: self._execute_job(
                        job,
                        triggered_by="retry",
                        scheduled_time=scheduled_time,
                        attempt=attempt + 1,
                        retry_of=run.id
                    )
                ).start()
        
        self.store.save_run(run)
        return run
    
    def _default_executor(self, job: Job) -> str:
        """
        Default executor that uses SkillAgent.
        
        Override via the executor parameter for custom execution.
        """
        # Lazy import to avoid circular dependency
        try:
            from iaf_agent_skills import SkillAgent
            from agent_os import create_kernel_runtime
            
            kernel = create_kernel_runtime(
                tenant_id=job.tenant_id,
                agent_id=job.agent_id,
                user_id=job.user_id,
                require_confirmation=False  # Scheduled jobs run unattended
            )
            
            agent = SkillAgent(
                kernel=kernel,
                user_id=job.user_id
            )
            
            response = agent.run(
                job.task,
                skill_name=job.skill_name,
                skip_memory=True  # Don't pollute memory with scheduled runs
            )
            
            return response
            
        except ImportError as e:
            raise RuntimeError(f"Cannot import agent dependencies: {e}")
    
    
    def start(self, blocking: bool = False):
        """
        Start the scheduler.
        
        Args:
            blocking: If True, blocks the current thread.
                      If False, runs in background thread.
        """
        if self._running:
            logger.warning("Scheduler already running")
            return
        
        self._running = True
        logger.info(f"Starting scheduler (check_interval={self.check_interval}s)")
        
        if blocking:
            self._scheduler_loop()
        else:
            self._scheduler_thread = threading.Thread(target=self._scheduler_loop, daemon=True)
            self._scheduler_thread.start()
    
    def stop(self, wait: bool = True, timeout: float = 30.0):
        """
        Stop the scheduler gracefully.
        
        Args:
            wait: Wait for active jobs to complete
            timeout: Maximum time to wait for jobs
        """
        if not self._running:
            return
        
        logger.info("Stopping scheduler...")
        self._running = False
        
        if wait and self._active_jobs:
            logger.info(f"Waiting for {len(self._active_jobs)} active jobs...")
            # Wait for active jobs with timeout
            start = datetime.now(timezone.utc)
            while self._active_jobs and (datetime.now(timezone.utc) - start).total_seconds() < timeout:
                threading.Event().wait(0.5)
        
        if self._scheduler_thread and self._scheduler_thread.is_alive():
            self._scheduler_thread.join(timeout=5)
        
        logger.info("Scheduler stopped")
    
    def _recover_stuck_jobs(self):
        """
        Recover jobs stuck in 'running' state from previous server crash.
        
        Called on scheduler startup. Marks any 'running' jobs as 'failed'
        since they couldn't have survived a server restart.
        """
        try:
            stuck_runs = self.store.get_stuck_runs(max_age_minutes=5)
            if stuck_runs:
                logger.warning(f"Found {len(stuck_runs)} stuck job run(s), marking as failed")
                for run in stuck_runs:
                    run.status = RunStatus.FAILED
                    run.error_message = "Job interrupted by server restart"
                    run.completed_at = datetime.now(timezone.utc)
                    run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
                    self.store.save_run(run)
                    logger.info(f"  Recovered run {run.id[:8]} for job '{run.job_name}'")
        except Exception as e:
            logger.error(f"Error recovering stuck jobs: {e}")
    
    def _scheduler_loop(self):
        """Main scheduler loop - checks for due jobs and executes them."""
        logger.info("Scheduler loop started")
        
        # Recover stuck jobs from previous run on first iteration
        self._recover_stuck_jobs()
        
        while self._running:
            try:
                self._check_and_execute_due_jobs()
            except Exception as e:
                logger.error(f"Error in scheduler loop: {e}")
            
            # Sleep in small increments to allow quick shutdown
            for _ in range(self.check_interval):
                if not self._running:
                    break
                threading.Event().wait(1)
        
        logger.info("Scheduler loop ended")
    
    def _check_and_execute_due_jobs(self):
        """Check for due jobs and execute them."""
        now = datetime.now(timezone.utc)
        due_jobs = self.store.get_due_jobs(before=now)

        if due_jobs:
            logger.info(f"Found {len(due_jobs)} due job(s) to execute")

        for job in due_jobs:
            with self._lock:
                if len(self._active_jobs) >= self.max_concurrent_jobs:
                    logger.warning(f"Max concurrent jobs reached ({self.max_concurrent_jobs}), skipping")
                    break

                # Check if job is already running (race-condition-safe: checked under lock)
                if job.id in self._active_jobs:
                    logger.debug(f"Job '{job.name}' already running, skipping")
                    continue

                # Register before launching so a concurrent check sees it immediately
                self._active_jobs[job.id] = datetime.now(timezone.utc)

            def run_job(j=job, scheduled=job.next_run_at):
                # Watchdog timer: kill job if it exceeds max_runtime_seconds
                timeout_secs = getattr(j, 'max_runtime_seconds', 300) or 300
                run_ref: list = [None]   # mutable so timeout closure can read the run

                def _timeout_handler():
                    run = run_ref[0]
                    logger.error(
                        f"Job '{j.name}' exceeded timeout ({timeout_secs}s) — marking TIMEOUT"
                    )
                    if run is not None:
                        run.status = RunStatus.TIMEOUT
                        run.error_message = f"Exceeded max_runtime_seconds={timeout_secs}"
                        run.completed_at = datetime.now(timezone.utc)
                        run.duration_seconds = (run.completed_at - run.started_at).total_seconds()
                        try:
                            self.store.save_run(run)
                        except Exception:
                            pass
                    with self._lock:
                        self._active_jobs.pop(j.id, None)

                watchdog = threading.Timer(timeout_secs, _timeout_handler)
                watchdog.daemon = True
                watchdog.start()

                try:
                    logger.info(f"Executing job '{j.name}' (id={j.id[:8]}, timeout={timeout_secs}s)")
                    run = self._execute_job(j, triggered_by="scheduler", scheduled_time=scheduled)
                    run_ref[0] = run
                finally:
                    watchdog.cancel()   # Job finished normally — cancel the watchdog
                    with self._lock:
                        self._active_jobs.pop(j.id, None)

            thread = threading.Thread(target=run_job, daemon=True)
            thread.start()
    
    
    @property
    def is_running(self) -> bool:
        """Check if scheduler is running."""
        return self._running
    
    @property
    def active_job_count(self) -> int:
        """Get number of currently executing jobs."""
        return len(self._active_jobs)
    
    def get_status(self) -> Dict[str, Any]:
        """Get scheduler status."""
        jobs = self.list_jobs()
        enabled = sum(1 for j in jobs if j.enabled)
        
        return {
            "running": self._running,
            "total_jobs": len(jobs),
            "enabled_jobs": enabled,
            "disabled_jobs": len(jobs) - enabled,
            "active_executions": len(self._active_jobs),
            "max_concurrent": self.max_concurrent_jobs,
            "check_interval_seconds": self.check_interval
        }
