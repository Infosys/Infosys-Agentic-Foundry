"""
Configuration for Smart Code Executor.
All settings are dataclasses with sensible defaults — no external config files required.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class LLMConfig:
    """LLM provider configuration for code generation."""
    # Use IAF's model service by default; set model_name to the IAF model alias
    model_name: Optional[str] = None  # None = use IAF default model
    temperature: float = 0.2
    max_tokens: int = 4096
    system_prompt: str = (
        "You are an expert code generator. Given a goal, produce ONLY executable code — "
        "no explanations, no markdown fences, no comments unless essential. "
        "The code must be self-contained, handle its own imports, and print results to stdout. "
        "If the goal involves files, use paths relative to the current working directory. "
        "If creating visualizations, save to files (e.g., output.png) rather than showing interactively. "
        "IMPORTANT: Return ONLY raw code. No ```python fences. No prose."
    )


@dataclass
class ExecutionConfig:
    """Execution backend configuration."""
    backend: str = "subprocess"  # Only subprocess for now
    timeout_per_attempt: int = 60  # Seconds per execution attempt
    total_timeout: int = 300  # Max total seconds across all retries
    max_attempts: int = 5  # Max retry attempts
    max_memory_mb: int = 512  # Memory limit hint


@dataclass
class SecurityConfig:
    """Security restrictions for code execution."""
    network_access: bool = True
    blocked_commands: List[str] = field(default_factory=lambda: [
        "rm -rf /", "sudo", "mkfs", "dd if=", ":(){ :|:& };:",
        "shutdown", "reboot", "format", "del /f /s /q",
    ])
    max_file_size_mb: int = 50
    restrict_to_workspace: bool = True
    restricted_imports: List[str] = field(default_factory=lambda: [
        "ctypes", "subprocess",  # subprocess allowed internally, blocked in user code
    ])


@dataclass
class CacheConfig:
    """Caching configuration."""
    enabled: bool = True
    goal_cache_ttl: int = 3600  # 1 hour
    goal_cache_max_size: int = 1000
    result_cache_ttl: int = 1800  # 30 minutes
    result_cache_max_size: int = 500


@dataclass
class AsyncConfig:
    """Async task execution configuration."""
    enabled: bool = True
    worker_count: int = 2
    max_queue_size: int = 100
    result_ttl: int = 3600  # How long to keep completed task results
    cleanup_interval: int = 300  # Cleanup old tasks every 5 min


@dataclass
class WorkspaceConfig:
    """Workspace management configuration."""
    base_path: str = "./agent_workspaces/code_executor"
    cleanup_policy: str = "after_task"  # "after_task" | "ttl" | "manual"
    ttl_seconds: int = 3600


@dataclass
class AutoRecoveryConfig:
    """Automatic error recovery configuration."""
    install_packages: bool = True
    allowed_package_managers: List[str] = field(default_factory=lambda: ["pip", "npm"])
    max_install_retries: int = 3


@dataclass
class LanguageDefaults:
    """Default packages and interpreter paths per language."""
    python_interpreter: str = "python"
    node_interpreter: str = "node"
    bash_interpreter: str = "bash"
    python_default_packages: List[str] = field(default_factory=lambda: [
        "pandas", "numpy", "requests", "pyyaml",
    ])


@dataclass
class OutputConfig:
    """Output formatting configuration."""
    max_result_length: int = 10000
    summarize_long_results: bool = True
    allowed_output_extensions: List[str] = field(default_factory=lambda: [
        ".pdf", ".docx", ".xlsx", ".csv", ".json", ".png", ".jpg",
        ".svg", ".html", ".txt", ".md", ".zip",
    ])
    outputs_base_path: str = "./agent_workspaces/code_executor_outputs"
    max_output_size_mb: int = 100


@dataclass
class CodeExecutorConfig:
    """Root configuration for Smart Code Executor."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    async_config: AsyncConfig = field(default_factory=AsyncConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    auto_recovery: AutoRecoveryConfig = field(default_factory=AutoRecoveryConfig)
    languages: LanguageDefaults = field(default_factory=LanguageDefaults)
    output: OutputConfig = field(default_factory=OutputConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "CodeExecutorConfig":
        """Build config from a flat or nested dictionary."""
        cfg = cls()
        for section_name, section_cls in [
            ("llm", LLMConfig),
            ("execution", ExecutionConfig),
            ("security", SecurityConfig),
            ("cache", CacheConfig),
            ("async_config", AsyncConfig),
            ("workspace", WorkspaceConfig),
            ("auto_recovery", AutoRecoveryConfig),
            ("languages", LanguageDefaults),
            ("output", OutputConfig),
        ]:
            if section_name in data and isinstance(data[section_name], dict):
                section_data = data[section_name]
                section_obj = section_cls(**{
                    k: v for k, v in section_data.items()
                    if k in section_cls.__dataclass_fields__
                })
                setattr(cfg, section_name, section_obj)
        return cfg
