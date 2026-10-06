"""
LLM-powered code generation for Smart Code Executor.

Uses IAF's existing model infrastructure (LangChain chat models) to
generate code from natural-language goals, and to fix broken code.
"""

import logging
import re
from typing import Optional

from src.agentos.code_executor.config import LLMConfig

logger = logging.getLogger("agentos.code_executor.llm_codegen")


class LLMCodeGenerator:
    """
    Generates executable code from English goals using a LangChain chat model.
    Also provides code-fix capability for iterative error recovery.
    """

    def __init__(self, config: LLMConfig, llm: Optional[object] = None):
        """
        Args:
            config: LLM configuration (model name, temperature, system prompt).
            llm: Optional pre-built LangChain chat model. If None, will try to
                 load via IAF's model service at first use.
        """
        self.config = config
        self._llm = llm
        self._initialized = False

    async def _ensure_llm(self):
        """Lazy-load the LLM model via IAF's model service."""
        if self._llm is not None:
            self._initialized = True
            return

        try:
            # Try IAF's global model service
            from src.models.model_service import global_model_service
            model_name = self.config.model_name or global_model_service.default_model_name
            self._llm = await global_model_service.get_llm_model(
                model_name=model_name,
                temperature=self.config.temperature,
            )
            self._initialized = True
            logger.info(f"LLM loaded via IAF model service: {model_name}")
        except Exception as e1:
            logger.warning(f"Could not load via IAF model service: {e1}")
            try:
                # Fallback: try direct Azure/OpenAI instantiation from env vars
                self._llm = self._create_fallback_llm()
                self._initialized = True
                logger.info("LLM loaded via fallback (env vars)")
            except Exception as e2:
                logger.error(f"Could not create fallback LLM: {e2}")
                raise RuntimeError(
                    f"No LLM available. IAF model service error: {e1}. "
                    f"Fallback error: {e2}"
                )

    def _create_fallback_llm(self):
        """Create a LangChain chat model from environment variables."""
        import os

        # Try Azure OpenAI first
        azure_key = os.environ.get("AZURE_OPENAI_API_KEY")
        azure_endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
        azure_deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT_NAME")
        azure_version = os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-15-preview")

        if azure_key and azure_endpoint and azure_deployment:
            # Use TokenLoggingAzureChatOpenAI for LLM request tracking
            from src.models.guardrail_aware_llm import TokenLoggingAzureChatOpenAI
            return TokenLoggingAzureChatOpenAI(
                azure_endpoint=azure_endpoint,
                azure_deployment=azure_deployment,
                api_version=azure_version,
                api_key=azure_key,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

        # Try OpenAI
        openai_key = os.environ.get("OPENAI_API_KEY")
        if openai_key:
            # Use GuardrailChatOpenAI for LLM request tracking
            from src.models.guardrail_aware_llm import GuardrailChatOpenAI
            return GuardrailChatOpenAI(
                api_key=openai_key,
                model=self.config.model_name or "gpt-4o",
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )

        raise RuntimeError("No LLM credentials found in environment variables")

    async def generate_code(
        self,
        goal: str,
        language: str = "python",
        context: str = "",
    ) -> str:
        """
        Generate executable code for a goal.

        Args:
            goal: Natural-language description of what the code should do.
            language: Target language (python, javascript, bash).
            context: Optional context (file listings, prior output, etc.).

        Returns:
            Generated source code string.

        Raises:
            RuntimeError: If LLM is unavailable or generation fails.
        """
        await self._ensure_llm()

        prompt = self._build_generation_prompt(goal, language, context)

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content=self.config.system_prompt),
                HumanMessage(content=prompt),
            ]

            response = await self._llm.ainvoke(messages)
            raw = response.content if hasattr(response, "content") else str(response)
            code = self._extract_code(raw, language)
            logger.info(f"Generated {len(code)} chars of {language} code for goal: {goal[:80]}")
            return code

        except Exception as exc:
            logger.error(f"Code generation failed: {exc}")
            raise RuntimeError(f"Code generation failed: {exc}")

    async def fix_code(
        self,
        code: str,
        error: str,
        goal: str,
        language: str = "python",
    ) -> str:
        """
        Ask the LLM to fix broken code given the error message.

        Args:
            code: The code that failed.
            error: The error message / stderr.
            goal: Original goal for context.
            language: Programming language.

        Returns:
            Fixed source code string.
        """
        await self._ensure_llm()

        prompt = self._build_fix_prompt(code, error, goal, language)

        try:
            from langchain_core.messages import HumanMessage, SystemMessage

            messages = [
                SystemMessage(content=self.config.system_prompt),
                HumanMessage(content=prompt),
            ]

            response = await self._llm.ainvoke(messages)
            raw = response.content if hasattr(response, "content") else str(response)
            fixed = self._extract_code(raw, language)
            logger.info(f"Fixed code ({len(fixed)} chars) for error: {error[:80]}")
            return fixed

        except Exception as exc:
            logger.error(f"Code fix failed: {exc}")
            raise RuntimeError(f"Code fix failed: {exc}")

    async def is_available(self) -> bool:
        """Check if the LLM is reachable. Returns False quickly if not configured."""
        if self._llm is not None:
            return True
        # Don't attempt to load during health checks — just report availability
        if self._initialized:
            return self._llm is not None
        return False

    # -------------------------------------------------------------------
    # Prompt builders
    # -------------------------------------------------------------------

    @staticmethod
    def _build_generation_prompt(goal: str, language: str, context: str) -> str:
        parts = [
            f"Write {language} code to accomplish the following goal:",
            f"\nGOAL: {goal}",
        ]
        if context:
            parts.append(f"\nCONTEXT:\n{context}")

        parts.append(
            f"\nIMPORTANT RULES:\n"
            f"- Return ONLY raw executable {language} code.\n"
            f"- No markdown fences (no ```). No explanations. No comments except where essential.\n"
            f"- The code must be self-contained with all imports.\n"
            f"- Print results to stdout.\n"
            f"- If creating files, use relative paths in the current directory.\n"
            f"- If creating charts/visualizations, save to files (e.g., output.png), do not show interactively.\n"
            f"- Handle errors gracefully."
        )
        return "\n".join(parts)

    @staticmethod
    def _build_fix_prompt(code: str, error: str, goal: str, language: str) -> str:
        return (
            f"The following {language} code failed. Fix it and return ONLY the corrected code.\n"
            f"No markdown fences, no explanations.\n\n"
            f"ORIGINAL GOAL: {goal}\n\n"
            f"FAILED CODE:\n{code}\n\n"
            f"ERROR:\n{error}\n\n"
            f"FIXED CODE:"
        )

    # -------------------------------------------------------------------
    # Code extraction from LLM response
    # -------------------------------------------------------------------

    @staticmethod
    def _extract_code(raw: str, language: str) -> str:
        """
        Extract clean code from LLM output.
        Strips thinking tags, markdown fences, and preamble text.
        """
        text = raw

        # Remove thinking/reasoning/scratchpad tags
        for tag in ["think", "reasoning", "scratchpad", "thought"]:
            text = re.sub(rf"<{tag}>.*?</{tag}>", "", text, flags=re.DOTALL)

        # Try to extract from markdown code fences
        lang_aliases = {
            "python": ["python", "py", "python3"],
            "javascript": ["javascript", "js", "node"],
            "bash": ["bash", "sh", "shell"],
        }
        aliases = lang_aliases.get(language, [language])
        for alias in aliases:
            pattern = rf"```{alias}\s*\n(.*?)```"
            m = re.search(pattern, text, re.DOTALL)
            if m:
                return m.group(1).strip()

        # Try generic code fence
        m = re.search(r"```\s*\n(.*?)```", text, re.DOTALL)
        if m:
            return m.group(1).strip()

        # No fences — return the raw text, stripped of leading prose
        # Remove any leading lines that look like explanations
        lines = text.strip().split("\n")
        code_lines = []
        started = False
        for line in lines:
            if not started:
                # Skip lines that look like prose (no code-like tokens)
                stripped = line.strip()
                if (
                    stripped.startswith(("import ", "from ", "def ", "class ",
                                        "#!", "const ", "let ", "var ",
                                        "function ", "async ", "#!/"))
                    or stripped == ""
                    or "=" in stripped
                    or stripped.startswith(("#", "//", "print(", "console."))
                ):
                    started = True
                    code_lines.append(line)
                # else skip this prose line
            else:
                code_lines.append(line)

        result = "\n".join(code_lines).strip()
        return result if result else text.strip()
