"""
Mock External APIs Router — For testing LLM-native context source calling.

This creates fake external API endpoints that simulate:
- CloudTech License API
- CloudTech Billing API
- Other vendor APIs

These are callable by the agent via execute_code to verify
that API metadata is being used for actual calls.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, Header, HTTPException

logger = logging.getLogger(__name__)

router = APIRouter(tags=["mock-apis"])


@router.get("/mock/cloudtech/v1/customers/{customer_id}/licenses")
async def cloudtech_license_status(
    customer_id: str,
    period: Optional[str] = "current_month",
    authorization: Optional[str] = Header(None),
):
    """
    Mock CloudTech License Status API.
    
    This simulates: https://api.cloudtech.example.com/v1/customers/{customer_id}/licenses
    The agent should call this via execute_code when asked about CloudTech licenses.
    """
    logger.info("🎯 MOCK API CALLED: CloudTech License Status for customer=%s", customer_id)
    
    # Log that we were called (proves the agent used the metadata)
    print(f"\n{'='*60}")
    print(f"✅ MOCK CLOUDTECH LICENSE API CALLED!")
    print(f"   Customer ID: {customer_id}")
    print(f"   Period: {period}")
    print(f"   Auth Header: {authorization[:20]}..." if authorization else "   Auth: None")
    print(f"{'='*60}\n")
    
    return {
        "customer_id": customer_id,
        "as_of": datetime.now().isoformat(),
        "total_licensed": 150,
        "active_licenses": 142,
        "used_licenses": 138,
        "available_licenses": 12,
        "license_type": "Enterprise SaaS",
        "renewal_date": (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d"),
        "usage_by_feature": [
            {"feature": "Core Platform", "licensed": 150, "used": 130},
            {"feature": "Analytics Module", "licensed": 50, "used": 45},
            {"feature": "API Access", "licensed": 25, "used": 22},
        ],
        "status": "healthy",
        "alert": None,
    }


@router.get("/mock/cloudtech/v1/billing/summary")
async def cloudtech_billing_summary(
    period: Optional[str] = "current_month",
    authorization: Optional[str] = Header(None),
):
    """
    Mock CloudTech Billing Summary API.
    
    This simulates: https://api.cloudtech.example.com/v1/billing/summary
    """
    logger.info("🎯 MOCK API CALLED: CloudTech Billing Summary for period=%s", period)
    
    print(f"\n{'='*60}")
    print(f"✅ MOCK CLOUDTECH BILLING API CALLED!")
    print(f"   Period: {period}")
    print(f"{'='*60}\n")
    
    return {
        "period": period,
        "generated_at": datetime.now().isoformat(),
        "currency": "USD",
        "total_amount": 24500.00,
        "line_items": [
            {"description": "Enterprise SaaS License (150 seats)", "amount": 22500.00},
            {"description": "Analytics Module Add-on", "amount": 1500.00},
            {"description": "API Overage (2,340 extra calls)", "amount": 500.00},
        ],
        "payment_status": "pending",
        "due_date": (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d"),
        "invoice_number": "CT-INV-2026-0314",
    }


@router.get("/mock/test")
async def mock_test():
    """Simple test endpoint to verify mock router is loaded."""
    return {"status": "ok", "message": "Mock APIs router is active"}


# Demo host profiles — realistic data keyed by hostname
_ITOPS_HOSTS = {
    "prod-app-07": {
        "ci_name": "prod-app-07", "ci_type": "app_server", "tier": 1,
        "env": "production", "os": "RHEL 8.6", "ip": "10.10.1.7",
        "service": "payment-service", "team": "Platform Engineering",
        "owner": "Raj Patel", "email": "raj.patel@company.com",
        "disk": {"partition": "/var", "used_pct": 91.4, "used_gb": 182.8, "total_gb": 200.0,
                 "inode_pct": 44.1,
                 "top_dirs": [
                     {"path": "/var/log/payment-service", "size_gb": 87.3, "files": 14420},
                     {"path": "/var/log/nginx",           "size_gb": 31.6, "files": 892},
                     {"path": "/var/log/audit",           "size_gb": 22.1, "files": 310},
                     {"path": "/var/cache/yum",           "size_gb": 18.4, "files": 4110},
                     {"path": "/var/tmp",                 "size_gb": 12.8, "files": 237},
                 ]},
        "metrics": {"cpu_pct": 34.2, "mem_used_pct": 61.8,
                    "heap_used_pct": 58.4, "heap_used_gb": 7.0, "heap_max_gb": 12.0,
                    "gc_pause_ms": 120, "net_errors": 0, "p99_latency_ms": 210},
        "status": "degraded",
    },
    "prod-app-08": {
        "ci_name": "prod-app-08", "ci_type": "app_server", "tier": 1,
        "env": "production", "os": "RHEL 8.6", "ip": "10.10.1.8",
        "service": "payment-service", "team": "Platform Engineering",
        "owner": "Raj Patel", "email": "raj.patel@company.com",
        "disk": {"partition": "/var", "used_pct": 54.2, "used_gb": 108.4, "total_gb": 200.0,
                 "inode_pct": 22.0,
                 "top_dirs": [
                     {"path": "/var/log/payment-service", "size_gb": 42.1, "files": 8200},
                     {"path": "/var/log/nginx",           "size_gb": 18.3, "files": 620},
                 ]},
        "metrics": {"cpu_pct": 31.0, "mem_used_pct": 58.0,
                    "heap_used_pct": 55.0, "heap_used_gb": 6.6, "heap_max_gb": 12.0,
                    "gc_pause_ms": 95, "net_errors": 0, "p99_latency_ms": 195},
        "status": "healthy",
    },
    "prod-order-01": {
        "ci_name": "prod-order-01", "ci_type": "app_server", "tier": 1,
        "env": "production", "os": "RHEL 8.6", "ip": "10.10.2.1",
        "service": "order-service", "team": "Commerce Platform",
        "owner": "Priya Sharma", "email": "priya.sharma@company.com",
        "disk": {"partition": "/var", "used_pct": 48.3, "used_gb": 96.6, "total_gb": 200.0,
                 "inode_pct": 18.4,
                 "top_dirs": [
                     {"path": "/var/log/order-service", "size_gb": 28.4, "files": 5100},
                 ]},
        "metrics": {"cpu_pct": 42.1, "mem_used_pct": 78.4,
                    "heap_used_pct": 84.2, "heap_used_gb": 10.1, "heap_max_gb": 12.0,
                    "gc_pause_ms": 890, "net_errors": 14, "p99_latency_ms": 4280},
        "status": "critical",
    },
    "prod-order-db-01": {
        "ci_name": "prod-order-db-01", "ci_type": "database", "tier": 1,
        "env": "production", "os": "RHEL 8.6", "ip": "10.10.2.10",
        "service": "order-service", "team": "Commerce Platform",
        "owner": "Priya Sharma", "email": "priya.sharma@company.com",
        "disk": {"partition": "/data", "used_pct": 62.1, "used_gb": 621.0, "total_gb": 1000.0,
                 "inode_pct": 12.0, "top_dirs": []},
        "metrics": {"cpu_pct": 68.4, "mem_used_pct": 88.2,
                    "heap_used_pct": None, "heap_used_gb": None, "heap_max_gb": None,
                    "gc_pause_ms": None, "net_errors": 0,
                    "active_connections": 498, "max_connections": 500,
                    "p99_latency_ms": 3100},
        "status": "critical",
    },
    "prod-batch-01": {
        "ci_name": "prod-batch-01", "ci_type": "batch_server", "tier": 2,
        "env": "production", "os": "RHEL 8.6", "ip": "10.10.3.1",
        "service": "billing-reconciliation", "team": "Finance Engineering",
        "owner": "Anil Menon", "email": "anil.menon@company.com",
        "disk": {"partition": "/data", "used_pct": 71.3, "used_gb": 713.0, "total_gb": 1000.0,
                 "inode_pct": 28.0, "top_dirs": []},
        "metrics": {"cpu_pct": 0.4, "mem_used_pct": 12.1,
                    "heap_used_pct": None, "heap_used_gb": None, "heap_max_gb": None,
                    "gc_pause_ms": None, "net_errors": 0, "p99_latency_ms": None},
        "status": "degraded",
    },
    "prod-cache-01": {
        "ci_name": "prod-cache-01", "ci_type": "cache", "tier": 2,
        "env": "production", "os": "RHEL 8.6", "ip": "10.10.4.1",
        "service": "shared-cache", "team": "Platform Engineering",
        "owner": "Raj Patel", "email": "raj.patel@company.com",
        "disk": {"partition": "/", "used_pct": 38.2, "used_gb": 38.2, "total_gb": 100.0,
                 "inode_pct": 8.0, "top_dirs": []},
        "metrics": {"cpu_pct": 12.0, "mem_used_pct": 72.0,
                    "heap_used_pct": None, "heap_used_gb": None, "heap_max_gb": None,
                    "gc_pause_ms": None, "net_errors": 0, "p99_latency_ms": None},
        "status": "healthy",
    },
}

# Demo change log — realistic entries showing v2.4.1 deploy 6h before disk alert
_ITOPS_CHANGES = [
    {"id": "CHG0012347", "ci": "prod-app-07", "type": "deployment",
     "description": "Deploy payment-service v2.4.1 — updated log config, disabled rotation cron",
     "risk": "medium", "team": "Platform Engineering",
     "approved_by": "Raj Patel", "hours_ago": 6.2, "status": "closed"},
    {"id": "CHG0012346", "ci": "prod-order-01", "type": "deployment",
     "description": "Deploy order-service v3.1.2 — increased DB pool size to 500, cache TTL change",
     "risk": "medium", "team": "Commerce Platform",
     "approved_by": "Priya Sharma", "hours_ago": 0.67, "status": "closed"},
    {"id": "CHG0012345", "ci": "prod-order-db-01", "type": "config",
     "description": "Increase max_connections from 200 to 500 for order-service pool expansion",
     "risk": "high", "team": "DBA Team",
     "approved_by": "Vikram Nair", "hours_ago": 1.1, "status": "closed"},
    {"id": "CHG0012340", "ci": "prod-batch-01", "type": "config",
     "description": "Billing reconciliation job: increased input partition size — no memory adjustment",
     "risk": "low", "team": "Finance Engineering",
     "approved_by": "Anil Menon", "hours_ago": 18.0, "status": "closed"},
    {"id": "CHG0012335", "ci": "prod-app-08", "type": "deployment",
     "description": "Deploy payment-service v2.4.1 on prod-app-08 — same as prod-app-07",
     "risk": "medium", "team": "Platform Engineering",
     "approved_by": "Raj Patel", "hours_ago": 6.5, "status": "closed"},
]

_ITOPS_INCIDENTS = [
    {"id": "INC0098765", "ci": "prod-app-07", "title": "High disk utilization — prod-app-07 /var at 91%",
     "priority": "P2", "state": "In Progress", "assigned_to": "Raj Patel",
     "opened_mins_ago": 22, "sla_breach_mins": 58,
     "linked_change": "CHG0012347"},
    {"id": "INC0098770", "ci": "prod-order-01", "title": "order-service p99 latency 4x — DB connection pool exhausted",
     "priority": "P1", "state": "New", "assigned_to": "Priya Sharma",
     "opened_mins_ago": 8, "sla_breach_mins": 22,
     "linked_change": "CHG0012346"},
    {"id": "INC0098755", "ci": "prod-batch-01", "title": "billing-reconciliation OOM at row 7.8M — nightly job failed",
     "priority": "P2", "state": "In Progress", "assigned_to": "Anil Menon",
     "opened_mins_ago": 195, "sla_breach_mins": 185,
     "linked_change": "CHG0012340"},
]

_BATCH_JOBS = {
    "billing-reconciliation": {
        "job_name": "billing-reconciliation", "schedule": "0 2 * * *",
        "status": "failed", "exit_code": "OOM (exit 137)",
        "started_at": "02:14:38", "failed_at": "03:52:11",
        "last_successful_run": "2026-03-24 02:14:38",
        "input_partition": {"date": "2026-03-25", "rows": 11_200_000, "size_gb": 44.8},
        "last_checkpoint": {"row": 4_000_000, "timestamp": "03:06:22", "file": "/data/jobs/billing_recon_chk_4000000.parquet"},
        "memory_config": {"requested_gb": 8, "limit_gb": 8},
        "sla": {"deadline": "07:00:00", "breach_risk": True, "mins_remaining": 248},
        "owner": "Finance Engineering", "contact": "anil.menon@company.com",
    },
    "ar-daily-aging": {
        "job_name": "ar-daily-aging", "schedule": "0 3 * * *",
        "status": "success", "exit_code": "0",
        "started_at": "03:00:02", "completed_at": "03:18:44",
        "last_successful_run": "2026-03-25 03:18:44",
        "input_partition": {"date": "2026-03-25", "rows": 823_000, "size_gb": 3.2},
        "memory_config": {"requested_gb": 4, "limit_gb": 4},
        "sla": {"deadline": "06:00:00", "breach_risk": False, "mins_remaining": None},
        "owner": "Finance Engineering", "contact": "anil.menon@company.com",
    },
}


@router.get("/api/mock/itops/disk")
async def itops_disk(host: str = "prod-app-07"):
    """Simulates Datadog/Prometheus disk metrics for a host."""
    logger.info("🎯 MOCK ITOPS API: disk metrics for host=%s", host)
    h = _ITOPS_HOSTS.get(host)
    if not h:
        raise HTTPException(404, f"Host '{host}' not found in mock registry")
    d = h["disk"]
    return {
        "host": host, "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "partition": d["partition"],
        "used_pct": d["used_pct"], "used_gb": d["used_gb"], "total_gb": d["total_gb"],
        "free_gb": round(d["total_gb"] - d["used_gb"], 1),
        "inode_used_pct": d["inode_pct"],
        "alert_threshold_pct": 85,
        "status": "CRITICAL" if d["used_pct"] >= 90 else "WARNING" if d["used_pct"] >= 85 else "OK",
        "top_directories": d["top_dirs"],
        "trend": {
            "1h_ago_pct": round(d["used_pct"] - 0.3, 1),
            "6h_ago_pct": round(d["used_pct"] - 2.1, 1),
            "24h_ago_pct": round(d["used_pct"] - 7.4, 1),
            "growth_rate_pct_per_hour": 0.3,
            "estimated_full_in_hours": round((100 - d["used_pct"]) / 0.3, 1),
        },
    }


@router.get("/api/mock/itops/metrics")
async def itops_metrics(host: str = "prod-app-07"):
    """Simulates Datadog host metrics — CPU, memory, JVM heap, latency."""
    logger.info("🎯 MOCK ITOPS API: host metrics for host=%s", host)
    h = _ITOPS_HOSTS.get(host)
    if not h:
        raise HTTPException(404, f"Host '{host}' not found in mock registry")
    m = h["metrics"]
    result = {
        "host": host, "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "status": h["status"],
        "cpu": {"used_pct": m["cpu_pct"], "status": "OK" if m["cpu_pct"] < 80 else "WARNING"},
        "memory": {"used_pct": m["mem_used_pct"], "status": "OK" if m["mem_used_pct"] < 85 else "CRITICAL"},
        "network": {"errors_per_min": m["net_errors"]},
        "latency_p99_ms": m["p99_latency_ms"],
    }
    if m.get("heap_used_pct") is not None:
        result["jvm"] = {
            "heap_used_pct": m["heap_used_pct"],
            "heap_used_gb": m["heap_used_gb"],
            "heap_max_gb": m["heap_max_gb"],
            "gc_pause_ms_avg": m["gc_pause_ms"],
            "status": "CRITICAL" if m["heap_used_pct"] >= 80 else "WARNING" if m["heap_used_pct"] >= 70 else "OK",
        }
    if m.get("active_connections") is not None:
        result["database"] = {
            "active_connections": m["active_connections"],
            "max_connections": m["max_connections"],
            "connection_saturation_pct": round(m["active_connections"] / m["max_connections"] * 100, 1),
            "status": "CRITICAL" if m["active_connections"] >= m["max_connections"] * 0.95 else "OK",
        }
    return result


@router.get("/api/mock/itops/changes")
async def itops_changes(ci: str = "prod-app-07", hours: int = 24):
    """Simulates ServiceNow change request lookup for a CI."""
    logger.info("🎯 MOCK ITOPS API: changes for ci=%s hours=%d", ci, hours)
    now = datetime.now(timezone.utc)
    changes = [
        {**c,
         "opened_at": (now - timedelta(hours=c["hours_ago"])).isoformat() + "Z",
         "hours_ago": c["hours_ago"],
         "within_window": c["hours_ago"] <= hours,
         }
        for c in _ITOPS_CHANGES
        if c["ci"] == ci and c["hours_ago"] <= hours
    ]
    return {
        "ci": ci, "window_hours": hours,
        "total_changes": len(changes),
        "changes": changes,
        "correlation_hint": (
            f"⚠️ {len(changes)} change(s) found within {hours}h window — correlate with incident timeline"
            if changes else "No recent changes found"
        ),
    }


@router.get("/api/mock/itops/incidents")
async def itops_incidents(host: str = "prod-app-07"):
    """Simulates ServiceNow open incident lookup for a host."""
    logger.info("🎯 MOCK ITOPS API: open incidents for host=%s", host)
    now = datetime.now(timezone.utc)
    incidents = [
        {**i,
         "opened_at": (now - timedelta(minutes=i["opened_mins_ago"])).isoformat() + "Z",
         "sla_breach_at": (now + timedelta(minutes=i["sla_breach_mins"])).isoformat() + "Z",
         }
        for i in _ITOPS_INCIDENTS if i["ci"] == host
    ]
    return {
        "host": host,
        "open_incidents": len(incidents),
        "incidents": incidents,
    }


@router.get("/api/mock/itops/heap")
async def itops_heap(host: str = "prod-order-01"):
    """Simulates JVM heap dump analysis summary — GC pressure, object breakdown."""
    logger.info("🎯 MOCK ITOPS API: heap analysis for host=%s", host)
    h = _ITOPS_HOSTS.get(host)
    if not h or not h["metrics"].get("heap_used_pct"):
        raise HTTPException(404, f"No JVM metrics for host '{host}'")
    m = h["metrics"]
    return {
        "host": host, "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
        "heap_summary": {
            "used_gb": m["heap_used_gb"], "max_gb": m["heap_max_gb"],
            "used_pct": m["heap_used_pct"],
            "gc_pause_avg_ms": m["gc_pause_ms"],
            "gc_pause_p99_ms": m["gc_pause_ms"] * 3,
            "full_gc_count_1h": 14,
            "status": "CRITICAL" if m["heap_used_pct"] >= 80 else "WARNING",
        },
        "top_object_types": [
            {"class": "com.company.order.model.OrderCache", "retained_mb": 3840, "instances": 2_400_000},
            {"class": "io.netty.buffer.PooledByteBuf",      "retained_mb": 1280, "instances": 850_000},
            {"class": "java.util.concurrent.ConcurrentHashMap", "retained_mb": 640, "instances": 420_000},
        ],
        "diagnosis": "OrderCache is growing unbounded — TTL not applied after v3.1.2 cache config change",
        "recommendation": "Scale out 1 node immediately, set cache TTL=300s, consider rolling restart if heap > 90%",
    }


@router.get("/api/mock/itops/batch/status")
async def itops_batch_status(job: str = "billing-reconciliation"):
    """Simulates batch job status from internal job scheduler."""
    logger.info("🎯 MOCK ITOPS API: batch status for job=%s", job)
    j = _BATCH_JOBS.get(job)
    if not j:
        raise HTTPException(404, f"Batch job '{job}' not found in mock registry")
    return j


@router.get("/api/mock/itops/cmdb/{hostname}")
async def itops_cmdb_api(hostname: str):
    """Simulates a CMDB REST API — returns CI profile without needing SQL."""
    logger.info("🎯 MOCK ITOPS API: CMDB lookup for hostname=%s", hostname)
    h = _ITOPS_HOSTS.get(hostname)
    if not h:
        raise HTTPException(404, f"CI '{hostname}' not in CMDB")
    return {
        "ci_name": h["ci_name"], "ci_type": h["ci_type"], "tier": h["tier"],
        "environment": h["env"], "os": h["os"], "ip_address": h["ip"],
        "service": h["service"], "team": h["team"],
        "owner_name": h["owner"], "owner_email": h["email"],
        "status": h["status"],
        "blast_radius": "HIGH — Tier-1 production service" if h["tier"] == 1 else "MEDIUM — Tier-2 service",
    }
