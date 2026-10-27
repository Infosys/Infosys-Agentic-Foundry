"""
IAF Agent Scheduler - Enterprise Cron Jobs

Schedule agent tasks to run on cron schedules with full tracking.

Features:
- Cron expression scheduling (minute, hourly, daily, weekly, monthly)
- Job persistence (SQLite for dev, Redis for enterprise)
- Distributed scheduling with separate scheduler/worker processes
- Run history with status tracking
- Retry policies with exponential backoff
- Manual trigger support
- Enable/disable jobs without deletion
- Distributed locking for multi-server deployments

Usage (Single Server - Development):
    from iaf_agent_skills.scheduler import CronScheduler, Job
    
    scheduler = CronScheduler()
    job = Job(name="daily_report", skill_name="reporting", cron="0 9 * * *")
    scheduler.schedule(job)
    scheduler.start()

Usage (Enterprise - Redis Backend):
    # Terminal 1: Run scheduler (beat process)
    python -m iaf_agent_skills.scheduler.worker --mode=scheduler
    
    # Terminal 2+: Run workers (can be many)
    python -m iaf_agent_skills.scheduler.worker --mode=worker --concurrency=4

Programmatic (Redis):
    from iaf_agent_skills.scheduler import RedisScheduler, RedisJobStore, Job
    
    scheduler = RedisScheduler(redis_url="redis://localhost:6379")
    await scheduler.add_job(Job(name="report", skill_name="reporting", cron="0 9 * * *"))
    await scheduler.start()  # Runs forever checking due jobs
"""

from .models import Job, JobRun, Schedule, RunStatus, RetryPolicy
from .store import JobStore, SQLiteJobStore
from .scheduler import CronScheduler
from .redis_store import RedisJobStore
from .redis_scheduler import RedisScheduler
from .sync_redis_store import SyncRedisJobStore

__all__ = [
    # Models
    "Job",
    "JobRun", 
    "Schedule",
    "RunStatus",
    "RetryPolicy",
    # SQLite backend (development)
    "JobStore",
    "SQLiteJobStore",
    "CronScheduler",
    # Redis backend (enterprise - async)
    "RedisJobStore",
    "RedisScheduler",
    # Redis backend (enterprise - sync wrapper)
    "SyncRedisJobStore",
]
