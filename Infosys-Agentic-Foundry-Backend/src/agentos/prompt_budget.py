# -*- coding: utf-8 -*-
# (c) 2024-25 Infosys Limited, Bangalore, India. All Rights Reserved.
"""
PromptBudget -- enforce model context-window limits BEFORE calling the LLM.

Estimates token count using a fast heuristic (chars / 3.5) and truncates
the lowest-priority sections so the total stays within the model's context
window minus a safety margin for the response.

Usage inside skill_agent_inference.py:

    from src.agentos.prompt_budget import PromptBudget

    budget = PromptBudget(model_name="gpt-4o")
    system_prompt = budget.enforce(
        system_prompt=system_prompt,
        user_message=user_message,
        reserved_for_response=2048,
    )
"""

import os
import re

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Model context-window registry (tokens)
# Override via env: MODEL_CONTEXT_WINDOW=128000
# ---------------------------------------------------------------------------
_DEFAULT_CONTEXT_WINDOW = 128_000

MODEL_CONTEXT_WINDOWS = {
    # OpenAI
    "gpt-4o":           128_000,
    "gpt-4o-mini":      128_000,
    "gpt-4-turbo":      128_000,
    "gpt-4":              8_192,
    "gpt-4-32k":        32_768,
    "gpt-3.5-turbo":    16_385,
    "gpt-3.5-turbo-16k":16_385,
    # Azure OpenAI (same underlying models)
    "gpt-4o-2024-05-13":128_000,
    "gpt-4o-2024-08-06":128_000,
    # GPT-5.x family
    "gpt-5":            256_000,
    "gpt-5-mini":       128_000,
    "gpt-5.1":          256_000,
    # Anthropic
    "claude-3-opus":    200_000,
    "claude-3-sonnet":  200_000,
    "claude-3-haiku":   200_000,
    "claude-3.5-sonnet":200_000,
    "claude-4-sonnet":  200_000,
    # Google
    "gemini-1.5-pro":  1_000_000,
    "gemini-1.5-flash":1_000_000,
    "gemini-2.0-flash":1_000_000,
    # Open source
    "llama-3-70b":       8_192,
    "llama-3.1-70b":   128_000,
    "mistral-large":    32_768,
    "mixtral-8x7b":     32_768,
}


def get_context_window(model_name: str) -> int:
    """Return the context window for a model (env override > registry > default)."""
    env_override = os.getenv("MODEL_CONTEXT_WINDOW")
    if env_override:
        try:
            return int(env_override)
        except ValueError:
            pass

    if not model_name:
        return _DEFAULT_CONTEXT_WINDOW

    # Exact match first
    name_lower = model_name.lower().strip()
    if name_lower in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[name_lower]

    # Prefix/substring match (e.g. "gpt-4o-2024-11-20" matches "gpt-4o")
    for key, window in sorted(MODEL_CONTEXT_WINDOWS.items(), key=lambda x: -len(x[0])):
        if key in name_lower or name_lower.startswith(key):
            return window

    return _DEFAULT_CONTEXT_WINDOW


# ---------------------------------------------------------------------------
# Token estimation
# ---------------------------------------------------------------------------
# Average English text: ~4 chars per token for GPT models.
# We use 3.5 for a conservative (over-)estimate so we truncate slightly
# earlier rather than hitting the API limit.
_CHARS_PER_TOKEN = max(0.1, float(os.getenv("PROMPT_BUDGET_CHARS_PER_TOKEN", "3.5")))


def estimate_tokens(text: str) -> int:
    """Fast heuristic token count (no tokenizer dependency)."""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


# ---------------------------------------------------------------------------
# Section-priority truncation
# ---------------------------------------------------------------------------
# Lower number = higher priority (kept last during truncation).
# These labels must match the markers injected into the system prompt.
_SECTION_PRIORITIES = {
    "core_instructions": 1,   # Base skill instructions -- never truncated
    "enterprise_context": 4,  # Enterprise context -- truncate first
    "knowledge_context":  3,  # Knowledge store retrieval
    "user_info":          5,  # Current user info
    "shell_instructions": 6,  # AgentShell filesystem docs
    "conversation":       2,  # Past conversation summary
}


class PromptBudget:
    """Enforce context-window limits on assembled prompts."""

    def __init__(self, model_name: str = ""):
        self.model_name = model_name
        self.context_window = get_context_window(model_name)
        self._truncation_log: list = []

    def enforce(
        self,
        system_prompt: str,
        user_message: str,
        reserved_for_response: int = 4096,
    ) -> str:
        """
        Truncate lowest-priority sections of system_prompt so the total
        (system + user + response reserve) fits within the context window.

        Returns the (possibly truncated) system_prompt.
        """
        self._truncation_log.clear()

        total_budget = self.context_window - reserved_for_response
        user_tokens = estimate_tokens(user_message)
        available_for_system = total_budget - user_tokens

        if available_for_system < 500:
            # Even without system prompt, user message alone is too large
            log.warning(
                f"[PromptBudget] User message alone ({user_tokens} est. tokens) "
                f"nearly exceeds context window ({self.context_window}). "
                f"Proceeding with minimal system prompt."
            )
            available_for_system = 500

        system_tokens = estimate_tokens(system_prompt)

        if system_tokens <= available_for_system:
            # Fits fine -- no truncation needed
            log.debug(
                f"[PromptBudget] Prompt fits: system={system_tokens}, "
                f"user={user_tokens}, budget={total_budget}, "
                f"window={self.context_window}"
            )
            return system_prompt

        # Need to truncate. Split into sections and remove lowest-priority first.
        log.info(
            f"[PromptBudget] Prompt too large: system={system_tokens} + "
            f"user={user_tokens} = {system_tokens + user_tokens} > "
            f"budget={total_budget}. Truncating..."
        )

        sections = self._split_sections(system_prompt)
        # Store original order index for reassembly after truncation
        # sections_with_idx: [(label, priority, content, original_idx), ...]
        sections = [(label, priority, content, idx) for idx, (label, priority, content) in enumerate(sections)]
        # Sort by priority (highest number = lowest priority = truncate first)
        sections.sort(key=lambda s: -s[1])

        tokens_to_cut = system_tokens - available_for_system

        for i, (label, priority, content, _idx) in enumerate(sections):
            if tokens_to_cut <= 0:
                break
            section_tokens = estimate_tokens(content)
            if priority <= 2:
                # High-priority sections: trim to half rather than remove
                trim_target = section_tokens // 2
                if trim_target > 100:
                    trimmed = self._trim_text(content, trim_target)
                    saved = section_tokens - estimate_tokens(trimmed)
                    sections[i] = (label, priority, trimmed, _idx)
                    tokens_to_cut -= saved
                    self._truncation_log.append(
                        f"Trimmed '{label}' by ~{saved} tokens"
                    )
            else:
                # Low-priority: remove entirely if needed
                if section_tokens <= tokens_to_cut * 1.5:
                    # Remove entirely
                    sections[i] = (label, priority, "", _idx)
                    tokens_to_cut -= section_tokens
                    self._truncation_log.append(
                        f"Removed '{label}' (~{section_tokens} tokens)"
                    )
                else:
                    # Trim to fit
                    keep_tokens = section_tokens - tokens_to_cut
                    trimmed = self._trim_text(content, keep_tokens)
                    saved = section_tokens - estimate_tokens(trimmed)
                    sections[i] = (label, priority, trimmed, _idx)
                    tokens_to_cut -= saved
                    self._truncation_log.append(
                        f"Trimmed '{label}' by ~{saved} tokens"
                    )

        if self._truncation_log:
            log.info(
                f"[PromptBudget] Truncation applied: "
                + "; ".join(self._truncation_log)
            )

        # Reassemble in original order (stored as index 0..N at parse time)
        sections.sort(key=lambda s: s[3])  # restore by original index
        result = "\n\n".join(content for _, _, content, _ in sections if content.strip())

        final_tokens = estimate_tokens(result)
        log.info(
            f"[PromptBudget] After truncation: system={final_tokens} tokens "
            f"(was {system_tokens}), user={user_tokens}, "
            f"total={final_tokens + user_tokens}/{total_budget}"
        )
        return result

    @property
    def truncation_log(self) -> list:
        """Return log of truncation actions taken (for audit trail)."""
        return list(self._truncation_log)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _split_sections(prompt: str) -> list:
        """
        Split prompt into labeled sections using ## headers.
        Returns list of (label, priority, content) tuples.
        """
        # Split on markdown ## headers
        parts = re.split(r'(?=\n##\s)', prompt)

        sections = []
        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Try to identify the section
            label = "core_instructions"
            header_match = re.match(r'^##\s*(.+)', part)
            if header_match:
                header = header_match.group(1).lower().strip()
                if any(kw in header for kw in ("enterprise", "business")):
                    label = "enterprise_context"
                elif any(kw in header for kw in ("knowledge", "learned", "past interaction")):
                    label = "knowledge_context"
                elif any(kw in header for kw in ("user info", "current user")):
                    label = "user_info"
                elif any(kw in header for kw in ("filesystem", "shell", "mount", "directory")):
                    label = "shell_instructions"
                elif any(kw in header for kw in ("conversation", "context", "history")):
                    label = "conversation"

            priority = _SECTION_PRIORITIES.get(label, 3)
            sections.append((label, priority, part))

        if not sections:
            sections.append(("core_instructions", 1, prompt))

        return sections

    @staticmethod
    def _trim_text(text: str, target_tokens: int) -> str:
        """Trim text to approximately target_tokens, keeping the start."""
        target_chars = int(target_tokens * _CHARS_PER_TOKEN)
        if len(text) <= target_chars:
            return text
        trimmed = text[:target_chars]
        # Try to break at a sentence or line boundary
        last_newline = trimmed.rfind('\n')
        last_period = trimmed.rfind('. ')
        break_at = max(last_newline, last_period)
        if break_at > target_chars * 0.7:
            trimmed = trimmed[:break_at + 1]
        return trimmed + "\n\n[... content truncated to fit context window ...]\n"
