#!/usr/bin/env python3
"""
Worker CLI - Enterprise Scheduler Entry Point

Run as scheduler (beat) or worker process.

Usage:
    # Scheduler mode (only 1 instance) - checks due jobs, enqueues them
    python -m iaf_agent_skills.scheduler.worker --mode=scheduler
    
    # Worker mode (many instances) - executes tasks from queue
    python -m iaf_agent_skills.scheduler.worker --mode=worker
    python -m iaf_agent_skills.scheduler.worker --mode=worker --concurrency=4
    
    # Both modes (for development only)
    python -m iaf_agent_skills.scheduler.worker --mode=both

Environment Variables:
    REDIS_URL - Redis connection URL (default: redis://localhost:6379)
    WORKER_CONCURRENCY - Number of concurrent tasks (default: 1)
    SCHEDULER_INTERVAL - Seconds between due-job checks (default: 10)
"""

from __future__ import annotations
import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from iaf_agent_skills.scheduler.redis_store import RedisJobStore
from iaf_agent_skills.scheduler.redis_scheduler import RedisScheduler
from iaf_agent_skills.scheduler.models import Job, JobRun, RunStatus
from iaf_agent_skills.task_system import (
    TaskQueue,
    TaskDefinition,
    TaskResult,
    TaskStatus,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("iaf.worker")


class ScheduledTaskWorker:
    """
    Worker that executes scheduled tasks from the queue.
    
    Features:
    - Configurable concurrency (multiple tasks in parallel)
    - Heartbeat to extend job locks during long runs
    - Graceful shutdown on SIGTERM
    - Automatic retry on failure
    - Updates run records with results
    """
    
    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        concurrency: int = 1,
        heartbeat_interval: int = 30,
        worker_id: str = "",
    ):
        self.redis_url = redis_url
        self.concurrency = concurrency
        self.heartbeat_interval = heartbeat_interval
        self.worker_id = worker_id or f"worker-{int(time.time())}-{os.getpid()}"
        
        self.queue = TaskQueue(
            redis_url=redis_url,
            key_prefix="iaf:scheduler:queue",
        )
        self.store = RedisJobStore(redis_url=redis_url)
        
        self._running = False
        self._shutdown_event = asyncio.Event()
        self._active_tasks: dict = {}
        
        # Lazy-load agent
        self._agent = None
    
    def _get_agent(self):
        """Lazy-load the SkillAgent."""
        if self._agent is None:
            try:
                from iaf_agent_skills import SkillAgent
                self._agent = SkillAgent()
                logger.info("SkillAgent initialized")
            except Exception as e:
                logger.error(f"Failed to initialize SkillAgent: {e}")
                raise
        return self._agent
    
    async def start(self) -> None:
        """Start the worker."""
        logger.info(f"🔧 Starting ScheduledTaskWorker ({self.worker_id})")
        logger.info(f"   Concurrency: {self.concurrency}")
        logger.info(f"   Heartbeat: {self.heartbeat_interval}s")
        
        await self.queue.connect()
        await self.store.connect()
        
        self._running = True
        self._shutdown_event.clear()
        
        for sig in (signal.SIGTERM, signal.SIGINT):
            signal.signal(sig, lambda s, f: asyncio.create_task(self._handle_shutdown(s)))
        
        workers = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(self.concurrency)
        ]
        
        try:
            # Wait for shutdown or all workers to finish
            await asyncio.gather(*workers)
        finally:
            logger.info(f"🛑 ScheduledTaskWorker stopped ({self.worker_id})")
    
    async def stop(self) -> None:
        """Stop the worker gracefully."""
        logger.info("Stopping worker...")
        self._running = False
        self._shutdown_event.set()
    
    async def _handle_shutdown(self, signum: int) -> None:
        """Handle shutdown signal."""
        logger.info(f"Received signal {signum}, shutting down...")
        await self.stop()
    
    async def _worker_loop(self, worker_num: int) -> None:
        """Main worker loop - dequeue and execute tasks."""
        logger.info(f"Worker thread {worker_num} started")
        
        while self._running:
            try:
                # Dequeue a task
                task = await self.queue.dequeue(
                    lane="default",
                    timeout=5.0  # Block for up to 5 seconds
                )
                
                if task:
                    await self._execute_task(task, worker_num)
                else:
                    # No task available, check shutdown
                    if self._shutdown_event.is_set():
                        break
                        
            except Exception as e:
                logger.error(f"Worker {worker_num} error: {e}", exc_info=True)
                await asyncio.sleep(1)  # Brief pause before retry
        
        logger.info(f"Worker thread {worker_num} stopped")
    
    async def _execute_task(self, task: TaskDefinition, worker_num: int) -> None:
        """Execute a single task."""
        start_time = time.time()
        payload = task.payload or {}
        job_id = payload.get("job_id", "")
        run_id = payload.get("run_id", task.id)
        job_name = payload.get("job_name", getattr(task, "skill_name", ""))
        lock_holder = payload.get("lock_holder", "")
        
        logger.info(f"⚡ Worker {worker_num} executing: {job_name} (run: {run_id[:8]})")
        
        # Update run to RUNNING
        run = await self.store.get_run(run_id)
        if run:
            run.status = RunStatus.RUNNING
            run.started_at = datetime.now(timezone.utc)
            await self.store.save_run(run)
        
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(job_id, run_id, lock_holder)
        )
        
        try:
            agent = self._get_agent()
            response = await asyncio.to_thread(
                agent.execute,
                task=task.content,
                skill_name=task.skill_name,
                user_id=task.user_id,
            )
            
            # Success
            duration = time.time() - start_time
            
            # Acknowledge task
            result = TaskResult(
                task_id=task.id,
                status=TaskStatus.COMPLETED,
                response=str(response),
                duration_ms=duration * 1000,
            )
            await self.queue.ack(task.id, result)
            
            if run:
                run.status = RunStatus.SUCCESS
                run.completed_at = datetime.now(timezone.utc)
                run.duration_seconds = duration
                run.output_response = str(response)[:10000]  # Truncate
                await self.store.save_run(run)
            
            # Reset consecutive failures
            if job_id:
                await self.store.update_job_runtime(
                    job_id=job_id,
                    consecutive_failures=0,
                )
            
            logger.info(f"✅ Completed: {job_name} in {duration:.1f}s")
            
        except Exception as e:
            # Failure
            duration = time.time() - start_time
            error_msg = str(e)
            
            logger.error(f"❌ Failed: {job_name} - {error_msg}")
            
            # Nack task (may retry)
            await self.queue.nack(task.id, error_msg)
            
            if run:
                run.status = RunStatus.FAILED
                run.completed_at = datetime.now(timezone.utc)
                run.duration_seconds = duration
                run.error_message = error_msg[:5000]
                await self.store.save_run(run)
            
            # Increment consecutive failures
            if job_id:
                job = await self.store.get_job(job_id)
                if job:
                    await self.store.update_job_runtime(
                        job_id=job_id,
                        consecutive_failures=job.consecutive_failures + 1,
                    )
        
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            
            # Release job lock — must pass the same holder used at acquire time
            if job_id and lock_holder:
                await self.store.release_lock(f"job:{job_id}", lock_holder)
    
    async def _heartbeat_loop(self, job_id: str, run_id: str, lock_holder: str = "") -> None:
        """Send heartbeats to extend lock during execution."""
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            if job_id and lock_holder:
                await self.store.extend_lock(
                    resource=f"job:{job_id}",
                    ttl_seconds=self.heartbeat_interval * 2,
                    holder=lock_holder,
                )
                logger.debug(f"Heartbeat: job {job_id[:8]}")


async def run_scheduler(redis_url: str, interval: int) -> None:
    """Run the scheduler process."""
    scheduler = RedisScheduler(
        redis_url=redis_url,
        check_interval=interval,
    )
    await scheduler.start()


async def run_worker(redis_url: str, concurrency: int) -> None:
    """Run the worker process."""
    worker = ScheduledTaskWorker(
        redis_url=redis_url,
        concurrency=concurrency,
    )
    await worker.start()


async def run_both(redis_url: str, interval: int, concurrency: int) -> None:
    """Run both scheduler and worker (for development)."""
    scheduler = RedisScheduler(
        redis_url=redis_url,
        check_interval=interval,
    )
    worker = ScheduledTaskWorker(
        redis_url=redis_url,
        concurrency=concurrency,
    )
    
    await asyncio.gather(
        scheduler.start(),
        worker.start(),
    )


def main():
    parser = argparse.ArgumentParser(
        description="IAF Scheduler Worker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    parser.add_argument(
        "--mode",
        choices=["scheduler", "worker", "both"],
        default="worker",
        help="Run mode: scheduler (beat), worker, or both"
    )
    
    parser.add_argument(
        "--redis-url",
        default=os.environ.get("REDIS_URL", "redis://localhost:6379"),
        help="Redis connection URL"
    )
    
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("WORKER_CONCURRENCY", "1")),
        help="Number of concurrent worker tasks"
    )
    
    parser.add_argument(
        "--interval",
        type=int,
        default=int(os.environ.get("SCHEDULER_INTERVAL", "10")),
        help="Scheduler check interval in seconds"
    )
    
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        default="INFO",
        help="Logging level"
    )
    
    args = parser.parse_args()
    
    logging.getLogger().setLevel(getattr(logging, args.log_level))
    
    logger.info("=" * 60)
    logger.info("IAF Enterprise Scheduler")
    logger.info("=" * 60)
    logger.info(f"Mode: {args.mode}")
    logger.info("Redis: configured endpoint")
    if args.mode in ("worker", "both"):
        logger.info(f"Concurrency: {args.concurrency}")
    if args.mode in ("scheduler", "both"):
        logger.info(f"Check Interval: {args.interval}s")
    logger.info("=" * 60)
    
    try:
        if args.mode == "scheduler":
            asyncio.run(run_scheduler(args.redis_url, args.interval))
        elif args.mode == "worker":
            asyncio.run(run_worker(args.redis_url, args.concurrency))
        else:  # both
            asyncio.run(run_both(args.redis_url, args.interval, args.concurrency))
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
    
    logger.info("Shutdown complete")


if __name__ == "__main__":
    main()
