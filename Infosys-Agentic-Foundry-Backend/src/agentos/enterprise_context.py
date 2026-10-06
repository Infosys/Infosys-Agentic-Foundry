# © 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
EnterpriseContextManager - Manages enterprise-wide context injection.

Loads and injects:
- Enterprise_Context.md (company-wide context)
- Skill-specific context files (contexts/{skill}_context.md)
- Policy files (policies/*.md)
- Entity guides (entity_guide.md)
- User profiles (users/{user_id}/profile.md)

These files are injected into every agent prompt as background context,
giving agents awareness of company systems, terminology, and rules.
"""

import os
import re
import threading
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from collections import OrderedDict

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Path sanitisation helper
# ---------------------------------------------------------------------------

# Only allow safe characters in user-supplied names (alphanumeric, dash, underscore, dot)
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")


def _sanitize_name(name: str, label: str = "name") -> str:
    """Validate and return a safe filename component.

    Raises ValueError if the name contains path separators, '..',
    or any character outside the safe set.
    """
    if not name:
        raise ValueError(f"{label} must not be empty")
    # Block path traversal explicitly
    if ".." in name or "/" in name or "\\" in name:
        raise ValueError(f"{label} contains disallowed characters: {name!r}")
    if not _SAFE_NAME_RE.match(name):
        raise ValueError(f"{label} contains disallowed characters: {name!r}")
    return name


class EnterpriseContextManager:
    """
    Manages enterprise context that gets injected into agent prompts.
    
    Directory Structure:
        enterprise_root/
        ├── Enterprise_Context.md          # Master context document
        ├── contexts/                      # Domain-specific context files
        │   ├── ap_context.md
        │   └── hr_context.md
        ├── policies/                      # Business rules
        │   ├── invoice_validation.md
        │   └── vendor_onboarding.md
        ├── entity_guide.md                # Entity recognition guide
        ├── databases/                     # Shared databases info
        └── users/
            └── {user_email}/
                └── profile.md             # User profile
    """

    def __init__(self, enterprise_root: str):
        """
        Initialize the EnterpriseContextManager.
        
        Args:
            enterprise_root: Path to the enterprise context root directory.
        """
        self.enterprise_root = Path(enterprise_root)
        # Bounded LRU cache — prevents unbounded memory growth when
        # many user profiles / policies are loaded over time.
        self._cache_max_size = int(os.getenv("ENTERPRISE_CONTEXT_CACHE_MAX", "256"))
        self._cache: OrderedDict[str, str] = OrderedDict()       # relative_path → content
        self._cache_mtime: Dict[str, float] = {}                  # relative_path → mtime
        self._lock = threading.Lock()
        log.info(f"EnterpriseContextManager initialized: root={self.enterprise_root}")

    # ---- Internal: path safety ----

    def _safe_resolve(self, relative_path: str) -> Path:
        """Resolve *relative_path* under enterprise_root and verify it stays inside.

        Raises ``ValueError`` if the resolved path escapes the root.
        """
        full = (self.enterprise_root / relative_path).resolve()
        root_resolved = self.enterprise_root.resolve()
        if not str(full).startswith(str(root_resolved)):
            raise ValueError(f"Path escapes enterprise root: {relative_path!r}")
        return full

    # ---- Public API ----

    def get_master_context(self) -> Optional[str]:
        """
        Load the master Enterprise_Context.md file.
        
        Returns:
            Content of Enterprise_Context.md, or None if not found.
        """
        return self._read_cached("Enterprise_Context.md")

    def get_skill_context(self, skill_name: str) -> Optional[str]:
        """
        Load skill-specific context (contexts/{skill}_context.md).
        
        Args:
            skill_name: The skill name (alphanumeric/dash/underscore only).
            
        Returns:
            Skill-specific context content, or None.
        """
        try:
            safe_name = _sanitize_name(skill_name, "skill_name")
        except ValueError as e:
            log.warning(f"[EnterpriseContext] Invalid skill_name: {e}")
            return None
        return self._read_cached(f"contexts/{safe_name}_context.md")

    def get_policy(self, policy_name: str) -> Optional[str]:
        """
        Load a specific policy document.
        
        Args:
            policy_name: Policy filename (without .md extension, safe chars only).
            
        Returns:
            Policy content, or None.
        """
        try:
            safe_name = _sanitize_name(policy_name, "policy_name")
        except ValueError as e:
            log.warning(f"[EnterpriseContext] Invalid policy_name: {e}")
            return None
        return self._read_cached(f"policies/{safe_name}.md")

    def get_all_policies(self) -> Dict[str, str]:
        """Load all policy documents from the policies/ directory."""
        policies_dir = self.enterprise_root / "policies"
        if not policies_dir.exists():
            return {}

        result = {}
        for f in sorted(policies_dir.glob("*.md")):
            try:
                content = f.read_text(encoding="utf-8")
                result[f.stem] = content
            except Exception as e:
                log.warning(f"[EnterpriseContext] Failed to read policy {f.name}: {e}")
        return result

    def get_entity_guide(self) -> Optional[str]:
        """Load the entity recognition guide."""
        return self._read_cached("entity_guide.md")

    def get_user_profile(self, user_email: str) -> Optional[str]:
        """
        Load a user's profile document.
        
        Args:
            user_email: The user's email (used as folder name).
            
        Returns:
            User profile content, or None.
        """
        # Sanitize email for folder name
        safe_email = user_email.replace("@", "_at_").replace(".", "_")
        try:
            safe_email = _sanitize_name(safe_email, "user_email")
        except ValueError as e:
            log.warning(f"[EnterpriseContext] Invalid user_email: {e}")
            return None
        return self._read_cached(f"users/{safe_email}/profile.md")

    def build_context_for_skill(
        self,
        skill_name: str,
        user_email: Optional[str] = None,
        include_policies: bool = True,
        max_context_length: int = 8000,
    ) -> str:
        """
        Build the full enterprise context string for a skill.
        
        Concatenates master context + skill context + policies + user profile,
        respecting the max length limit.
        
        Args:
            skill_name: Active skill name.
            user_email: Current user's email.
            include_policies: Whether to include policy documents.
            max_context_length: Maximum total character length of context.
            
        Returns:
            Combined context string.
        """
        parts = []
        current_len = 0

        # 1. Master context (always included first)
        master = self.get_master_context()
        if master:
            parts.append(f"# Enterprise Context\n\n{master}")
            current_len += len(master)

        # 2. Skill-specific context
        skill_ctx = self.get_skill_context(skill_name)
        if skill_ctx and current_len + len(skill_ctx) < max_context_length:
            parts.append(f"\n\n# {skill_name.replace('_', ' ').title()} Context\n\n{skill_ctx}")
            current_len += len(skill_ctx)

        # 3. User profile
        if user_email:
            profile = self.get_user_profile(user_email)
            if profile and current_len + len(profile) < max_context_length:
                parts.append(f"\n\n# Current User\n\n{profile}")
                current_len += len(profile)

        # 4. Policies (truncated if over limit)
        if include_policies:
            policies = self.get_all_policies()
            for name, content in policies.items():
                if current_len + len(content) < max_context_length:
                    parts.append(f"\n\n## Policy: {name.replace('_', ' ').title()}\n\n{content}")
                    current_len += len(content)
                else:
                    break

        return "\n".join(parts)

    def build_routing_context(self, max_length: int = 1500) -> str:
        """Build a concise enterprise summary for the skill router.

        Unlike ``build_context_for_skill`` (which returns up to 8 KB for the
        executor), this returns a *short* digest that the LLM-based router
        can use to disambiguate skills — typically the master context
        headline, the entity guide summary, and a one-liner per policy.

        Args:
            max_length: Soft cap on the returned string length.

        Returns:
            A compact context string, or ``""`` when nothing is available.
        """
        parts: list[str] = []
        chars = 0

        # 1. Master context — first ~500 chars (usually the summary block)
        master = self.get_master_context()
        if master:
            snippet = master[:500].rsplit("\n", 1)[0]  # cut at last newline
            parts.append(f"Enterprise overview: {snippet}")
            chars += len(snippet)

        # 2. Entity guide — first ~300 chars
        guide = self.get_entity_guide()
        if guide and chars < max_length:
            snippet = guide[:300].rsplit("\n", 1)[0]
            parts.append(f"Entity guide: {snippet}")
            chars += len(snippet)

        # 3. Policy names only (not full content — just awareness)
        if chars < max_length:
            policies = self.get_all_policies()
            if policies:
                names = ", ".join(policies.keys())
                parts.append(f"Active policies: {names}")
                chars += len(names)

        # 4. Skill-specific context *names* available
        contexts_dir = self.enterprise_root / "contexts"
        if contexts_dir.exists() and chars < max_length:
            ctx_names = [f.stem.replace("_context", "")
                         for f in sorted(contexts_dir.glob("*_context.md"))]
            if ctx_names:
                parts.append(f"Domain contexts available for: {', '.join(ctx_names)}")

        return "\n".join(parts) if parts else ""

    def list_available_contexts(self) -> Dict[str, Any]:
        """List all available context files with their content (no paths exposed)."""
        result = {
            "master_context": None,
            "skill_contexts": [],
            "policies": [],
            "entity_guide": None,
            "users": [],
        }

        master_file = self.enterprise_root / "Enterprise_Context.md"
        if master_file.exists():
            try:
                result["master_context"] = {
                    "size_bytes": master_file.stat().st_size,
                    "content": master_file.read_text(encoding="utf-8"),
                }
            except Exception as e:
                log.warning(f"[EnterpriseContext] Failed to read master context: {e}")

        contexts_dir = self.enterprise_root / "contexts"
        if contexts_dir.exists():
            for f in sorted(contexts_dir.glob("*.md")):
                try:
                    result["skill_contexts"].append({
                        "name": f.stem.replace("_context", ""),
                        "size_bytes": f.stat().st_size,
                        "content": f.read_text(encoding="utf-8"),
                    })
                except Exception as e:
                    log.warning(f"[EnterpriseContext] Failed to read context {f.name}: {e}")

        policies_dir = self.enterprise_root / "policies"
        if policies_dir.exists():
            for f in sorted(policies_dir.glob("*.md")):
                try:
                    result["policies"].append({
                        "name": f.stem,
                        "size_bytes": f.stat().st_size,
                        "content": f.read_text(encoding="utf-8"),
                    })
                except Exception as e:
                    log.warning(f"[EnterpriseContext] Failed to read policy {f.name}: {e}")

        entity_file = self.enterprise_root / "entity_guide.md"
        if entity_file.exists():
            try:
                result["entity_guide"] = {
                    "size_bytes": entity_file.stat().st_size,
                    "content": entity_file.read_text(encoding="utf-8"),
                }
            except Exception as e:
                log.warning(f"[EnterpriseContext] Failed to read entity guide: {e}")

        users_dir = self.enterprise_root / "users"
        if users_dir.exists():
            for d in sorted(users_dir.iterdir()):
                if d.is_dir():
                    result["users"].append(d.name)

        return result

    def save_master_context(self, content: str):
        """Save/overwrite the master Enterprise_Context.md."""
        file_path = self.enterprise_root / "Enterprise_Context.md"
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            self._invalidate_cache("Enterprise_Context.md")
            log.info("Saved Enterprise_Context.md")
        except Exception as e:
            log.error(f"[EnterpriseContext] Failed to save master context: {e}")
            raise

    def save_skill_context(self, skill_name: str, content: str):
        """Save a skill-specific context file."""
        safe_name = _sanitize_name(skill_name, "skill_name")
        rel_path = f"contexts/{safe_name}_context.md"
        file_path = self._safe_resolve(rel_path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            self._invalidate_cache(rel_path)
            log.info(f"Saved context for skill: {safe_name}")
        except Exception as e:
            log.error(f"[EnterpriseContext] Failed to save skill context {safe_name}: {e}")
            raise

    def save_policy(self, policy_name: str, content: str):
        """Save a policy document."""
        safe_name = _sanitize_name(policy_name, "policy_name")
        rel_path = f"policies/{safe_name}.md"
        file_path = self._safe_resolve(rel_path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            self._invalidate_cache(rel_path)
            log.info(f"Saved policy: {safe_name}")
        except Exception as e:
            log.error(f"[EnterpriseContext] Failed to save policy {safe_name}: {e}")
            raise

    def save_user_profile(self, user_email: str, content: str):
        """Save a user profile document."""
        safe_email = user_email.replace("@", "_at_").replace(".", "_")
        safe_email = _sanitize_name(safe_email, "user_email")
        rel_path = f"users/{safe_email}/profile.md"
        file_path = self._safe_resolve(rel_path)
        try:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            self._invalidate_cache(rel_path)
            log.info(f"Saved user profile: {user_email}")
        except Exception as e:
            log.error(f"[EnterpriseContext] Failed to save user profile {user_email}: {e}")
            raise

    # ---- Internal ----

    def _read_cached(self, relative_path: str) -> Optional[str]:
        """Read a file with mtime-based caching (thread-safe, LRU-bounded)."""
        try:
            full_path = self._safe_resolve(relative_path)
        except ValueError as e:
            log.warning(f"[EnterpriseContext] Path rejected: {e}")
            return None

        if not full_path.exists():
            return None

        try:
            current_mtime = full_path.stat().st_mtime
            cache_key = relative_path

            with self._lock:
                if cache_key in self._cache and self._cache_mtime.get(cache_key) == current_mtime:
                    # Move to end (most-recently-used) for LRU ordering
                    self._cache.move_to_end(cache_key)
                    return self._cache[cache_key]

            content = full_path.read_text(encoding="utf-8")

            with self._lock:
                self._cache[cache_key] = content
                self._cache_mtime[cache_key] = current_mtime
                # Move to end (freshest)
                self._cache.move_to_end(cache_key)
                # Evict oldest entries when cache exceeds max size
                while len(self._cache) > self._cache_max_size:
                    evicted_key, _ = self._cache.popitem(last=False)
                    self._cache_mtime.pop(evicted_key, None)

            return content
        except Exception as e:
            log.warning(f"[EnterpriseContext] Failed to read {relative_path}: {e}")
            return None

    def _invalidate_cache(self, relative_path: str):
        """Remove a specific entry from cache (thread-safe)."""
        with self._lock:
            self._cache.pop(relative_path, None)
            self._cache_mtime.pop(relative_path, None)
