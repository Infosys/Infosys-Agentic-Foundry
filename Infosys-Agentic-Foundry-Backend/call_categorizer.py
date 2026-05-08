# """
# Automatic LLM Call Categorizer

# This module inspects the call stack to automatically categorize LLM calls
# without needing manual tracking code everywhere.

# It works by examining:
# 1. The filename where the LLM call originates
# 2. The function name making the call
# 3. Keywords in the call stack

# This enables 100% automatic coverage!
# """

# import inspect
# import re
# from typing import Optional, Tuple, Dict, Any
# from pathlib import Path

# try:
#     from telemetry_wrapper import logger as log
# except ImportError:
#     import logging
#     log = logging.getLogger(__name__)


# class CallCategorizer:
#     """
#     Automatically categorizes LLM calls based on call stack inspection
#     """
    
#     # Category detection rules (file path patterns)
#     FILE_PATTERNS = {
#         'agent_inference': [
#             'react_agent_inference',
#             'meta_agent_inference',
#             'planner_executor_agent_inference',
#             'planner_executor_critic_agent_inference',
#             'hybrid_agent_inference',
#             'planner_meta_agent_inference',
#             'react_critic_agent_inference',
#             'base_agent_inference',
#             'python_based_agent_inference',
#         ],
#         'tool_operation': [
#             'tool_validation',
#             'tool_code_processor',
#             'tool_export_import',
#             'tool_code_dependency_analyzer',
#             'tool_endpoints',
#         ],
#         'evaluation': [
#             'groundtruth',
#             'evaluation',
#             'core_evaluation_service',
#         ],
#         'prompt_generation': [
#             'prompt_generator',
#             'prompt_builder',
#             'prompt_factory',
#         ],
#         'file_analysis': [
#             'file_analyzer',
#             'document_processor',
#         ],
#         'rag_query': [
#             'knowledgebase',
#             'vector_store',
#             'rag_',
#         ],
#         'guardrail': [
#             'guardrail',
#             'moderation',
#             'safety',
#         ],
#         'conversation': [
#             'conversation',
#             'chat_endpoints',
#             'session',
#         ],
#     }
    
#     # Function name patterns
#     FUNCTION_PATTERNS = {
#         'agent_inference': [
#             'agent_',
#             '_agent',
#             'run_react',
#             'run_meta',
#             'run_planner',
#             'run_hybrid',
#             'agent_executor',
#             'create_agent',
#         ],
#         'tool_operation': [
#             'validate_tool',
#             'tool_validation',
#             'auto_fix_tool',
#             'check_tool',
#             'verify_tool',
#         ],
#         'evaluation': [
#             'evaluate',
#             'ground_truth',
#             'quality_check',
#             'assess',
#             'grade',
#             'score',
#         ],
#         'prompt_generation': [
#             'generate_prompt',
#             'create_prompt',
#             'build_prompt',
#             'prompt_gen',
#         ],
#         'file_analysis': [
#             'analyze_file',
#             'process_file',
#             'parse_document',
#             'analyze_document',
#         ],
#         'rag_query': [
#             'query_knowledgebase',
#             'rag_query',
#             'retrieve_',
#             'search_documents',
#         ],
#     }
    
#     # Agent type detection
#     AGENT_TYPE_PATTERNS = {
#         'react': ['react'],
#         'meta': ['meta'],
#         'planner_executor': ['planner_executor', 'planner-executor'],
#         'planner_executor_critic': ['planner_executor_critic', 'critic'],
#         'hybrid': ['hybrid'],
#     }
    
#     # Agent component detection
#     COMPONENT_PATTERNS = {
#         'planner': ['planner', '_plan'],
#         'executor': ['executor', '_execute'],
#         'critic': ['critic', '_critique'],
#         'replanner': ['replanner', '_replan'],
#     }
    
#     # Tool operation detection
#     TOOL_OPERATION_PATTERNS = {
#         'parameter_validation': ['parameter', 'param', 'validate_parameters'],
#         'execution_validation': ['execution', 'execute', 'run_validation'],
#         'json_validation': ['json', 'schema'],
#         'auto_fix': ['auto_fix', 'repair', 'fix'],
#     }
    
#     # Evaluation type detection
#     EVALUATION_TYPE_PATTERNS = {
#         'ground_truth': ['ground_truth', 'groundtruth'],
#         'response_quality': ['quality', 'response_eval', 'assess_response'],
#         'metric_calculation': ['metric', 'calculate', 'score'],
#         'preference_analysis': ['preference', 'feedback'],
#     }
    
#     @classmethod
#     def categorize_call(cls) -> Dict[str, Optional[str]]:
#         """
#         Automatically categorize an LLM call based on call stack
        
#         Returns:
#             dict with keys: call_category, call_sub_category, agent_type, 
#                            agent_component, tool_operation, evaluation_type
#         """
#         # Get call stack
#         stack = inspect.stack()
        
#         # Initialize result
#         result = {
#             'call_category': 'other',
#             'call_sub_category': None,
#             'call_operation': None,
#             'agent_type': None,
#             'agent_component': None,
#             'tool_operation': None,
#             'evaluation_type': None,
#             'tool_id': None,
#             'tool_name': None,
#         }
        
#         # Collect info from stack
#         filenames = []
#         function_names = []
        
#         # Check up to 30 frames to find the original caller (tool_validation.py, agent_inference.py, etc.)
#         # This is needed because async calls create deep stacks
#         for frame_info in stack[1:30]:
#             filename = frame_info.filename
#             function_name = frame_info.function
            
#             filenames.append(filename.lower())
#             function_names.append(function_name.lower())
        
#         # Convert to search strings
#         filepath_str = ' '.join(filenames)
#         funcname_str = ' '.join(function_names)
#         combined_str = filepath_str + ' ' + funcname_str
        
#         # 1. Detect main category
#         result['call_category'] = cls._detect_category(filepath_str, funcname_str)
        
#         # 2. Detect sub-category based on category
#         if result['call_category'] == 'agent_inference':
#             result['agent_type'] = cls._detect_agent_type(combined_str)
#             result['agent_component'] = cls._detect_component(combined_str)
            
#             # Build sub_category
#             parts = []
#             if result['agent_type']:
#                 parts.append(result['agent_type'])
#             if result['agent_component']:
#                 parts.append(result['agent_component'])
#             else:
#                 # Check if streaming
#                 if 'astream' in funcname_str or 'stream' in funcname_str:
#                     parts.append('stream')
#                 else:
#                     parts.append('invoke')
            
#             result['call_sub_category'] = '_'.join(parts) if parts else 'agent_general'
#             result['call_operation'] = 'chat_inference'
            
#         elif result['call_category'] == 'tool_operation':
#             result['tool_operation'] = cls._detect_tool_operation(combined_str)
#             result['call_sub_category'] = f"tool_{result['tool_operation']}" if result['tool_operation'] else 'tool_general'
#             result['call_operation'] = result['tool_operation'] or 'tool_operation'
            
#         elif result['call_category'] == 'evaluation':
#             result['evaluation_type'] = cls._detect_evaluation_type(combined_str)
#             result['call_sub_category'] = f"eval_{result['evaluation_type']}" if result['evaluation_type'] else 'eval_general'
#             result['call_operation'] = 'evaluation'
            
#         elif result['call_category'] == 'prompt_generation':
#             result['call_sub_category'] = 'prompt_generation'
#             result['call_operation'] = 'generate_prompt'
            
#         elif result['call_category'] == 'file_analysis':
#             result['call_sub_category'] = 'file_analysis'
#             result['call_operation'] = 'analyze_file'
            
#         elif result['call_category'] == 'rag_query':
#             result['call_sub_category'] = 'rag_query'
#             result['call_operation'] = 'knowledge_retrieval'
            
#         elif result['call_category'] == 'guardrail':
#             result['call_sub_category'] = 'guardrail_check'
#             result['call_operation'] = 'content_moderation'
            
#         elif result['call_category'] == 'conversation':
#             result['call_sub_category'] = 'conversation_management'
#             result['call_operation'] = 'conversation'
        
#         log.debug(f"🔍 Auto-categorized call: {result}")
#         return result
    
#     @classmethod
#     def _detect_category(cls, filepath_str: str, funcname_str: str) -> str:
#         """Detect main category from file path and function names"""
#         combined = filepath_str + ' ' + funcname_str
        
#         log.info(f"🔍 [Categorizer] filepath_str: {filepath_str[:400] if len(filepath_str) > 400 else filepath_str}")
#         log.info(f"🔍 [Categorizer] funcname_str: {funcname_str[:400] if len(funcname_str) > 400 else funcname_str}")
        
#         # PRIORITY 1: Check for specific operation types FIRST (tool, agent, evaluation, etc.)
#         # These take precedence over infrastructure (guardrail_aware_llm.py file)
#         for category, patterns in cls.FILE_PATTERNS.items():
#             if category == 'guardrail':
#                 continue  # Handle guardrail LAST (lowest priority)
#             for pattern in patterns:
#                 if pattern.lower() in combined:
#                     log.info(f"🔍 Matched category '{category}' via FILE_PATTERNS (pattern: '{pattern}')")
#                     return category
        
#         # PRIORITY 2: Check function name patterns for specific operations
#         for category, patterns in cls.FUNCTION_PATTERNS.items():
#             if any(pattern.lower() in funcname_str for pattern in patterns):
#                 log.info(f"🔍 Matched category '{category}' via FUNCTION_PATTERNS (priority match)")
#                 return category
        
#         # PRIORITY 3 (LOWEST): Only categorize as guardrail if:
#         # - guardrail_aware_llm.py is in path AND
#         # - NO other specific operation was detected above AND
#         # - There's evidence of actual moderation/safety operations
#         if 'guardrail_aware_llm' in filepath_str:
#             has_guardrail_evidence = any([
#                 'moderation' in funcname_str,
#                 'safety' in funcname_str,
#                 'content_filter' in funcname_str,
#             ])
#             log.info(f"🔍 Guardrail check (fallback): evidence={has_guardrail_evidence}")
#             if has_guardrail_evidence:
#                 log.info(f"🔍 Categorized as guardrail (no specific operation detected)")
#                 return 'guardrail'
        
#         # If nothing matched, default to 'other'
#         log.info(f"🔍 No category match - defaulting to 'other'")
#         log.info(f"🔍 [Categorizer] DEBUG: Checked {len(cls.FILE_PATTERNS)} file patterns and {len(cls.FUNCTION_PATTERNS)} function patterns")
#         return 'other'
    
#     @classmethod
#     def _detect_agent_type(cls, combined_str: str) -> Optional[str]:
#         """Detect agent type"""
#         for agent_type, patterns in cls.AGENT_TYPE_PATTERNS.items():
#             if any(pattern in combined_str for pattern in patterns):
#                 return agent_type
#         return None
    
#     @classmethod
#     def _detect_component(cls, combined_str: str) -> Optional[str]:
#         """Detect agent component"""
#         for component, patterns in cls.COMPONENT_PATTERNS.items():
#             if any(pattern in combined_str for pattern in patterns):
#                 return component
#         return None
    
#     @classmethod
#     def _detect_tool_operation(cls, combined_str: str) -> Optional[str]:
#         """Detect tool operation type"""
#         for operation, patterns in cls.TOOL_OPERATION_PATTERNS.items():
#             if any(pattern in combined_str for pattern in patterns):
#                 return operation
#         return None
    
#     @classmethod
#     def _detect_evaluation_type(cls, combined_str: str) -> Optional[str]:
#         """Detect evaluation type"""
#         for eval_type, patterns in cls.EVALUATION_TYPE_PATTERNS.items():
#             if any(pattern in combined_str for pattern in patterns):
#                 return eval_type
#         return None


# # Convenience function for use in wrappers
# def auto_categorize_llm_call() -> Dict[str, Optional[str]]:
#     """
#     Automatically categorize the current LLM call
    
#     Returns:
#         Dictionary with categorization info
#     """
#     return CallCategorizer.categorize_call()


# __all__ = ['CallCategorizer', 'auto_categorize_llm_call']

"""
Automatic LLM Call Categorizer

This module inspects the call stack to automatically categorize LLM calls
without needing manual tracking code everywhere.

It works by examining:
1. The filename where the LLM call originates
2. The function name making the call
3. Keywords in the call stack

This enables 100% automatic coverage!
"""

import inspect
import re
from typing import Optional, Tuple, Dict, Any
from pathlib import Path

try:
    from telemetry_wrapper import logger as log
except ImportError:
    import logging
    log = logging.getLogger(__name__)


class CallCategorizer:
    """
    Automatically categorizes LLM calls based on call stack inspection
    """
    
    # Category detection rules (file path patterns)
    FILE_PATTERNS = {
        'agent_inference': [
            'react_agent_inference',
            'meta_agent_inference',
            'planner_executor_agent_inference',
            'planner_executor_critic_agent_inference',
            'hybrid_agent_inference',
            'planner_meta_agent_inference',
            'react_critic_agent_inference',
            'base_agent_inference',
            'python_based_agent_inference',
            'centralized_agent_inference',  # Main inference entry point
        ],
        'tool_operation': [
            'tool_validation',
            'tool_code_processor',
            'tool_export_import',
            'tool_code_dependency_analyzer',
            'tool_endpoints',
        ],
        'evaluation': [
            'groundtruth',
            'evaluation',
            'core_evaluation_service',
        ],
        'prompt_generation': [
            'prompt_generator',
            'prompt_builder',
            'prompt_factory',
        ],
        'file_analysis': [
            'file_analyzer',
            'document_processor',
        ],
        'rag_query': [
            'knowledgebase',
            'vector_store',
            'rag_',
        ],
        'guardrail': [
            'guardrail',
            'moderation',
            'safety',
        ],
        'conversation': [
            'conversation',
            'chat_endpoints',
            'session',
        ],
    }
    
    # Function name patterns
    FUNCTION_PATTERNS = {
        'agent_inference': [
            'agent_',
            '_agent',
            'run_react',
            'run_meta',
            'run_planner',
            'run_hybrid',
            'agent_executor',
            'create_agent',
        ],
        'tool_operation': [
            'validate_tool',
            'tool_validation',
            'auto_fix_tool',
            'check_tool',
            'verify_tool',
        ],
        'evaluation': [
            'evaluate',
            'ground_truth',
            'quality_check',
            'assess',
            'grade',
            'score',
        ],
        'prompt_generation': [
            'generate_prompt',
            'create_prompt',
            'build_prompt',
            'prompt_gen',
        ],
        'file_analysis': [
            'analyze_file',
            'process_file',
            'parse_document',
            'analyze_document',
        ],
        'rag_query': [
            'query_knowledgebase',
            'rag_query',
            'retrieve_',
            'search_documents',
        ],
    }
    
    # Agent type detection (order matters: more specific patterns first)
    AGENT_TYPE_PATTERNS = {
        'planner_executor_critic': ['planner_executor_critic', 'multi_agent'],
        'planner_executor': ['planner_executor', 'planner-executor'],
        'planner_meta': ['planner_meta'],
        'react_critic': ['react_critic'],
        'react': ['react'],
        'meta': ['meta'],
        'hybrid': ['hybrid'],
    }
    
    # Agent component detection
    COMPONENT_PATTERNS = {
        'planner': ['planner', '_plan'],
        'executor': ['executor', '_execute'],
        'critic': ['critic', '_critique'],
        'replanner': ['replanner', '_replan'],
    }
    
    # Tool operation detection
    TOOL_OPERATION_PATTERNS = {
        'parameter_validation': ['parameter', 'param', 'validate_parameters'],
        'execution_validation': ['execution', 'execute', 'run_validation'],
        'json_validation': ['json', 'schema'],
        'auto_fix': ['auto_fix', 'repair', 'fix'],
    }
    
    # Evaluation type detection
    EVALUATION_TYPE_PATTERNS = {
        'ground_truth': ['ground_truth', 'groundtruth'],
        'response_quality': ['quality', 'response_eval', 'assess_response'],
        'metric_calculation': ['metric', 'calculate', 'score'],
        'preference_analysis': ['preference', 'feedback'],
    }
    
    @classmethod
    def categorize_call(cls) -> Dict[str, Optional[str]]:
        """
        Automatically categorize an LLM call based on call stack
        
        Returns:
            dict with keys: call_category, call_sub_category, agent_type, 
                           agent_component, tool_operation, evaluation_type
        """
        # Get call stack
        stack = inspect.stack()
        
        # Initialize result
        result = {
            'call_category': 'other',
            'call_sub_category': None,
            'call_operation': None,
            'agent_type': None,
            'agent_component': None,
            'tool_operation': None,
            'evaluation_type': None,
            'tool_id': None,
            'tool_name': None,
        }
        
        # Collect info from stack
        filenames = []
        function_names = []
        
        # Check up to 50 frames to find the original caller (tool_validation.py, agent_inference.py, etc.)
        # This is needed because async calls (LangChain/LangGraph) create deep stacks
        for frame_info in stack[1:50]:
            filename = frame_info.filename
            function_name = frame_info.function
            
            filenames.append(filename.lower())
            function_names.append(function_name.lower())
        
        # Convert to search strings
        filepath_str = ' '.join(filenames)
        funcname_str = ' '.join(function_names)
        combined_str = filepath_str + ' ' + funcname_str
        
        # 1. Detect main category (stack-based)
        result['call_category'] = cls._detect_category(filepath_str, funcname_str)

        # 1b. CONTEXT FALLBACK: When stack returns 'other', use SessionContext to detect
        # agent_inference calls. This is needed because LangGraph runs nodes in separate
        # asyncio tasks, so the react_agent_inference.py frames are absent from the stack
        # by the time the token hook fires. If an agent_id is present in SessionContext,
        # the call is definitionally an agent_inference call.
        if result['call_category'] == 'other':
            try:
                from telemetry_wrapper import SessionContext
                ctx = SessionContext.get()
                # SessionContext tuple: 0=user_id, 1=session_id, 3=agent_id, 9=agent_type
                agent_id  = ctx[3]  if ctx[3]  != 'Unassigned' else None
                agent_type = ctx[9] if ctx[9]  != 'Unassigned' else None
                if agent_id:
                    result['call_category'] = 'agent_inference'
                    if agent_type:
                        result['agent_type'] = agent_type
                    log.info(f"🔍 Context fallback → agent_inference (agent_id={agent_id}, agent_type={agent_type})")
            except Exception as e:
                log.debug(f"Context fallback skipped: {e}")

        # 2. Detect sub-category based on category
        if result['call_category'] == 'agent_inference':
            # Prefer stack-based detection; fall back to value already set by context fallback
            stack_agent_type = cls._detect_agent_type(combined_str)
            result['agent_type'] = stack_agent_type or result.get('agent_type')
            result['agent_component'] = cls._detect_component(combined_str)
            
            # Build sub_category
            parts = []
            if result['agent_type']:
                parts.append(result['agent_type'])
            if result['agent_component']:
                parts.append(result['agent_component'])
            else:
                # Check if streaming
                if 'astream' in funcname_str or 'stream' in funcname_str:
                    parts.append('stream')
                else:
                    parts.append('invoke')
            
            result['call_sub_category'] = '_'.join(parts) if parts else 'agent_general'
            result['call_operation'] = 'chat_inference'
            
        elif result['call_category'] == 'tool_operation':
            result['tool_operation'] = cls._detect_tool_operation(combined_str)
            result['call_sub_category'] = f"tool_{result['tool_operation']}" if result['tool_operation'] else 'tool_general'
            result['call_operation'] = result['tool_operation'] or 'tool_operation'
            
        elif result['call_category'] == 'evaluation':
            result['evaluation_type'] = cls._detect_evaluation_type(combined_str)
            result['call_sub_category'] = f"eval_{result['evaluation_type']}" if result['evaluation_type'] else 'eval_general'
            result['call_operation'] = 'evaluation'
            
        elif result['call_category'] == 'prompt_generation':
            result['call_sub_category'] = 'prompt_generation'
            result['call_operation'] = 'generate_prompt'
            
        elif result['call_category'] == 'file_analysis':
            result['call_sub_category'] = 'file_analysis'
            result['call_operation'] = 'analyze_file'
            
        elif result['call_category'] == 'rag_query':
            result['call_sub_category'] = 'rag_query'
            result['call_operation'] = 'knowledge_retrieval'
            
        elif result['call_category'] == 'guardrail':
            result['call_sub_category'] = 'guardrail_check'
            result['call_operation'] = 'content_moderation'
            
        elif result['call_category'] == 'conversation':
            result['call_sub_category'] = 'conversation_management'
            result['call_operation'] = 'conversation'
        
        log.debug(f"🔍 Auto-categorized call: {result}")
        return result
    
    @classmethod
    def _detect_category(cls, filepath_str: str, funcname_str: str) -> str:
        """Detect main category from file path and function names"""
        combined = filepath_str + ' ' + funcname_str
        
        log.info(f"🔍 [Categorizer] filepath_str: {filepath_str[:400] if len(filepath_str) > 400 else filepath_str}")
        log.info(f"🔍 [Categorizer] funcname_str: {funcname_str[:400] if len(funcname_str) > 400 else funcname_str}")
        
        # PRIORITY 1: Check for specific operation types FIRST (tool, agent, evaluation, etc.)
        # These take precedence over infrastructure (guardrail_aware_llm.py file)
        for category, patterns in cls.FILE_PATTERNS.items():
            if category == 'guardrail':
                continue  # Handle guardrail LAST (lowest priority)
            for pattern in patterns:
                if pattern.lower() in combined:
                    log.info(f"🔍 Matched category '{category}' via FILE_PATTERNS (pattern: '{pattern}')")
                    return category
        
        # PRIORITY 2: Check function name patterns for specific operations
        for category, patterns in cls.FUNCTION_PATTERNS.items():
            if any(pattern.lower() in funcname_str for pattern in patterns):
                log.info(f"🔍 Matched category '{category}' via FUNCTION_PATTERNS (priority match)")
                return category
        
        # PRIORITY 3 (LOWEST): Only categorize as guardrail if:
        # - guardrail_aware_llm.py is in path AND
        # - NO other specific operation was detected above AND
        # - There's evidence of actual moderation/safety operations
        if 'guardrail_aware_llm' in filepath_str:
            has_guardrail_evidence = any([
                'moderation' in funcname_str,
                'safety' in funcname_str,
                'content_filter' in funcname_str,
            ])
            log.info(f"🔍 Guardrail check (fallback): evidence={has_guardrail_evidence}")
            if has_guardrail_evidence:
                log.info(f"🔍 Categorized as guardrail (no specific operation detected)")
                return 'guardrail'
        
        # If nothing matched, default to 'other'
        log.info(f"🔍 No category match - defaulting to 'other'")
        log.info(f"🔍 [Categorizer] DEBUG: Checked {len(cls.FILE_PATTERNS)} file patterns and {len(cls.FUNCTION_PATTERNS)} function patterns")
        return 'other'
    
    @classmethod
    def _detect_agent_type(cls, combined_str: str) -> Optional[str]:
        """Detect agent type"""
        for agent_type, patterns in cls.AGENT_TYPE_PATTERNS.items():
            if any(pattern in combined_str for pattern in patterns):
                return agent_type
        return None
    
    @classmethod
    def _detect_component(cls, combined_str: str) -> Optional[str]:
        """Detect agent component"""
        for component, patterns in cls.COMPONENT_PATTERNS.items():
            if any(pattern in combined_str for pattern in patterns):
                return component
        return None
    
    @classmethod
    def _detect_tool_operation(cls, combined_str: str) -> Optional[str]:
        """Detect tool operation type"""
        for operation, patterns in cls.TOOL_OPERATION_PATTERNS.items():
            if any(pattern in combined_str for pattern in patterns):
                return operation
        return None
    
    @classmethod
    def _detect_evaluation_type(cls, combined_str: str) -> Optional[str]:
        """Detect evaluation type"""
        for eval_type, patterns in cls.EVALUATION_TYPE_PATTERNS.items():
            if any(pattern in combined_str for pattern in patterns):
                return eval_type
        return None


# Convenience function for use in wrappers
def auto_categorize_llm_call() -> Dict[str, Optional[str]]:
    """
    Automatically categorize the current LLM call
    
    Returns:
        Dictionary with categorization info
    """
    return CallCategorizer.categorize_call()


__all__ = ['CallCategorizer', 'auto_categorize_llm_call']
