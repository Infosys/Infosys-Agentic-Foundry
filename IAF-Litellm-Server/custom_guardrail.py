"""
Custom Guardrails for LiteLLM Proxy Server

This module implements custom guardrails including:
- RAI Content Moderation (pre-call and post-call) - jailbreak, toxicity, profanity, restricted topics
- PII Detection, Blocking, Encryption/Decryption (via PiiProtectionGuardrail)
- Token usage tracking and cost logging
- Comprehensive logging and audit trails
- Proxy support for enterprise environments
"""

from typing import Any, Dict, List, Literal, Optional, Union
import os
import litellm
from litellm._logging import verbose_proxy_logger
from litellm.caching import DualCache
from litellm.integrations.custom_guardrail import CustomGuardrail
from litellm.proxy._types import UserAPIKeyAuth
from litellm import ContentPolicyViolationError

import requests
from fastapi import HTTPException
from dotenv import load_dotenv

import json
from pathlib import Path
from datetime import datetime
import asyncio

from moderation_db_service import get_moderation_db_service
from constants import env_bool

load_dotenv()

# print("[GUARDRAIL] custom_guardrail.py module loaded successfully!")

class RaiCustomGuardrail(CustomGuardrail):
    """
    Custom Guardrail for RAI (Responsible AI) Content Moderation
    
    Features:
    - Content moderation (jailbreak, toxicity, profanity, restricted topics)
    - Detailed logging and audit trails
    - Token usage tracking
    - Proxy support for enterprise environments
    """
    
    def __init__(self, **kwargs):
        """
        Initialize RAI Custom Guardrail
        
        Args:
            **kwargs: Optional parameters for guardrail configuration
        """
        self.optional_params = kwargs
        super().__init__(**kwargs)
        
        self.proxies = None
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        
        if http_proxy or https_proxy:
            self.proxies = {}
            if http_proxy:
                self.proxies['http'] = http_proxy
            if https_proxy:
                self.proxies['https'] = https_proxy
            verbose_proxy_logger.debug(f"Using proxies: {self.proxies}")
        
        
        self.rai_api_url = os.getenv("RAI_API_URL")
        
        verbose_proxy_logger.info(
            "RAI Guardrail initialized - pre=%s post=%s",
            env_bool("GUARDRAILS_PRE_CALL_ENABLED", False),
            env_bool("GUARDRAILS_POST_CALL_ENABLED", False),
        )
        
        self.db_service = get_moderation_db_service()
        try:
            asyncio.create_task(self.db_service.initialize())
            asyncio.create_task(self.db_service.ensure_table_exists())
            verbose_proxy_logger.info("Database service initialized for moderation logging")
        except Exception as e:
            verbose_proxy_logger.warning(f"Failed to initialize database service: {e}. Will fallback to file logging.")
            self.db_service = None
        
        self.token_logger = None

    def _create_moderation_payload(self, prompt_content: str, is_pre_call: bool = True) -> dict:
        """
        Create payload for RAI moderation API
        
        Args:
            prompt_content: Content to moderate
            is_pre_call: Whether this is a pre-call check
            
        Returns:
            dict: Moderation payload
        """
        moderation_checks = [
            # "PromptInjection",
            "JailBreak",
            "Toxicity",
            "Profanity",
            "RestrictTopic"
        ]
        print(".............1.........")
        print(json.dumps(prompt_content))
        return {
            "AccountName": os.getenv("RAI_ACCOUNT_NAME", "None"),
            "userid": "None",
            "PortfolioName": os.getenv("RAI_PORTFOLIO_NAME", "None"),
            "lotNumber": "1",
            "Prompt": json.dumps(prompt_content),
            "ModerationChecks": moderation_checks,
            "ModerationCheckThresholds": {
                "PromptinjectionThreshold": 0.7,
                "JailbreakThreshold": 0.7,
                "RefusalThreshold": 0.7,
                "ToxicityThresholds": {
                    "ToxicityThreshold": 0.6,
                    "SevereToxicityThreshold": 0.6,
                    "ObsceneThreshold": 0.6,
                    "ThreatThreshold": 0.6,
                    "InsultThreshold": 0.6,
                    "IdentityAttackThreshold": 0.6,
                    "SexualExplicitThreshold": 0.6
                },
                "ProfanityCountThreshold": 1,
                "RestrictedtopicDetails": {
                    "RestrictedtopicThreshold": 0.7,
                    "Restrictedtopics": [
                        "Terrorism", "Explosives", "Nudity", "Cruelty", "Cheating",
                        "Fraud", "Crime", "Hacking", "Immoral", "Unethical",
                        "Illegal", "Robbery", "Forgery", "Misinformation"
                    ]
                },
                "CustomTheme": {
                    "Themename": "string",
                    "Themethresold": 0.6,
                    "ThemeTexts": ["Text2"]
                }
            }
        }

    async def _log_moderation_result(self, content: str, moderation_result: dict, check_type: str = "pre-call"):
        """
        Log moderation result to PostgreSQL database
        
        Args:
            content: Moderated content
            moderation_result: Result from moderation API
            check_type: Type of check (pre-call or post-call)
        """
        try:
            if self.db_service:
                record_id = await self.db_service.save_moderation_log(
                    check_type=check_type,
                    content=content,
                    moderation_result=moderation_result
                )
                if record_id:
                    verbose_proxy_logger.debug(f"Moderation log saved to database with ID: {record_id}")
                else:
                    verbose_proxy_logger.warning("Failed to save moderation log to database")
            else:
                log_file = self.output_dir / "rai_moderation_results.jsonl"
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat() + "Z",
                    "check_type": check_type,
                    "content": content,
                    "moderation_result": moderation_result
                }
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False) + "\n")
                verbose_proxy_logger.debug("Moderation log saved to file (database unavailable)")
        except Exception as e:
            verbose_proxy_logger.error(f"Error logging moderation result: {e}")

    def _parse_failed_checks(self, moderation_results: dict) -> List[str]:
        """
        Parse failed moderation checks from results
        
        Args:
            moderation_results: Results from moderation API
            
        Returns:
            list: List of failed check descriptions
        """
        failed_checks = []
        mod_str = str(moderation_results)
        
        if 'JailBreak' in mod_str:
            failed_checks.append("potential jailbreak attempt")
        if 'Toxicity' in mod_str:
            failed_checks.append("toxic content")
        if 'Profanity' in mod_str:
            failed_checks.append("profanity")
        if 'RestrictTopic' in mod_str:
            failed_checks.append("restricted topic")
        if 'PromptInjection' in mod_str:
            failed_checks.append("prompt injection")
        
        return failed_checks

    def _extract_user_content_for_moderation(self, content: str) -> str:
        """
        Generic extraction of user-provided content from LLM prompts.
        
        This extracts ONLY user-provided content (code, descriptions, queries)
        and excludes system instructions that may contain false-positive keywords.
        
        Extraction patterns (in priority order):
        1. "User Query:" - chat inference user input
        2. "# Tool Code" / "# Tool Description" - tool onboarding
        3. "### Python Function" - tool validation
        4. Code blocks between ``` markers
        
        Returns:
            str: Extracted user content to scan, or empty string if none found
        """
        import re
        
        extracted_parts = []
        
        # Pattern 1: Extract content after "User Query:" marker
        user_query_marker = "User Query:"
        if user_query_marker in content:
            marker_pos = content.rfind(user_query_marker)
            user_query = content[marker_pos + len(user_query_marker):].strip()
            if user_query:
                extracted_parts.append(user_query)
                verbose_proxy_logger.debug(f"Extracted User Query: {len(user_query)} chars")
        
        # Pattern 2: Extract content after "# Tool Code" until next section
        tool_code_match = re.search(r'#\s*Tool\s*Code\s*\n(.*?)(?=\n\*\*|$)', content, re.DOTALL | re.IGNORECASE)
        if tool_code_match:
            tool_code = tool_code_match.group(1).strip()
            if tool_code:
                extracted_parts.append(tool_code)
                verbose_proxy_logger.debug(f"Extracted Tool Code: {len(tool_code)} chars")
        
        # Pattern 3: Extract content after "# Tool Description" until next section
        tool_desc_match = re.search(r'#\s*Tool\s*Description\s*\n(.*?)(?=\n#|\n\*\*|$)', content, re.DOTALL | re.IGNORECASE)
        if tool_desc_match:
            tool_desc = tool_desc_match.group(1).strip()
            if tool_desc:
                extracted_parts.append(tool_desc)
                verbose_proxy_logger.debug(f"Extracted Tool Description: {len(tool_desc)} chars")
        
        # Pattern 4: Extract content after "### Python Function" until "## Instructions"
        python_func_match = re.search(r'###\s*Python\s*Function\s*\n(.*?)(?=\n##\s*Instructions|$)', content, re.DOTALL | re.IGNORECASE)
        if python_func_match:
            python_func = python_func_match.group(1).strip()
            if python_func:
                extracted_parts.append(python_func)
                verbose_proxy_logger.debug(f"Extracted Python Function: {len(python_func)} chars")
        
        # Pattern 5: Extract code from code blocks (```python ... ``` or ``` ... ```)
        code_blocks = re.findall(r'```(?:python)?\s*\n(.*?)```', content, re.DOTALL)
        for code_block in code_blocks:
            code = code_block.strip()
            if code and code not in extracted_parts:  # Avoid duplicates
                extracted_parts.append(code)
                verbose_proxy_logger.debug(f"Extracted code block: {len(code)} chars")
        
        # Combine all extracted parts
        combined = "\n".join(extracted_parts)
        
        if combined:
            verbose_proxy_logger.info(f"Total extracted user content: {len(combined)} chars from {len(extracted_parts)} parts")
        
        return combined

    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: Literal[
            "acompletion", "completions", "text_completion", "embeddings",
            "image_generation", "moderation", "audio_transcription",
            "pass_through_endpoint", "rerank"
        ],
    ) -> Optional[Union[Exception, str, dict]]:
        """
        Pre-call hook for content moderation
        
        Validates input messages for:
        - Jailbreak attempts
        - Toxic content
        - Profanity
        - Restricted topics
        - Prompt injection
        
        Args:
            user_api_key_dict: User API key authentication
            cache: Dual cache instance
            data: Request data
            call_type: Type of LLM call
            
        Returns:
            Modified data or raises HTTPException if moderation fails
        """
        if not env_bool("GUARDRAILS_PRE_CALL_ENABLED", False):
            verbose_proxy_logger.debug("Pre-call RAI guardrail skipped (GUARDRAILS_PRE_CALL_ENABLED=false)")
            return data

        if not self.rai_api_url:
            verbose_proxy_logger.warning("RAI_API_URL not configured, skipping pre-call moderation")
            return data
            
        _messages = data.get("messages")
        verbose_proxy_logger.info("RAI pre-call hook executing")
        
        if _messages:
            # ALWAYS CALL GUARDRAILS - but extract only user-provided content to scan
            # This avoids false positives from system instructions that contain 
            # security-related keywords (e.g., "shutdown", "kill", "malicious")
            #
            # Generic extraction patterns for user content:
            # - "User Query:" followed by user's question
            # - "# Tool Code" / "### Python Function" followed by code
            # - "# Tool Description" followed by description
            # - Content between code blocks (```)
            
            messages_to_moderate = []
            for message in _messages:
                role = message.get("role", "").lower()
                if role in ["user", "human", "system"]:
                    content = message.get("content")
                    if content and isinstance(content, str):
                        # Extract user-provided content using generic patterns
                        user_content = self._extract_user_content_for_moderation(content)
                        
                        if user_content:
                            verbose_proxy_logger.debug(f"Extracted user content ({len(user_content)} chars) from {role} message")
                            messages_to_moderate.append({
                                "role": role,
                                "content": user_content,
                                "message": message
                            })
                        else:
                            verbose_proxy_logger.debug(f"No user content extracted from {role} message - skipping")
            
            # If no user content extracted, skip moderation
            if not messages_to_moderate:
                verbose_proxy_logger.debug("No user content to moderate after extraction")
                return data
            
            # Moderate each extracted user content
            for msg_data in messages_to_moderate:
                role = msg_data["role"]
                _content = msg_data["content"]
                
                headers = {
                    'accept': 'application/json',
                    'Content-Type': 'application/json'
                }
                
                prompt_data = self._create_moderation_payload(_content, is_pre_call=True)
                
                try:
                    response = requests.post(
                        self.rai_api_url, 
                        json=prompt_data, 
                        headers=headers, 
                        proxies=self.proxies, 
                        verify=False,
                        timeout=30
                    )
                    response.raise_for_status()
                    resp = response.json()
                    
                    verbose_proxy_logger.debug(f"RAI API Response for {role} message: {resp}")
                    modResults = resp.get('moderationResults', {})
                    
                    # Log moderation result to database
                    await self._log_moderation_result(_content, resp, check_type="pre-call")
                    
                    summary = modResults.get('summary', {})
                    status = summary.get('status', 'UNKNOWN')
                    
                    if status == "PASSED":
                        verbose_proxy_logger.info(f"{role.capitalize()} message passed moderation")
                    else:
                        verbose_proxy_logger.warning(f"{role.capitalize()} message failed moderation: {status}")
                        
                        failed_checks = self._parse_failed_checks(modResults)
                        violation_message = ", ".join(failed_checks) if failed_checks else "policy violation"
                        
                        # Raise ContentPolicyViolationError - configured to not retry/fallback in config.yaml
                        verbose_proxy_logger.info(f"Blocking {role} message due to policy violation: {violation_message}")
                        raise ContentPolicyViolationError(
                            message=f"The {role} message was flagged for: {violation_message}. Please review the content.",
                            model="guardrail",
                            llm_provider="rai_moderation",
                        )
                
                except ContentPolicyViolationError:
                    # Re-raise directly - config.yaml has ContentPolicyViolationErrorRetries: 0
                    raise
                
                except requests.exceptions.RequestException as e:
                    verbose_proxy_logger.error(f"Error calling RAI API in pre-call for {role} message: {e}")
                    raise HTTPException(
                        status_code=403,
                        detail={"error": f"Moderation Service Unavailable: {str(e)}"},
                    )
                
                except HTTPException:
                    raise
                
                except Exception as e:
                    verbose_proxy_logger.error(f"Unexpected error in pre-call hook for {role} message: {e}")
                    raise HTTPException(
                        status_code=403,
                        detail={"error": f"Unexpected error during moderation: {str(e)}"},
                    )
        
        return data

    async def async_post_call_success_hook(
        self,
        data: dict,
        user_api_key_dict: UserAPIKeyAuth,
        response,
    ):
        """
        Post-call hook for response moderation and PII decryption
        
        Args:
            data: Request data
            user_api_key_dict: User API key authentication
            response: LLM response
            
        Returns:
            Modified response or original response
        """
        
        verbose_proxy_logger.info("RAI post-call hook executing")
        
        if not env_bool("GUARDRAILS_POST_CALL_ENABLED", False):
            verbose_proxy_logger.debug("Post-call RAI guardrail skipped (GUARDRAILS_POST_CALL_ENABLED=false)")
            return response
        
        try:
            # Extract response content for moderation
            if hasattr(response, 'choices') and len(response.choices) > 0:
                choice = response.choices[0]
                if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                    response_content = choice.message.content
                    
                    # Moderate response content
                    headers = {
                        'accept': 'application/json',
                        'Content-Type': 'application/json'
                    }
                    
                    moderation_payload = self._create_moderation_payload(
                        response_content, 
                        is_pre_call=False
                    )
                    
                    mod_response = requests.post(
                        self.rai_api_url,
                        json=moderation_payload,
                        headers=headers,
                        proxies=self.proxies,
                        verify=False,
                        timeout=30
                    )
                    mod_response.raise_for_status()
                    mod_result = mod_response.json()
                    
                    # Log response moderation to database
                    await self._log_moderation_result(response_content, mod_result, check_type="post-call")
                    
                    modResults = mod_result.get('moderationResults', {})
                    summary = modResults.get('summary', {})
                    status = summary.get('status', 'UNKNOWN')
                    
                    if status != "PASSED":
                        verbose_proxy_logger.warning(f"Response failed moderation: {status}")
                        # Optionally handle failed response moderation
                        # For now, we'll just log it
        except Exception as e:
            verbose_proxy_logger.error(f"Error in post-call hook: {e}")
            # Don't fail the request if post-call moderation fails
        
        return response


class PiiProtectionGuardrail(CustomGuardrail):
    """
    Standalone PII Protection Guardrail
    
    Encrypts PII in requests and decrypts in responses
    """
    
    def __init__(self, **kwargs):
        """Initialize PII Protection Guardrail"""
        # print(f"[PII GUARDRAIL] Initializing PiiProtectionGuardrail with mode={kwargs.get('mode', 'unknown')}")
        self.optional_params = kwargs
        super().__init__(**kwargs)
        
        # PII API is internal - explicitly bypass corporate proxy
        # Setting empty dict forces requests to NOT use environment proxy vars
        self.proxies = {'http': None, 'https': None}
        
        self.encrypt_url = os.getenv(
            "PII_ENCRYPT_URL",
            "https://api-aicloud.ad.infosys.com/v1/privacy/text/encrpyt"
        )
        self.decrypt_url = os.getenv(
            "PII_DECRYPT_URL",
            "https://api-aicloud.ad.infosys.com/v1/privacy/text/decrpyt"
        )
        
        block_list_env = os.getenv("PII_ENTITIES_TO_BLOCK", "")
        if block_list_env:
            self.pii_entities_to_block = set(e.strip() for e in block_list_env.split(",") if e.strip())
        else:
            self.pii_entities_to_block = {"IN_PAN", "PAN_Number", "PASSPORT", "US_PASSPORT", "PHONE_NUMBER", "IP_ADDRESS", "EMAIL_ADDRESS", "US_SSN"}
        
        # print(f"[PII GUARDRAIL] Block list: {self.pii_entities_to_block}")
        verbose_proxy_logger.info(f"PiiProtectionGuardrail initialized (mode={kwargs.get('mode', 'unknown')})")
        verbose_proxy_logger.info(f"PII entities configured to BLOCK: {self.pii_entities_to_block}")
    
    def _build_replacement_map(self, original_text: str, encrypted_text: str, items: list) -> dict:
        """
        Build replacement map using position-based extraction.
        
        The API returns items with 'start' and 'end' positions in the ENCRYPTED text.
        We correlate these with the ORIGINAL text to extract original values.
        """
        if not items or original_text == encrypted_text:
            return {}
        
        # Sort items by start position (ascending order)
        sorted_items = sorted(items, key=lambda x: x.get('start', 0))
        
        replacement_map = {}
        cumulative_len_diff = 0  # Track difference between encrypted and original lengths
        
        for item in sorted_items:
            start_enc = item.get('start', 0)
            end_enc = item.get('end', 0)
            encrypted_token = item.get('text', '')
            
            if not encrypted_token:
                continue
            
            encrypted_token_len = end_enc - start_enc
            
            # Calculate position in original text (adjusted for previous token length differences)
            start_orig = start_enc - cumulative_len_diff
            
            # Get text AFTER the encrypted token to use as anchor
            anchor_len = min(30, len(encrypted_text) - end_enc)
            text_after_enc = encrypted_text[end_enc:end_enc + anchor_len] if anchor_len > 0 else ""
            
            original_value = None
            
            if text_after_enc:
                # Search for the anchor text in original, starting from start_orig
                for orig_len in range(1, min(100, len(original_text) - start_orig + 1)):
                    check_pos = start_orig + orig_len
                    if check_pos >= len(original_text):
                        break
                    if original_text[check_pos:check_pos + len(text_after_enc)] == text_after_enc:
                        original_value = original_text[start_orig:check_pos]
                        cumulative_len_diff += encrypted_token_len - orig_len
                        break
            else:
                # End of text - the original value is whatever remains from start_orig
                original_value = original_text[start_orig:]
                cumulative_len_diff += encrypted_token_len - len(original_value)
            
            if original_value:
                replacement_map[encrypted_token] = original_value
                print(f"[PII GUARDRAIL] Replacement map: '{encrypted_token[:25]}...' → '{original_value}'")
        
        return replacement_map
    
    def _encrypt_pii(self, text: str) -> tuple[str, list, dict, list, bool]:
        """
        Encrypt PII in text.
        Returns (encrypted_text, items, replacement_map, detected_entity_types, was_encrypted)
        replacement_map: {encrypted_token: original_value} for simple string replacement
        detected_entity_types: list of dicts with 'entity_type' and 'text' for each detected entity
        """
        payload = {
            "inputText": text,
            "nlp": "roberta",
            "redactionType": "string",
            "scoreThreshold": 0.4
        }
        
        headers = {'Content-Type': 'application/json'}
        
        # Retry logic for transient failures
        max_retries = 2
        last_error = None
        
        for attempt in range(max_retries + 1):
            try:
                response = requests.post(
                    self.encrypt_url,
                    json=payload,
                    headers=headers,
                    proxies=self.proxies,
                    verify=False,
                    timeout=30
                )
                response.raise_for_status()
                result = response.json()
                print(f"[PII GUARDRAIL] Raw API response keys: {result.keys()}")
                encrypted_text = result.get('text', text)
                items = result.get('items', [])
                print(f"[PII GUARDRAIL] Items count: {len(items)}")
                was_encrypted = encrypted_text != text
                
                # Build replacement map using position-based extraction
                replacement_map = self._build_replacement_map(text, encrypted_text, items)
                print(f"[PII GUARDRAIL] Built replacement map with {len(replacement_map)} entries")
                
                # Extract entity types from items for blocking logic
                detected_entity_types = []
                if items:
                    for item in items:
                        entity_type = item.get('entity_type', '') or item.get('type', '') or item.get('entityType', '')
                        encrypted_token = item.get('text', '')  # This is the encrypted value in the response
                        
                        if entity_type:
                            # Find the original value from replacement_map
                            original_value = replacement_map.get(encrypted_token, 'unknown')
                            detected_entity_types.append({
                                'entity_type': entity_type,
                                'text': original_value,
                                'encrypted': encrypted_token
                            })
                            print(f"[PII GUARDRAIL] Entity: {entity_type} | Original: '{original_value}' | Encrypted: '{encrypted_token[:25]}...'")
                
                if was_encrypted:
                    verbose_proxy_logger.info(f"PII encryption: {len(items)} entities found, types={[e['entity_type'] for e in detected_entity_types]}")
                    verbose_proxy_logger.info(f"PII replacement map built with {len(replacement_map)} entries")
                else:
                    verbose_proxy_logger.info(f"PII scan completed: no PII detected in {len(text)} chars")
                return encrypted_text, items, replacement_map, detected_entity_types, was_encrypted
            except Exception as e:
                last_error = e
                if attempt < max_retries:
                    verbose_proxy_logger.warning(f"PII encryption attempt {attempt + 1} failed: {e}, retrying...")
                    import time
                    time.sleep(0.5)
                    continue
                break
        
        verbose_proxy_logger.error(f"PII encryption failed after {max_retries + 1} attempts: {last_error}")
        raise last_error
    
    def _extract_user_content_for_pii_scan(self, content: str) -> tuple:
        """
        Generic extraction of user-provided content from LLM prompts.
        
        This extracts ONLY user-provided content (code, descriptions, queries)
        and excludes system instructions that may cause false positives.
        
        Returns:
            tuple: (extracted_content, content_type, marker_position)
                   marker_position is used for replacing encrypted content back into original
        """
        import re
        
        extracted_parts = []
        
        # Pattern 1: Extract content after "User Query:" marker (highest priority for chat)
        user_query_marker = "User Query:"
        if user_query_marker in content:
            marker_pos = content.rfind(user_query_marker)
            user_query = content[marker_pos + len(user_query_marker):].strip()
            if user_query:
                return user_query, "user_query", marker_pos
        
        # Pattern 2: Extract content after "# Tool Code" until next section
        tool_code_match = re.search(r'#\s*Tool\s*Code\s*\n(.*?)(?=\n\*\*|$)', content, re.DOTALL | re.IGNORECASE)
        if tool_code_match:
            tool_code = tool_code_match.group(1).strip()
            if tool_code:
                extracted_parts.append(("tool_code", tool_code))
        
        # Pattern 3: Extract content after "# Tool Description" until next section
        tool_desc_match = re.search(r'#\s*Tool\s*Description\s*\n(.*?)(?=\n#|\n\*\*|$)', content, re.DOTALL | re.IGNORECASE)
        if tool_desc_match:
            tool_desc = tool_desc_match.group(1).strip()
            if tool_desc:
                extracted_parts.append(("tool_description", tool_desc))
        
        # Pattern 4: Extract content after "### Python Function" until "## Instructions"
        python_func_match = re.search(r'###\s*Python\s*Function\s*\n(.*?)(?=\n##\s*Instructions|$)', content, re.DOTALL | re.IGNORECASE)
        if python_func_match:
            python_func = python_func_match.group(1).strip()
            if python_func:
                extracted_parts.append(("python_function", python_func))
        
        # Pattern 5: Extract code from code blocks (```python ... ``` or ``` ... ```)
        code_blocks = re.findall(r'```(?:python)?\s*\n(.*?)```', content, re.DOTALL)
        for code_block in code_blocks:
            code = code_block.strip()
            if code:
                extracted_parts.append(("code_block", code))
        
        # Combine all extracted parts for scanning
        if extracted_parts:
            combined = "\n".join([part[1] for part in extracted_parts])
            print(f"[PII GUARDRAIL] Extracted {len(extracted_parts)} parts: {[p[0] for p in extracted_parts]}")
            return combined, "combined", -1  # -1 means no single marker position
        
        return "", "none", -1
    
    def _decrypt_pii(self, text: str, items: list) -> str:
        """Decrypt PII in text"""
        if not items:
            return text
        
        payload = {"text": text, "items": items}
        headers = {'Content-Type': 'application/json'}
        
        verbose_proxy_logger.info(f"Decrypt API request - text length: {len(text)}, items count: {len(items)}")
        
        try:
            response = requests.post(
                self.decrypt_url,
                json=payload,
                headers=headers,
                proxies=self.proxies,
                verify=False,
                timeout=30
            )
            if response.status_code != 200:
                verbose_proxy_logger.error(f"PII decryption API error: status={response.status_code}, response={response.text[:500]}")
            response.raise_for_status()
            result = response.json()
            return result.get('decryptedText', text)
        except Exception as e:
            verbose_proxy_logger.error(f"PII decryption failed: {e}")
            return text
    
    async def async_pre_call_hook(
        self,
        user_api_key_dict: UserAPIKeyAuth,
        cache: DualCache,
        data: dict,
        call_type: Literal[
            "acompletion", "completions", "text_completion", "embeddings",
            "image_generation", "moderation", "audio_transcription",
            "pass_through_endpoint", "rerank"
        ],
    ) -> Optional[Union[Exception, str, dict]]:
        """Encrypt PII in request and block if blocked entities are detected"""
        print(f"[PII GUARDRAIL] async_pre_call_hook triggered for call_type={call_type}")
        messages = data.get("messages", [])
        print(f"[PII GUARDRAIL] Found {len(messages)} messages in request")

        if 'metadata' not in data or not isinstance(data.get('metadata'), dict):
            data['metadata'] = {}
        
        combined_replacement_map = {}
        all_blocked_entities = []
        
        # Find ONLY the LAST user/human message
        last_user_message = None
        all_roles = [m.get("role", "N/A") for m in messages]
        print(f"[PII GUARDRAIL] Message roles in request: {all_roles}")
        for message in reversed(messages):
            role = message.get("role", "").lower()
            if role in ("user", "human"):
                last_user_message = message
                break
        
        print(f"[PII GUARDRAIL] Last user message found: {last_user_message is not None}")
        
        if last_user_message:
            content = last_user_message.get("content")
            print(f"[PII GUARDRAIL] Full content length: {len(content) if isinstance(content, str) else 'N/A'}")
            
            if isinstance(content, str):
                # ALWAYS CALL GUARDRAILS - but extract only user-provided content to scan
                # This avoids false positives where code like "os.path" is detected as URL
                #
                # Generic extraction patterns:
                # - "User Query:" followed by user's question (chat inference)
                # - "# Tool Code" / "# Tool Description" (tool onboarding)
                # - "### Python Function" (tool validation)
                # - Code blocks (```)
                
                user_content_to_scan, content_type, marker_pos = self._extract_user_content_for_pii_scan(content)
                
                if not user_content_to_scan:
                    print(f"[PII GUARDRAIL] No user content extracted - skipping PII scan")
                    print(f"[PII GUARDRAIL] Pre-call hook completed (no user content to scan)")
                    return data
                
                print(f"[PII GUARDRAIL] Extracted user content ({content_type}): {len(user_content_to_scan)} chars")
                print(f"[PII GUARDRAIL] SCANNING: '{user_content_to_scan[:100]}...'")
                
                try:
                    encrypted, items, replacement_map, detected_entity_types, was_encrypted = self._encrypt_pii(user_content_to_scan)
                    print(f"[PII GUARDRAIL] Encryption result: was_encrypted={was_encrypted}, entities={detected_entity_types}")
                except Exception as e:
                    print(f"[PII GUARDRAIL] ERROR - PII API failed: {e}")
                    if len(user_content_to_scan) > 200000:
                        print(f"[PII GUARDRAIL] Skipping PII scan for large content after API failure")
                        verbose_proxy_logger.warning(f"PII API failed for large content ({len(user_content_to_scan)} chars), skipping: {e}")
                        return data
                    else:
                        verbose_proxy_logger.error(f"PII encryption service error - blocking request: {e}")
                        raise ContentPolicyViolationError(
                            message="Unable to verify content safety - PII protection service unavailable. Please try again later.",
                            model="guardrail",
                            llm_provider="pii_protection",
                        )
                
                if detected_entity_types:
                    for entity in detected_entity_types:
                        entity_type = entity.get('entity_type', '')
                        print(f"[PII GUARDRAIL] Detected entity: {entity_type} - checking if blocked...")
                        if entity_type in self.pii_entities_to_block:
                            all_blocked_entities.append(entity)
                            print(f"[PII GUARDRAIL] *** BLOCKED ENTITY: {entity_type} ***")
                            verbose_proxy_logger.warning(
                                f"BLOCKED PII entity detected: type={entity_type}, value='{entity.get('text', '')}'"
                            )
                        else:
                            print(f"[PII GUARDRAIL] Entity {entity_type} NOT in block list - will be ENCRYPTED")
                
                if was_encrypted:
                    # For User Query content_type, replace the content in the message
                    if content_type == "user_query" and marker_pos >= 0:
                        user_query_marker = "User Query:"
                        new_content = content[:marker_pos + len(user_query_marker)] + "\n" + encrypted
                        last_user_message["content"] = new_content
                        print(f"[PII GUARDRAIL] User query encrypted - replaced in message")
                    else:
                        # For other content types, store replacement map for response decryption
                        print(f"[PII GUARDRAIL] {content_type} - stored {len(replacement_map)} replacements for decryption")
                    combined_replacement_map.update(replacement_map)
                else:
                    print(f"[PII GUARDRAIL] No encryption applied - content unchanged")
        else:
            print(f"[PII GUARDRAIL] No user message found in request - skipping PII scan")
        
        # If any blocked entities were found, reject the request
        if all_blocked_entities:
            blocked_types = list(set(e['entity_type'] for e in all_blocked_entities))
            verbose_proxy_logger.warning(
                f"Request BLOCKED - {len(all_blocked_entities)} blocked PII entities detected: {blocked_types}"
            )
            raise ContentPolicyViolationError(
                message=f"Request blocked: detected sensitive PII entities that are not allowed: {', '.join(blocked_types)}. Please remove this information and try again.",
                model="guardrail",
                llm_provider="pii_protection",
            )
        
        if combined_replacement_map:
            data['metadata']['_pii_replacement_map'] = combined_replacement_map
            verbose_proxy_logger.info(f"Stored {len(combined_replacement_map)} PII replacement mappings for decryption")
        
        print(f"[PII GUARDRAIL] Pre-call hook completed successfully")
        return data
    
    async def async_post_call_success_hook(
        self,
        data: dict,
        user_api_key_dict: UserAPIKeyAuth,
        response,
    ):
        """Decrypt PII in response by replacing encrypted tokens with original values"""
        print(f"[PII GUARDRAIL] POST-CALL hook triggered")
        metadata = data.get('metadata', {})
        replacement_map = metadata.pop('_pii_replacement_map', {}) if isinstance(metadata, dict) else {}
        
        print(f"[PII GUARDRAIL] Replacement map entries: {len(replacement_map)}")
        if replacement_map:
            for enc, orig in replacement_map.items():
                print(f"[PII GUARDRAIL] Map: '{enc[:30]}...' → '{orig}'")
        
        if replacement_map and hasattr(response, 'choices'):
            for choice in response.choices:
                if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                    response_text = choice.message.content
                    if not response_text:
                        continue
                    
                    print(f"[PII GUARDRAIL] Response text (first 200 chars): {response_text[:200]}...")
                    decrypted_text = response_text
                    replacements_made = 0
                    for encrypted_token, original_value in replacement_map.items():
                        if encrypted_token in decrypted_text:
                            print(f"[PII GUARDRAIL] Found token to replace: '{encrypted_token[:30]}...'")
                            decrypted_text = decrypted_text.replace(encrypted_token, original_value)
                            replacements_made += 1
                    
                    choice.message.content = decrypted_text
                    
                    if replacements_made > 0:
                        print(f"[PII GUARDRAIL] Decrypted {replacements_made} tokens in response")
                        verbose_proxy_logger.info(f"PII decryption: {replacements_made} replacements made in response")
                    else:
                        print(f"[PII GUARDRAIL] No tokens found to decrypt in response")
        else:
            print(f"[PII GUARDRAIL] No replacement map or no choices in response")
        
        return response