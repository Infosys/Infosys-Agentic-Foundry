"""Static coverage for the session/force-logout fixes and custom-tool persistence wiring.

These are deliberately source-text assertions (no app boot): they guard that every gated
page keeps the Bug-3 coordinated-refresh wiring, that session-controls.js keeps all four
idle-timeout behaviours *and* its full public API, and that the backend custom-tool /
personal-skill plumbing stays in place. A new page or a careless edit that drops any of
this fails here instead of silently regressing in production.

Covers:
  * Bug 1 (run-gated idle), Bug 2 (cross-tab activity), Bug 3 (coordinated refresh),
    Bug 4 (cross-tab logout) — frontend.
  * Custom-tool loader robustness (§3), skill-save tool_scripts semantics (§4),
    personal-skill tool persistence (§5), bundled-tool entitlement fallback (§6).
"""

from __future__ import annotations

from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parents[1]          # IAF-Agent-Studio
ROOT = Path(__file__).resolve().parents[2]            # repo root
STATIC = STUDIO / "static"
SKILLS = ROOT / "IAF-Agent-Skills" / "iaf_agent_skills"

# Pages that carry a fetch wrapper with a 401 -> /auth/refresh retry path.
GATED_PAGES = [
    "dashboard_v2.html",
    "finops.html",
    "twin.html",
    "optimization.html",
    "skill-builder-v2.html",
    "workstreams.html",
    "workstream_detail.html",
    "workstream_new.html",
]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------- Bug 3 wiring

@pytest.mark.parametrize("page", GATED_PAGES)
def test_gated_page_includes_coordinated_refresh(page):
    html = _read(STATIC / page)
    assert "/static/auth-refresh.js" in html, f"{page} missing auth-refresh.js include"
    assert "__iafCoordinatedRefresh" in html, f"{page} does not call the coordinated refresh"
    # auth-refresh.js must load before session-controls.js so the coordinator is installed first.
    i_auth = html.find("/static/auth-refresh.js")
    i_sc = html.find("/static/session-controls.js")
    assert i_sc != -1 and i_auth < i_sc, f"{page}: auth-refresh.js must precede session-controls.js"


def test_index_has_coordinated_refresh_in_head():
    html = _read(STATIC / "index.html")
    assert "/static/auth-refresh.js" in html
    assert "__iafCoordinatedRefresh" in html


def test_auth_refresh_file_exists_and_never_stores_token():
    js = _read(STATIC / "auth-refresh.js")
    assert "__iafCoordinatedRefresh" in js
    # SEC-6: only a timestamp marker is persisted, never the access token.
    assert "iaf_last_refresh" in js
    assert "access_token" not in js, "auth-refresh.js must not touch the access token"


def test_bearer_pages_guard_undefined_token():
    # Pages that set Authorization from the refresh body must guard the cross-tab {} case.
    for page in ("twin.html", "optimization.html", "skill-builder-v2.html"):
        html = _read(STATIC / page)
        assert "if (data && data.access_token)" in html, (
            f"{page} would send 'Bearer undefined' on the cross-tab dedup path"
        )


# ------------------------------------------------ session-controls.js (Bugs 1,2,4)

def test_session_controls_has_all_idle_behaviours():
    js = _read(STATIC / "session-controls.js")
    assert "installWsHook" in js            # Bug 1: streamed frames count as activity
    assert "maybeLogout" in js              # Bug 1: run-gated logout
    assert "ABSOLUTE_MAX_MS" in js
    assert "iaf_last_activity" in js        # Bug 2: cross-tab activity key
    assert "broadcastActivity" in js
    assert "iaf_logout" in js               # Bug 4: cross-tab logout key
    assert "remoteLogout" in js


def test_session_controls_public_api_preserved():
    # The idle additions must NOT drop the existing user-menu API.
    js = _read(STATIC / "session-controls.js")
    for name in ("logout:", "showSessions:", "signOutEverywhere:", "beginRun:", "endRun:", "resetIdle:"):
        assert name in js, f"IafSessionControls export missing {name}"


def test_index_idle_timer_run_gated_and_cross_tab():
    html = _read(STATIC / "index.html")
    assert "maybeLogout" in html
    assert "this.isTyping" in html          # run-in-flight gate
    assert "iaf_last_activity" in html      # Bug 2
    assert "'iaf_logout'" in html           # Bug 4 broadcast


# ------------------------------------------------------------- backend plumbing

def test_models_tool_scripts_optional_none():
    src = _read(STUDIO / "shared" / "models.py")
    assert "tool_scripts: Optional[List[ToolScript]] = None" in src, (
        "SkillCreate.tool_scripts must default to None (preserve) not [] (delete-all)"
    )


def test_skill_versions_resolve_scripts():
    src = _read(STUDIO / "shared" / "skill_versions.py")
    assert "_resolve_scripts" in src
    assert "_read_live_tool_scripts" in src


def test_loader_normalizes_all_param_shapes():
    src = _read(SKILLS / "tools" / "skill_tool_loader.py")
    assert "_normalize_parameters" in src
    assert "required" in src


def test_personal_skills_sync_tool_scripts():
    src = _read(STUDIO / "routers" / "personal_skills.py")
    assert "_sync_tool_scripts" in src
    assert "tool_scripts" in src


def test_agent_bundled_tools_ride_on_skill_entitlement():
    src = _read(SKILLS / "agent.py")
    assert "_skill_usable" in src
    assert "_bundled_allowed" in src


# ---------------------------------------------- Copilot review hardening

def test_heartbeat_excluded_from_idle_activity():
    # Keep-alive heartbeats must not reset the idle timer (else unattended pages never log out).
    # session-controls.js carries heartbeat in its idle-ignore denylist; index.html guards inline.
    assert "heartbeat: 1" in _read(STATIC / "session-controls.js")
    assert "data.type !== 'heartbeat'" in _read(STATIC / "index.html")


def test_cross_tab_run_lease_present():
    for f in ("session-controls.js", "index.html"):
        assert "iaf_run_lease" in _read(STATIC / f), f"{f} missing cross-tab run lease"


def test_index_retry_drops_stale_authorization():
    html = _read(STATIC / "index.html")
    assert "delete hdrs2['Authorization']" in html


def test_retire_draft_only_when_active():
    assert "payload.save_mode !== 'new'" in _read(STATIC / "skill-builder-v2.html")


def test_global_existence_decides_post_vs_put():
    assert "globalExists" in _read(STATIC / "skill-builder-v2.html")


def test_personal_requests_pass_tenant():
    html = _read(STATIC / "skill-builder-v2.html")
    assert html.count("tenant_id=${encodeURIComponent") >= 4, "personal-skill requests must pass the tenant"


def test_tool_script_mirror_is_once_per_open():
    html = _read(STATIC / "skill-builder-v2.html")
    assert "_personalToolsSynced" in html


def test_entitlement_checker_exposes_decision():
    # §6/#1: the checker must expose the full Decision so explicit tool denials survive.
    assert ".decide" in _read(STUDIO / "security" / "dependencies.py")
    assert 'effect' in _read(SKILLS / "agent.py")


# ---------------------------------------- Copilot review round 2

def test_bundled_fallback_fails_closed_to_default_deny():
    # #1: fallback only for a confirmed no-rule default_deny; explicit deny / provider errors withhold.
    src = _read(SKILLS / "agent.py")
    assert "default_deny" in src
    assert "_tool_fallback_ok" in src


def test_ws_idle_denylist_ignores_broadcasts():
    # #8: background broadcasts must not reset the idle timer (precise denylist, no Bug-1 regression).
    js = _read(STATIC / "session-controls.js")
    assert "IDLE_IGNORE_TYPES" in js
    for t in ("snapshot", "deployment", "item_created"):
        assert t in js, f"denylist missing {t}"
    # Run-adjacent frame types must NOT be denylisted (could let a real run time out).
    for t in ("hitl: 1", "task_started", "task_completed"):
        assert t not in js, f"denylist wrongly includes run-adjacent {t}"


def test_one_personal_scope_predicate():
    # Finding A/B: a single shared predicate routes load/knowledge/component/delete.
    html = _read(STATIC / "skill-builder-v2.html")
    assert "_scopeIsPersonal" in html
    # editSkill, deleteSkill and the aux ops must all go through it.
    assert "this._scopeIsPersonal(skillScope)" in html
    assert "this._scopeIsPersonal(this.editorSourceScope)" in html


def test_lease_is_renewed_during_run():
    # #7: the run lease must be renewed on an interval, not only at the idle timeout.
    assert "startLeaseRenew" in _read(STATIC / "session-controls.js")
    assert "_leaseRenew" in _read(STATIC / "index.html")


def test_run_helpers_are_wired():
    # #9: beginRun/endRun actually bracket real runs.
    assert "IafSessionControls.beginRun" in _read(STATIC / "twin.html")
    assert "IafSessionControls.beginRun" in _read(STATIC / "skill-builder-v2.html")


def test_admin_delete_routes_by_scope():
    # #3: deleteSkill routes personal-scoped editors to the personal copy (not the global skill),
    # via the single shared predicate so it can't disagree with how the draft was loaded.
    html = _read(STATIC / "skill-builder-v2.html")
    assert "const isPersonal = this._scopeIsPersonal(this.editorSourceScope)" in html


def test_new_skill_cannot_overwrite_via_put():
    # #4 + #10: a genuinely new skill (no editingName) must POST; existence comes from
    # shared-scoped cards, never the personal-merged names list.
    assert "!!this.editingName && (this.skills" in _read(STATIC / "skill-builder-v2.html")


def test_retire_guards_unpublished_knowledge():
    # #5: never hard-delete a draft that still has unpublished knowledge files.
    assert "Draft kept" in _read(STATIC / "skill-builder-v2.html")


def test_canonical_fs_user_key():
    # #2: personal-skill keying resolves the same canonical key as execution.
    assert "_canonical_fs_user_id" in _read(STUDIO / "routers" / "personal_skills.py")


# ---------------------------------------- Copilot review round 3

def test_sync_tool_scripts_rejects_invalid_before_prune():
    # #1: an invalid filename must 400, not silently empty-prune every existing script.
    assert "Tool script filename must be a safe" in _read(STUDIO / "routers" / "personal_skills.py")


def test_load_personal_tools_preserves_on_failure():
    # #4: a failed tools request must not overwrite tool_scripts with [].
    assert "Failed to load personal tool scripts" in _read(STATIC / "skill-builder-v2.html")


def test_aux_ops_route_by_scope():
    # #2: knowledge + component ops route by the editor's personal scope, not always global.
    html = _read(STATIC / "skill-builder-v2.html")
    assert "_isPersonalEditorScope" in html
    assert "_knowledgeTenantQuery" in html


def test_global_list_filters_personal_rows():
    # #9: personal rows from /api/skills must be filtered out of the global list.
    assert "!s.scope || s.scope === 'shared'" in _read(STATIC / "skill-builder-v2.html")


def test_global_existence_uses_shared_cards():
    # #10: existence must come from shared-scoped cards, not the personal-merged names list.
    assert "(s._scope || s.scope || 'shared') === 'shared'" in _read(STATIC / "skill-builder-v2.html")


def test_tool_mutations_pass_tenant():
    html = _read(STATIC / "skill-builder-v2.html")
    assert "tools/save?tenant_id=" in html
    assert "/tools/${encodeURIComponent(filename)}?tenant_id=" in html


def test_run_cap_recomputed_on_policy():
    # #8-cap: ABSOLUTE_MAX_MS is recomputed after the logout policy loads.
    js = _read(STATIC / "session-controls.js")
    assert js.count("ABSOLUTE_MAX_MS = LOGOUT_MS * 6") >= 2


def test_refresh_has_weblocks_fallback():
    # #7: a cross-tab exclusion claim exists for the no-Web-Locks path.
    assert "HAS_WEB_LOCKS" in _read(STATIC / "auth-refresh.js")


def test_retire_checks_backend_knowledge_files():
    # #3: retirement checks actual draft files via the backend, not frontmatter refs.
    assert "/knowledge?${tq}" in _read(STATIC / "skill-builder-v2.html")


# ---------------------------------------- Copilot review round 4

def test_tool_filenames_validated_before_writes():
    # #2: invalid tool filenames must 400 BEFORE SKILL.md/component.html are written, so a
    # bad save can't leave a new skill in an unindexed folder.
    src = _read(STUDIO / "routers" / "personal_skills.py")
    assert "_validate_tool_script_filenames" in src
    i_val = src.find("_validate_tool_script_filenames(req.tool_scripts)")
    i_mkdir = src.find("skill_dir.mkdir(parents=True")
    assert 0 < i_val < i_mkdir, "filename validation must precede the first skill-file write"


def test_skill_md_read_returns_component():
    # #4: the personal skill-md read returns the saved component so reopen can hydrate it
    # instead of substituting a default template that a later save would persist.
    assert '"component_html": component_html' in _read(STUDIO / "routers" / "personal_skills.py")


def test_editor_hydrates_saved_component_on_reopen():
    # #4: editSkill hydrates componentHtml from the read so an unrelated save can't clobber it.
    html = _read(STATIC / "skill-builder-v2.html")
    assert "d.component_html" in html
    assert "_hadSavedComponent" in html


def test_component_only_edits_are_dirty():
    # #5: a component-only change is not reported as "No changes" and is not marked clean
    # until the main Save actually persists it.
    html = _read(STATIC / "skill-builder-v2.html")
    assert "!this.isDirty && !this.componentIsDirty" in html
    assert "const sendComponent" in html
    # the personal saveComponentSource branch must no longer clear the baseline without writing.
    assert "Component edits persist when you click Save" in html


def test_retire_promotes_component_before_delete():
    # #1: the draft's component is copied to the published global skill before the draft is
    # retired (the global publish payload does not carry it), else the only copy is lost.
    html = _read(STATIC / "skill-builder-v2.html")
    assert "/component-source`" in html
    assert "its component couldn't be copied to the global skill" in html


def test_refresh_waits_for_cross_tab_completion():
    # #3: a deferring tab waits for the leader's refresh to COMPLETE (pending vs completed
    # markers) rather than reporting success against a still-expired cookie.
    js = _read(STATIC / "auth-refresh.js")
    assert "iaf_refresh_pending" in js
    assert "waitForCompletion" in js
    assert "access_token" not in js, "auth-refresh.js must still never touch the access token"


# ---------------------------------------- Copilot review round 5

def test_component_load_does_not_clobber_dirty_baseline():
    # #8: the personal-draft Load branch seeds the dirty baseline ONLY when it's still null,
    # so re-loading after inline edits can't mark unsaved component HTML as saved (which would
    # make a component-only Save report "No changes" and drop the unsaved-close warning).
    html = _read(STATIC / "skill-builder-v2.html")
    assert "if (this._savedComponentHtml === null) this._savedComponentHtml = this.componentHtml;" in html


def test_personal_skill_copy_is_staged_then_promoted():
    # #5: skill folders are copied to a staging dir and atomically promoted, so a crash
    # mid-copytree can't leave a half-populated authoritative target.
    src = _read(STUDIO / "routers" / "personal_skills.py")
    assert ".tmp-" in src and "os.replace(staging, target)" in src
    i_copy = src.find("shutil.copytree(child, staging)")
    i_promote = src.find("os.replace(staging, target)")
    assert 0 < i_copy < i_promote, "copytree to staging must precede the atomic promote"
    # the standalone migration script gets the same treatment.
    script = _read(STUDIO / "scripts" / "merge_orphaned_personal_skills.py")
    assert "os.replace(staging, target)" in script


def test_admin_access_resolves_canonical_identity():
    # #6: the non-owner (admin) path still resolves the TARGET user's canonical fs key,
    # instead of returning the raw key that points at a stale alt-key folder after a restart.
    src = _read(STUDIO / "routers" / "personal_skills.py")
    i_not_owner = src.find("if not is_owner:")
    i_canon = src.find("_canonical_fs_user_id(tenant_id, username", i_not_owner)
    assert 0 < i_not_owner < i_canon, "admin branch must resolve the canonical fs key"


def test_migration_fails_fast_without_yaml():
    # #7: the standalone merge tool refuses at import when PyYAML is unavailable, rather than
    # copying folders while silently skipping the _index.yaml merge (leaving drafts invisible).
    script = _read(STUDIO / "scripts" / "merge_orphaned_personal_skills.py")
    assert "except ImportError as exc:" in script
    assert "PyYAML is required to merge personal skill indexes" in script
    assert "yaml = None" not in script, "the None-fallback that skipped the index merge must be gone"


# ---------------------------------------- Copilot review round 6

def test_refresh_takeover_gated_on_leader_ownership_not_waiter_timeout():
    # #4: a deferring tab takes over only once the leader's pending marker is gone/expired,
    # never on a fixed waiter timeout (which would start a concurrent refresh and revoke a token).
    js = _read(STATIC / "auth-refresh.js")
    assert "WAIT_MS" not in js, "the fixed waiter-timeout takeover must be gone"
    assert "PENDING_TTL_MS + POLL_MS" in js
    assert "access_token" not in js, "auth-refresh.js must still never touch the access token"


def test_admin_identity_resolved_via_auth_provider():
    # #6: a UUID-addressed admin request resolves the target's email via the auth provider
    # before choosing the filesystem key (coerce can't find the email folder without a hint).
    src = _read(STUDIO / "routers" / "personal_skills.py")
    i_notowner = src.find("if not is_owner:")
    i_getuser = src.find("provider.get_user(username)", i_notowner)
    assert 0 < i_notowner < i_getuser, "admin branch must resolve the target via the auth provider"


def test_submission_autosave_includes_tool_scripts():
    # #7: the pre-submit auto-save carries the author's CURRENT bundled tool scripts (same
    # authoritative array as the main Save), so the submission doesn't snapshot stale on-disk tools.
    html = _read(STATIC / "skill-builder-v2.html")
    i_submit = html.find("async submitForReview()")
    i_ts = html.find("tool_scripts: Array.isArray(this.editorForm.tool_scripts)", i_submit)
    assert i_submit > 0 and i_ts > i_submit, "submitForReview auto-save must include tool_scripts"
