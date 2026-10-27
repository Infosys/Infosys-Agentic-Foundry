"""
AgentOS Framework v2.3
The Enterprise Filesystem Agent with RBAC

A Python framework that provides AI Agents with a Standardized, Secure Operating Environment.
"""

from .kernel import (
    SafeKernel,
    UserRole,
    TeamResolver,
    RateLimiter,
    RateLimitExceeded,
    AccessDeniedError,
)
from .kernel_runtime import KernelRuntime, LocalKernelRuntime, RemoteKernelRuntime, create_kernel_runtime
from .tools import get_agent_tools, create_shell_tool
from .vector_store import VectorStore
from .credential_store import CredentialStore, Credential
from .secret_provider import (
    CredentialStoreSecretProvider,
    SecretProviderError,
    SecretProviderUnavailable,
    build_secret_provider,
)

__version__ = "2.3.0"
__all__ = [
    "SafeKernel",
    "KernelRuntime",
    "LocalKernelRuntime",
    "RemoteKernelRuntime",
    "create_kernel_runtime",
    "UserRole",
    "TeamResolver",
    "RateLimiter",
    "RateLimitExceeded",
    "AccessDeniedError",
    "get_agent_tools",
    "create_shell_tool",
    "VectorStore",
    "CredentialStore",
    "Credential",
    "CredentialStoreSecretProvider",
    "SecretProviderError",
    "SecretProviderUnavailable",
    "build_secret_provider",
]
