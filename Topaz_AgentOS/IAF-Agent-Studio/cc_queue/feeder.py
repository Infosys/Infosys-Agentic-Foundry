#!/usr/bin/env python3
"""
Queue Feeder — reads work items from a source and calls POST /api/queue/ingest.

Sources (today → future):
  file        — JSON or CSV file at a local path  (ready)
  servicenow  — ServiceNow incidents via REST API  (ready)
  excel       — Excel/XLSX file via openpyxl       (stub, add openpyxl dep)
  kafka       — Kafka topic via confluent-kafka     (stub)

Usage:
  python3 feeder.py --source file --path /path/to/feed.json
  python3 feeder.py --source file --path /path/to/feed.csv
  python3 feeder.py --source servicenow --sn-url https://company.service-now.com \\
                    --sn-user svc_agent --sn-pass "$SN_PASS" --sn-table incident
  python3 feeder.py --source file --path feed.json --dry-run   # preview only

Environment variables (override CLI defaults):
  STUDIO_URL            — base URL of the IAF Agent Studio server (default http://localhost:8080)
  AGENT_STUDIO_URL      — legacy alias for STUDIO_URL
  QUEUE_INGEST_API_KEY  — ingest API key if QUEUE_INGEST_API_KEY is set on the server
  QUEUE_FEED_FILE_PATH  — default file path when --path is omitted
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.error

import logging
logger = logging.getLogger(__name__)

DEFAULT_API_URL  = os.getenv("STUDIO_URL", os.getenv("AGENT_STUDIO_URL", "http://localhost:8080"))
DEFAULT_API_KEY  = os.getenv("QUEUE_INGEST_API_KEY", "")
DEFAULT_FEED_PATH = os.getenv("QUEUE_FEED_FILE_PATH", "")



def call_ingest(item: dict, api_url: str, api_key: str) -> dict:
    """POST one normalised item to /api/queue/ingest. Returns status dict."""
    url = f"{api_url.rstrip('/')}/api/queue/ingest"
    payload = json.dumps(item).encode("utf-8")
    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    if api_key:
        req.add_header("X-API-Key", api_key)

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read())
            return {"status": "ok", "id": body.get("id")}
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        # 409 Conflict = external_id already in queue (idempotent, not an error)
        if e.code == 409 or "conflict" in body.lower():
            return {"status": "skipped", "reason": "duplicate external_id"}
        return {"status": "error", "http_code": e.code, "reason": body[:300]}
    except Exception as ex:
        logger.error("Queue feed submission failed: %s", ex, exc_info=True)
        return {"status": "error", "reason": "submission failed"}



def read_json_file(path: str) -> list:
    """
    Read items from a JSON file.
    Accepts:
      - top-level array:  [ {item}, ... ]
      - wrapper object:   { "items": [...] }  (also: records, data, alerts, tickets, orders)
    """
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("items", "records", "data", "alerts", "tickets", "orders", "incidents"):
            if key in data and isinstance(data[key], list):
                return data[key]
    raise ValueError(
        f"Cannot parse JSON — expected array or object with an "
        f"items/records/data/alerts key. Got top-level type: {type(data).__name__}"
    )


def read_csv_file(path: str) -> list:
    """
    Read items from a CSV file.
    Expected columns (optional columns gracefully ignored):
      external_id, title, description, priority, domain, entity_id, tenant_id, source
    """
    items = []
    with open(path, "r", encoding="utf-8-sig") as f:  # utf-8-sig strips Excel BOM
        reader = csv.DictReader(f)
        for row in reader:
            # Strip whitespace from all string values
            items.append({k: v.strip() for k, v in row.items() if v is not None})
    return items


def read_servicenow(sn_url: str, sn_user: str, sn_pass: str,
                    table: str = "incident", limit: int = 50) -> list:
    """
    Pull open incidents from ServiceNow REST Table API.
    Maps SN fields to queue item schema.
    """
    import base64
    creds = base64.b64encode(f"{sn_user}:{sn_pass}".encode()).decode()

    query = "state=1^ORstate=2"  # New + In Progress
    fields = "sys_id,number,short_description,description,priority,category,assignment_group,opened_at"
    url = (
        f"{sn_url.rstrip('/')}/api/now/table/{table}"
        f"?sysparm_query={query}&sysparm_limit={limit}&sysparm_fields={fields}"
    )
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Basic {creds}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())

    items = []
    for rec in data.get("result", []):
        group = rec.get("assignment_group") or {}
        group_name = group.get("display_value", "") if isinstance(group, dict) else str(group)
        items.append({
            "external_id":  rec.get("number") or rec.get("sys_id"),
            "tenant_id":    "company",
            "domain":       rec.get("category", "itops"),
            "entity_id":    group_name,
            "title":        rec.get("short_description", ""),
            "description":  rec.get("description") or rec.get("short_description", ""),
            "priority":     _sn_priority(rec.get("priority", "3")),
            "source":       "servicenow",
        })
    return items


def _sn_priority(sn_p) -> str:
    """Map ServiceNow priority (1-5) to P1-P4."""
    return {"1": "P1", "2": "P1", "3": "P2", "4": "P3", "5": "P4"}.get(str(sn_p), "P3")



_FIELD_ALIASES = {
    "external_id": ["id", "alert_id", "ticket_id", "order_id", "incident_id", "number", "ref"],
    "title":       ["summary", "name", "subject", "short_description", "headline"],
    "description": ["detail", "body", "long_description", "notes", "details"],
    "domain":      ["category", "type", "area"],
    "entity_id":   ["host", "system", "server", "asset", "entity", "ci"],
    "priority":    ["severity", "urgency", "level"],
    "tenant_id":   ["tenant", "org", "company_id"],
}

def normalize_item(raw: dict) -> dict:
    """
    Map raw record (any schema) to the canonical queue item shape.
    Resolves field aliases so feed files don't need to match exactly.
    """
    resolved = dict(raw)  # start with copy

    for canonical, aliases in _FIELD_ALIASES.items():
        if canonical not in resolved or not resolved[canonical]:
            for alias in aliases:
                if alias in raw and raw[alias]:
                    resolved[canonical] = raw[alias]
                    break

    # Generate stable external_id if still missing
    if not resolved.get("external_id"):
        stable = json.dumps(raw, sort_keys=True, default=str)
        resolved["external_id"] = f"feed-{abs(hash(stable)) % 10**8:08d}"

    # Normalise priority to P1-P4
    priority_map = {
        "critical": "P1", "high": "P1", "p1": "P1", "1": "P1",
        "medium": "P2",                  "p2": "P2", "2": "P2",
        "low": "P3",                     "p3": "P3", "3": "P3",
        "info": "P4", "informational": "P4", "p4": "P4", "4": "P4",
    }
    raw_pri = str(resolved.get("priority", "P3")).strip().lower()
    resolved["priority"] = priority_map.get(raw_pri, "P3")

    return {
        "external_id": str(resolved.get("external_id", "")).strip(),
        "tenant_id":   str(resolved.get("tenant_id", "company")).strip(),
        "domain":      str(resolved.get("domain", "general")).strip(),
        "entity_id":   str(resolved.get("entity_id", "")).strip(),
        "title":       str(resolved.get("title", "Unnamed item")).strip()[:255],
        "description": str(resolved.get("description", resolved.get("title", ""))).strip(),
        "priority":    resolved["priority"],
        "source":      str(resolved.get("source", "feeder")).strip(),
    }



def main():
    parser = argparse.ArgumentParser(
        description="Queue Feeder — push work items into the autonomous queue processor"
    )
    parser.add_argument("--source", choices=["file", "servicenow", "excel", "kafka"],
                        default="file", help="Data source type")
    parser.add_argument("--path", default=DEFAULT_FEED_PATH,
                        help="File path (JSON or CSV). Also reads QUEUE_FEED_FILE_PATH env var.")
    parser.add_argument("--api-url", default=DEFAULT_API_URL,
                        help="IAF Agent Studio base URL")
    parser.add_argument("--api-key", default=DEFAULT_API_KEY,
                        help="Ingest API key (if QUEUE_INGEST_API_KEY is set on server)")
    parser.add_argument("--sn-url",   help="ServiceNow instance base URL")
    parser.add_argument("--sn-user",  help="ServiceNow username")
    parser.add_argument("--sn-pass",  help="ServiceNow password")
    parser.add_argument("--sn-table", default="incident",
                        help="ServiceNow table (incident, sc_request, etc.)")
    parser.add_argument("--sn-limit", type=int, default=50,
                        help="Max records to pull from ServiceNow")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print items without calling ingest (safe preview)")
    parser.add_argument("--tenant-id", default="company",
                        help="Override tenant_id for all ingested items")
    args = parser.parse_args()

    try:
        if args.source == "file":
            if not args.path:
                logger.debug("ERROR: --path is required for source=file "
                      "(or set QUEUE_FEED_FILE_PATH env var)")
                sys.exit(1)
            path = Path(args.path)
            if not path.exists():
                logger.debug(f"ERROR: File not found: {path}")
                sys.exit(1)
            suffix = path.suffix.lower()
            if suffix in (".json", ".jsonl"):
                raw_items = read_json_file(str(path))
            elif suffix == ".csv":
                raw_items = read_csv_file(str(path))
            else:
                logger.debug(f"ERROR: Unsupported extension '{suffix}'. Use .json or .csv")
                sys.exit(1)

        elif args.source == "servicenow":
            missing = [f for f, v in [("--sn-url", args.sn_url),
                                        ("--sn-user", args.sn_user),
                                        ("--sn-pass", args.sn_pass)] if not v]
            if missing:
                logger.debug(f"ERROR: {', '.join(missing)} required for source=servicenow")
                sys.exit(1)
            raw_items = read_servicenow(
                args.sn_url, args.sn_user, args.sn_pass, args.sn_table, args.sn_limit
            )

        else:
            logger.debug(f"ERROR: source='{args.source}' is not yet implemented. "
                  f"Contributions welcome!")
            sys.exit(1)

    except Exception as e:
        logger.debug(f"ERROR reading source: {e}")
        sys.exit(1)

    logger.debug(f"Read {len(raw_items)} item(s) from {args.source}")

    inserted = skipped = errors = 0
    error_ids = []

    for raw in raw_items:
        item = normalize_item(raw)
        if args.tenant_id and args.tenant_id != "company":
            item["tenant_id"] = args.tenant_id  # override if explicitly set

        if args.dry_run:
            logger.debug(f"  [DRY-RUN] {item['external_id']} | {item['priority']} | {item['title'][:60]}")
            inserted += 1
            continue

        result = call_ingest(item, args.api_url, args.api_key)
        if result["status"] == "ok":
            inserted += 1
        elif result["status"] == "skipped":
            skipped += 1
        else:
            errors += 1
            error_ids.append(item["external_id"])
            logger.debug(f"  ERROR [{item['external_id']}]: {result.get('reason', '')}")

    summary = {
        "source":             args.source,
        "total_read":         len(raw_items),
        "inserted":           inserted,
        "skipped_duplicate":  skipped,
        "errors":             errors,
        "error_ids":          error_ids,
        "dry_run":            args.dry_run,
        "timestamp":          datetime.now(timezone.utc).isoformat(),
    }
    logger.debug(json.dumps(summary, indent=2))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
