# Verification Scripts

This folder contains ad-hoc and live verification utilities. They are useful
for manual smoke tests, demos, and security validation, but they are not part of
the core runtime packages.

Use the formal test suites for automated regression coverage:

- `tests/`
- `IAF-Agent-Studio/tests/`
- `IAF-Agent-Skills/tests/`
- `agent_os/tests/`

See also [docs/README.md](../../docs/README.md) and
[SECURITY_TESTING_GUIDE.md](../../docs/SECURITY_TESTING_GUIDE.md).

Current utilities:

- `check_db.py` - inspects live knowledge DB episode columns and entity indexes.
- `check_entities.py` - inspects where extracted entities are stored in SQLite.
- `setup_security_test.py` - seeds scoped demo credentials and external access allowlist entries.
- `test_cron_hitl.py` - live cron-to-HITL approval flow driver.
- `verify_live.py` - inspects live knowledge DB DecisionTrace fields.
- `verify_phase7.py` - inspects live Phase 7 tool I/O and reasoning data.
- `verify_enterprise_restore.py` - creates backup checksum manifests and runs
  deterministic, read-only verification against an isolated restored data root.
  `capture` requires an explicit output path and accepts an optional
  `--redis-snapshot` inside the backup root; `verify` refuses roots that
  overlap the active `DATA_ROOT` and exits non-zero when a required check fails.
  Add `--run-live` only after secret-injecting `RECOVERY_LIVE_BASE_URL`,
  `RECOVERY_REDIS_URL`, `RECOVERY_LIVE_TOKEN`, and
  `RECOVERY_LIVE_CONFIRMATION=isolated-recovery-cell`; production Redis
  host/port reuse is rejected.
- `run_recovery_drill.py` - collects live evidence from an isolated recovery
  cell: scheduler leader status, signed-file rendering, a drill-prefixed queue
  canary, and SLO timing values. It writes sanitized JSON locally and can submit
  the evidence to `/api/recovery-readiness/evidence`; with `--verify`, it runs
  `/api/recovery-readiness/verify` using the submitted evidence id.

Example:

```bash
python3 scripts/verification/run_recovery_drill.py \
  --api-url "$RECOVERY_LIVE_BASE_URL" \
  --token "$RECOVERY_LIVE_TOKEN" \
  --queue-api-key "$QUEUE_INGEST_API_KEY" \
  --queue-count 3 \
  --submit \
  --verify
```
