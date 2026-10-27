"""
DEPRECATED — credential_store has moved to agent_os.credential_store.

This shim re-exports the public API for backwards compatibility and will be
removed in v2.4. Update your imports:

    # old
    from iaf_agent_skills.credential_store import CredentialStore
    # new
    from agent_os.credential_store import CredentialStore

The deprecated `skill=` parameter on get() / list() / resolve_for_api() still
works but emits a DeprecationWarning. Use `consumer=` instead.
"""
import warnings

warnings.warn(
    "iaf_agent_skills.credential_store is deprecated. "
    "Import from agent_os.credential_store instead. "
    "This shim will be removed in v2.4.",
    DeprecationWarning,
    stacklevel=2,
)

from agent_os.credential_store import (  # noqa: F401
    Credential,
    AuditEntry,
    CredentialBackend,
    EnvBackend,
    FernetFileBackend,
    CredentialStore,
    get_credential_store,
    get_credential,
)
