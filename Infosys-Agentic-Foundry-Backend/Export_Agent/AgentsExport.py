import os
import sys
import json
import black
import shutil
import asyncio
import asyncpg
import tempfile
import zipfile
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.database.services import ToolService, AgentService, McpToolService, ExportService
from src.auth.repositories import UserRepository
from src.config.constants import AgentType
from telemetry_wrapper import logger as log
from Export_Agent.export_dependency_analyzer import generate_export_requirements
if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class AgentExporter:
    STATIC_TEMPLATE_FOLDER = 'Export_Agent/Agentcode'    # Final export template base (configs etc.)

    SHARED_FILES = [
        ('telemetry_wrapper.py', 'Agent_Backend'),
        ('groundtruth.py', 'Agent_Backend'),
        ('MultiDBConnection_Manager.py','Agent_Backend'),
        ('VERSION', 'Agent_Backend'),
        ('main.py', 'Agent_Backend'),
        ('.env.example', 'Agent_Backend'),
        ('model_server.py', 'Agent_Backend'),
        ('README.md', 'Agent_Backend')
    ]

    # Marker constants for export preprocessing
    EXPORT_EXCLUDE_START = '# EXPORT:EXCLUDE:START'
    EXPORT_EXCLUDE_END = '# EXPORT:EXCLUDE:END'
    EXPORT_INCLUDE_START = '# EXPORT:INCLUDE:START'
    EXPORT_INCLUDE_END = '# EXPORT:INCLUDE:END'

    def __init__(
        self,
        agent_ids: List[str],
        user_email: str,
        file_names: List[str],
        env_config: Dict[str, Any],
        tool_service: ToolService,
        agent_service: AgentService,
        mcp_service: McpToolService,
        export_service: ExportService,
        export_and_deploy: bool,
        login_pool: asyncpg.Pool,
    ):
        self.agent_ids = agent_ids
        self.user_email = user_email
        self.work_dir = tempfile.mkdtemp(prefix='Agent_code_')
        self.filenames=file_names
        self.env_config=env_config
        self.tool_service = tool_service
        self.agent_service = agent_service
        self.mcp_service = mcp_service
        self.export_service = export_service
        self.export_and_deploy=export_and_deploy
        self.login_pool = login_pool

    #------------------------------------------------------------------------
    @staticmethod
    def extract_frontend_from_zip():
        """
        Extracts the bundled Frontend-Export.zip to Export_Agent/Agentcode/Agent_Frontend.
        This runs once at server startup to populate the frontend code.
        Deletes existing Agent_Frontend folder first to ensure clean extraction.
        """
        # Paths
        base_dir = os.path.dirname(os.path.abspath(__file__))
        zip_path = os.path.join(base_dir, 'Frontend-Export.zip')
        target_path = os.path.join(base_dir, 'Agentcode', 'Agent_Frontend')
        
        # Check if ZIP exists
        if not os.path.exists(zip_path):
            log.warning(f'Frontend ZIP not found at {zip_path}. Frontend will not be included in exports.')
            return False
        
        log.info(f'Extracting frontend from {zip_path}')
        
        # Clean up existing Agent_Frontend folder first
        if os.path.exists(target_path):
            try:
                shutil.rmtree(target_path)
                log.info(f'Removed existing Agent_Frontend folder at {target_path}')
            except Exception as e:
                log.error(f'Error removing existing Agent_Frontend folder: {e}')
        
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                # Extract ZIP to temp directory
                with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
                log.info('ZIP extracted to temporary directory.')
                
                # Find the root folder (GitHub format: {repo}-{branch})
                extracted_folders = os.listdir(temp_dir)
                if not extracted_folders:
                    log.error('No contents found in extracted ZIP')
                    return False
                
                source_folder = os.path.join(temp_dir, extracted_folders[0])
                
                # Create target directory
                os.makedirs(target_path, exist_ok=True)
                
                # Copy contents to target folder
                for item in os.listdir(source_folder):
                    s = os.path.join(source_folder, item)
                    d = os.path.join(target_path, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)
                
                log.info(f'Frontend extracted successfully to {target_path}')
                return True
                
            except zipfile.BadZipFile as e:
                log.error(f'Invalid ZIP file: {e}')
                return False
            except Exception as e:
                log.error(f'Error extracting frontend: {e}')
                return False

    #------------------------------------------------------------------------
    
    def clean_nested_nulls_iterative(self,data, default_null=""):
        """
        Clean None values in nested lists/dicts without recursion.
        Works for structures like validation_criteria.
        """
        stack = [data]

        while stack:
            item = stack.pop()

            if isinstance(item, dict):
                for k, v in item.items():
                    if v is None:
                        item[k] = default_null
                    elif isinstance(v, (dict, list)):
                        stack.append(v)

            elif isinstance(item, list):
                for idx, v in enumerate(item):
                    if v is None:
                        item[idx] = default_null
                    elif isinstance(v, (dict, list)):
                        stack.append(v)

        return data


    async def gather_agent_configs(self) -> Dict[str, Any]:
        configs = {}
        for agent_id in self.agent_ids:
            data =await self.agent_service.get_agent(agentic_application_id=agent_id)
            if not data or not isinstance(data, list):
                raise Exception(f"No data found for Agent ID {agent_id}")
            agent_dict = data[0]
            configs[agent_id] = await self.serialize_agent(agent_dict)
        return configs
    #------------------------------------------------------------------------    
    def format_python_code_string(self,code_string: str) -> str:
        try:
            mode = black.Mode(line_length=88)
            formatted_code = black.format_str(code_string, mode=mode)      
            return formatted_code
        except black.InvalidInput as e:
            raise e
        except Exception as e:
            raise e
    #------------------------------------------------------------------------        
    async def get_tool_data(self, agent_data: dict, export_path: str, tools: List[str] = []):
        if not self.tool_service:
            raise ValueError("ToolService instance is required to fetch tool data.")
        import json
        if not tools:
            tools_id_str = agent_data.get("tools_id")
            tool_ids = tools_id_str
            
            # validator  = agent_data["validation_criteria"][0]["validator"]
            # if validator and validator not in tool_ids:
            #     tool_ids.append(validator)
            validators  = agent_data["validation_criteria"]
            for criterion in validators:
                validator = criterion.get("validator")
                if validator and validator not in tool_ids:
                    tool_ids.append(validator)

        else:
            tool_ids = tools 
        tools_data = {}
        tool_codes = []  # Collect all tool codes for dependency analysis
        prefixes = ('mcp_file_', 'mcp_url_', 'mcp_module_')
        mcp_items = [item for item in tool_ids if item.startswith(prefixes)]
        tool_ids = [item for item in tool_ids if not item.startswith(prefixes)]
        if mcp_items:
            for mcp_id in mcp_items:
                mcp_data = await self.mcp_service.get_mcp_tool(tool_id=mcp_id)
                if mcp_data:
                    mcp_dict = mcp_data[0]
                    processed_mcp_dict = {}
                    default_null=""
                    for key, value in mcp_dict.items():
                        if key not in ["created_on", "updated_on","db_connection_name","is_public","status","comments","approved_at","approved_by","department_name"]:
                            if isinstance(value, datetime):
                                processed_mcp_dict[key] = value.isoformat()
                            else:
                                processed_mcp_dict[key] = value if value is not None else default_null
                    tools_data[mcp_id] = processed_mcp_dict
                else:
                    tools_data[mcp_id] = None
        for tool_id in tool_ids:
            tool_data = await self.tool_service.get_tool(tool_id=tool_id)
            if tool_data:
                tool_dict= tool_data[0]
                processed_tool_dict = {}
                default_null=""
                for key, value in tool_dict.items():
                    if key not in ["created_on", "updated_on","db_connection_name","is_public","status","comments","approved_at","approved_by","department_name"]:
                        if isinstance(value, datetime):
                            processed_tool_dict[key] = value.isoformat()
                        else:
                            processed_tool_dict[key] = value if value is not None else default_null
                name=tool_dict["tool_name"]
                raw_code=tool_dict["code_snippet"]
                final_code=self.format_python_code_string(raw_code)
                tool_codes.append(final_code)  # Store tool code for dependency analysis
                file_path=os.path.join(export_path,f'Agent_Backend/tools_codes/{name}.py')         
                try:
                    path_obj = Path(file_path)
                    parent_directory = path_obj.parent
                    parent_directory.mkdir(parents=True, exist_ok=True)
                    with open(path_obj, 'w', encoding='utf-8') as f:
                        f.write(final_code)
                except Exception as e:
                    pass
                processed_tool_dict["code_snippet"]=f'tools_codes/{name}.py'
                # del processed_tool_dict["code_snippet"]
                tools_data[tool_id] = processed_tool_dict
            else:
                tools_data[tool_id] = None
        tool_data_file_path=os.path.join(export_path, 'Agent_Backend/tools_config.py')
        tools_data_json_str = json.dumps(tools_data, indent=4)
        with open(tool_data_file_path, 'w') as f:
                f.write('tools_data = ')
                f.write(tools_data_json_str)
        return tool_codes
    #------------------------------------------------------------------------
    async def serialize_agent(self, agent_dict):
        agent_for_json_dump = {}#agent_dict.copy()
        default_null=""
        for key, value in agent_dict.items():
            if key not in ["created_on", "updated_on","db_connection_name","is_public","status","comments","approved_at","approved_by","department_name"]:
                if isinstance(value, datetime):
                    agent_for_json_dump[key] = value.isoformat()
                
                elif key == "validation_criteria" and isinstance(value, list):
                    # Clean nested dict with NO recursion
                    agent_for_json_dump[key] = self.clean_nested_nulls_iterative(value, default_null)

                else:
                    agent_for_json_dump[key] = value if value is not None else default_null
        return agent_for_json_dump

    #------------------------------------------------------------------------   
    async def store_logs(self,agentic_application_id,agentic_application_name,user_email,user_name):
        import uuid
        eid=str(uuid.uuid4())
        ts=datetime.now()
        await self.export_service.insert_export_log(
            export_id=eid,
            agent_id=agentic_application_id,
            agent_name=agentic_application_name,
            user_email=user_email,
            user_name=user_name,
            export_time=ts
        ) 
    #------------------------------------------------------------------------
    async def write_env_and_configs(self, target_path: str, agent_dict: dict, tool_codes: List[str] = None):
        remove_quotes=["DATABASE_URL","POSTGRESQL_HOST","POSTGRESQL_PORT","POSTGRESQL_USER","POSTGRESQL_PASSWORD","DATABASE","CONNECTION_POOL_SIZE","REDIS_HOST","REDIS_PORT","REDIS_DB","REDIS_PASSWORD","CACHE_EXPIRY_TIME","IAF_PASSWORD","ENABLE_CACHING","GITHUB_USERNAME","GITHUB_PAT","GITHUB_EMAIL","TARGET_REPO_NAME","TARGET_REPO_OWNER","TARGET_BRANCH"]
        env_path = os.path.join(target_path, 'Agent_Backend/.env')
        # Write to a file
        if self.env_config:
            with open(env_path, "a") as env_file:
                for key, value in self.env_config.items():
                    if key not in remove_quotes:
                        if value is not None:
                            env_file.write(f'{key}="{value}"\n')
                    else:
                        if value is not None:
                            env_file.write(f'{key}={value}\n')

        config_py_path = os.path.join(target_path, 'Agent_Backend/agent_config.py')
        with open(config_py_path, 'w') as f:
            f.write('agent_data = ')
            json.dump({agent_dict['agentic_application_id']: agent_dict}, f, indent=4)
        
        # Generate requirements based on Export Agent dependencies and tool codes
        req_path = os.path.join(target_path, 'Agent_Backend/requirements.txt')
        try:
            export_requirements = generate_export_requirements(tool_code_strings=tool_codes or [])
            with open(req_path, 'w', encoding='utf-8') as f:
                for req in export_requirements:
                    f.write(f"{req}\n")
        except Exception as e:
            log.warning(f"Failed to generate requirements, falling back to requirements.txt: {e}")
            shutil.copy('requirements.txt', req_path)
        
        await self.store_logs(agent_dict['agentic_application_id'], agent_dict['agentic_application_name'], self.user_email, self.user_email)
    #------------------------------------------------------------------------
    async def write_env_and_agentconfigs(self, target_path: str, configs: dict, tool_codes: List[str] = None):
        remove_quotes=["DATABASE_URL","POSTGRESQL_HOST","POSTGRESQL_PORT","POSTGRESQL_USER","POSTGRESQL_PASSWORD","DATABASE","CONNECTION_POOL_SIZE","REDIS_HOST","REDIS_PORT","REDIS_DB","REDIS_PASSWORD","CACHE_EXPIRY_TIME","IAF_PASSWORD","ENABLE_CACHING"]
        # Write to a file
        env_path = os.path.join(target_path, 'Agent_Backend/.env')
        if self.env_config:
            with open(env_path, "a") as env_file:
                for key, value in self.env_config.items():
                    if key not in remove_quotes:
                        if value is not None:
                            env_file.write(f'{key}="{value}"\n')
                    else:
                        if value is not None:
                            env_file.write(f'{key}={value}\n')

        config_py_path = os.path.join(target_path, 'Agent_Backend/agent_config.py')
        adict = {agent_id: agent_dict for agent_id, agent_dict in configs.items()}
        with open(config_py_path, 'w') as f:
            f.write('agent_data = ')
            json.dump(adict, f, indent=4)
        
        # Generate requirements based on Export Agent dependencies and tool codes
        req_path = os.path.join(target_path, 'Agent_Backend/requirements.txt')
        try:
            export_requirements = generate_export_requirements(tool_code_strings=tool_codes or [])
            with open(req_path, 'w', encoding='utf-8') as f:
                for req in export_requirements:
                    f.write(f"{req}\n")
        except Exception as e:
            log.warning(f"Failed to generate requirements, falling back to requirements.txt: {e}")
            shutil.copy('requirements.txt', req_path)
        
        for agent_id, agent_dict in configs.items():
            await self.store_logs(agent_dict['agentic_application_id'],agent_dict['agentic_application_name'], self.user_email, self.user_email)
    #------------------------------------------------------------------------
    def copy_static_template_base(self, dst_folder: str):
        shutil.copytree(self.STATIC_TEMPLATE_FOLDER, dst_folder)
    #------------------------------------------------------------------------
    def copy_shared_files(self, target_folder: str):
        for src, subdir in self.SHARED_FILES:
            subdir_target = os.path.join(target_folder, subdir)
            os.makedirs(subdir_target, exist_ok=True)
            shutil.copy(src, subdir_target)
            py_target = os.path.join(subdir_target, os.path.basename(src))
    #------------------------------------------------------------------------
    def copy_user_uploads(self, target_folder: str):
        src = os.path.join(os.getcwd(), 'user_uploads')
        if self.filenames:
            for file in self.filenames:
                if "__files__/" in str(file):
                    file = file.replace("__files__/", "")
                source_file = os.path.join(src, file)
                if os.path.isfile(source_file):
                    # Replicate subdirectory structure in destination
                    dest_file_path = os.path.join(target_folder, 'Agent_Backend', 'user_uploads', file)
                    dest_dir = os.path.dirname(dest_file_path)
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.copy(source_file, dest_file_path)
    #------------------------------------------------------------------------

    def copy_src_folder(self, target_folder: str):
        """Copy the src/ folder to the export, then process EXPORT markers.

        Excludes: __pycache__, agent_templates, onboard, chat_logs.
        Copies src/api/ as-is (no longer uses Export_Agent/api/).
        After copying, runs process_export_markers() on every .py file
        to strip EXCLUDE blocks and uncomment INCLUDE blocks.
        """
        src = os.path.join(os.getcwd(), 'src')
        dest = os.path.join(target_folder, 'Agent_Backend', 'src')

        if os.path.exists(dest):
            shutil.rmtree(dest)

        shutil.copytree(
            src,
            dest,
            ignore=shutil.ignore_patterns(
                '__pycache__', '*.pyc', '*.pyo', '*.pyd', '.Python',
                'env', 'venv', 'ENV', 'env.bak', 'venv.bak',
                'agent_templates', 'chat_logs', 'onboard'
            )
        )

    #------------------------------------------------------------------------
    def copy_knowledgebase_server(self, target_folder: str):
        """Copy the knowledgebase_server folder into Agent_Backend."""
        src = os.path.join(os.getcwd(), 'knowledgebase_server')
        dest = os.path.join(target_folder, 'Agent_Backend', 'knowledgebase_server')
        if os.path.exists(src):
            shutil.copytree(
                src,
                dest,
                ignore=shutil.ignore_patterns(
                    '__pycache__', '*.pyc', '*.pyo', '*.pyd', '.Python',
                    '.env', 'env', '.venv', 'ENV', 'env.bak', 'venv.bak'
                )
            )
        else:
            log.warning('knowledgebase_server folder not found, skipping.')

    # ------------------------------------------------------------------ #
    @staticmethod
    def process_export_markers(directory: str):
        """Walk *directory* and process every ``.py`` file for EXPORT markers.

        Supported markers (must appear as Python comments at any indentation):

        ``# EXPORT:EXCLUDE:START`` / ``# EXPORT:EXCLUDE:END``
            Lines between (inclusive of the marker lines) are **removed**.

        ``# EXPORT:INCLUDE:START`` / ``# EXPORT:INCLUDE:END``
            The marker lines are removed and every line between them is
            **uncommented** by stripping the first ``# `` (hash + space)
            that follows the leading whitespace.  This means the code is
            dormant in the source repository (commented out) but becomes
            active in the export.

        The function modifies files **in-place** — always call it on a
        *copy*, never on the original source tree.
        """
        for dirpath, _, filenames in os.walk(directory):
            for fname in filenames:
                if not fname.endswith('.py'):
                    continue
                fpath = os.path.join(dirpath, fname)
                try:
                    with open(fpath, 'r', encoding='utf-8') as f:
                        lines = f.readlines()

                    new_lines: list = []
                    skip_mode = False      # inside EXCLUDE block
                    include_mode = False   # inside INCLUDE block

                    for line in lines:
                        stripped = line.strip()

                        # ── EXCLUDE markers ──
                        if stripped == AgentExporter.EXPORT_EXCLUDE_START:
                            skip_mode = True
                            continue
                        if stripped == AgentExporter.EXPORT_EXCLUDE_END:
                            skip_mode = False
                            continue
                        if skip_mode:
                            continue

                        # ── INCLUDE markers ──
                        if stripped == AgentExporter.EXPORT_INCLUDE_START:
                            include_mode = True
                            continue
                        if stripped == AgentExporter.EXPORT_INCLUDE_END:
                            include_mode = False
                            continue
                        if include_mode:
                            # Uncomment: remove the first '# ' after leading whitespace
                            leading = len(line) - len(line.lstrip())
                            rest = line[leading:]  # e.g. '# feedback_pool = main_pool\n'
                            if rest.startswith('# '):
                                new_lines.append(line[:leading] + rest[2:])
                            else:
                                # Safety: if the line is not commented, keep as-is
                                new_lines.append(line)
                            continue

                        # ── Normal line ──
                        new_lines.append(line)

                    with open(fpath, 'w', encoding='utf-8') as f:
                        f.writelines(new_lines)
                except Exception as e:
                    log.warning(f'Error processing export markers in {fpath}: {e}')

    #------------------------------------------------------------------------
    async def build_agent_folder(self, agent_id: str, agent_dict: dict) -> str:
        agent_type = agent_dict['agentic_application_type']
        if agent_type == AgentType.REACT_AGENT:
            foldername='React Agent'
        elif agent_type == AgentType.REACT_CRITIC_AGENT:
            foldername='React Critic Agent'
        elif agent_type == AgentType.PLANNER_EXECUTOR_AGENT:
            foldername='Planner Executor Agent'
        elif agent_type == AgentType.PLANNER_EXECUTOR_CRITIC_AGENT:
            foldername="Multi Agent"
        elif agent_type == AgentType.META_AGENT:
            foldername='Meta Agent'
        elif agent_type == AgentType.PLANNER_META_AGENT:
            foldername='Planner Meta Agent'
        elif agent_type == AgentType.HYBRID_AGENT:
            foldername='Hybrid Agent'
        target_folder = os.path.join(self.work_dir, f"{foldername}")
        self.copy_static_template_base(target_folder)     # final export folder (Agent_code)
        
        tool_codes = []  # Collect tool codes for dependency analysis
        
        self.copy_shared_files(target_folder)
        self.copy_src_folder(target_folder)
        self.copy_knowledgebase_server(target_folder)
        self.copy_user_uploads(target_folder)

        agent_backend = os.path.join(target_folder, 'Agent_Backend')
        os.makedirs(agent_backend, exist_ok=True)
        if agent_type in AgentType.meta_types():
            worker_agent_ids = agent_dict.get("tools_id")
            worker_agents = {}
            for wid in worker_agent_ids:
                worker_data =await self.agent_service.get_agent(agentic_application_id=wid)
                if worker_data:
                    worker_dict = worker_data[0]
                    processed_dict={}
                    default_null=""
                    for k, v in worker_dict.items():
                        if k not in ["created_on", "updated_on","db_connection_name","is_public","status","comments","approved_at","approved_by","department_name"]:
                            if isinstance(v, datetime):
                                processed_dict[k] = v.isoformat()
                            else:
                                processed_dict[k] = v if v is not None else default_null
                    worker_agents[wid] = processed_dict
                else:
                    worker_agents[wid] = None
            worker_agents_path = os.path.join(agent_backend, "worker_agents_config.py")
            with open(worker_agents_path, 'w') as f:
                f.write('worker_agents = ')
                json.dump(worker_agents, f, indent=4)
            tools_ids = set()
            for wid in worker_agents:
                tool_list = worker_agents[wid]["tools_id"]
                for tid in tool_list:
                    tools_ids.add(tid)                
            # validator = worker_agents[wid]["validation_criteria"][0]["validator"]
            validators = worker_agents[wid]["validation_criteria"]
            for criterion in validators:
                validator = criterion.get("validator")
                if validator:
                    tools_ids.add(validator)
            # if validator:
            #     tools_ids.add(validator)
            await self.get_tool_data(agent_dict, export_path=target_folder, tools=tools_ids)
        else:
            worker_agents_path = os.path.join(agent_backend, "worker_agents_config.py")
            with open(worker_agents_path, 'w') as f:
                f.write('worker_agents = {}\n')
            tool_codes = await self.get_tool_data(agent_dict, export_path=target_folder)
        
        # Pass tool codes to write_env_and_configs for dependency analysis
        await self.write_env_and_configs(target_folder, agent_dict, tool_codes=tool_codes)

        # Process EXPORT markers on all .py files in Agent_Backend (main.py, db_load.py, src/)
        self.process_export_markers(agent_backend)
        
        return target_folder
    #------------------------------------------------------------------------
    async def build_multi_agent_folder(self, configs: Dict[str, Any]) -> str:
        target_folder = os.path.join(self.work_dir, "Multiple_Agents")
        self.copy_static_template_base(target_folder)
        
        tool_codes = []  # Collect tool codes for dependency analysis
        
        self.copy_shared_files(target_folder)
        self.copy_src_folder(target_folder)
        self.copy_knowledgebase_server(target_folder)
        self.copy_user_uploads(target_folder)

        agent_backend = os.path.join(target_folder, 'Agent_Backend')
        os.makedirs(agent_backend, exist_ok=True)
        tools_ids = set()
        worker_ids = set()
        test=[]
        for agent in configs.values():
            atype = agent['agentic_application_type']
            if atype in AgentType.meta_types():
                worker_agent_ids = agent.get("tools_id")
                worker_ids.update(worker_agent_ids)
                # validator = agent["validation_criteria"][0]["validator"]
                # if validator:
                #     tools_ids.add(validator)
                validators  = agent["validation_criteria"]
                for criterion in validators:
                    validator = criterion.get("validator")
                    if validator and validator not in tools_ids:
                        tools_ids.add(validator)
            else:
                tool_ids_list = agent.get('tools_id')
                tools_ids.update(tool_ids_list)
                validators  = agent["validation_criteria"]
                for criterion in validators:
                    validator = criterion.get("validator")
                    if validator and validator not in tools_ids:
                        tools_ids.add(validator)
        worker_agents = {}
        for wid in worker_ids:
            worker_data =await self.agent_service.get_agent(agentic_application_id=wid)
            if worker_data:
                worker_dict = worker_data[0]
                default_null=""
                processed_dict={}
                for k, v in worker_dict.items():
                    if k not in ["created_on", "updated_on","db_connection_name","is_public","status","comments","approved_at","approved_by","department_name"]:
                        if isinstance(v, datetime):
                            processed_dict[k] = v.isoformat()
                        else:
                            # processed_dict[k] = v
                            processed_dict[k] = v if v is not None else default_null
                worker_agents[wid] = processed_dict
            else:
                worker_agents[wid] = None
        worker_agents_path = os.path.join(agent_backend, "worker_agents_config.py")
        with open(worker_agents_path, 'w') as f:
            f.write('worker_agents = ')
            json.dump(worker_agents, f, indent=4)
        for wid in worker_agents:
            tool_list = worker_agents[wid]["tools_id"]
            for tid in tool_list:
                tools_ids.add(tid)
            validators = worker_agents[wid]["validation_criteria"]
            for criterion in validators:
                validator = criterion.get("validator")
                if validator:
                    tools_ids.add(validator)     
        tool_codes = await self.get_tool_data(configs, export_path=target_folder, tools=tools_ids)
        
        # Pass tool codes to write_env_and_agentconfigs for dependency analysis
        await self.write_env_and_agentconfigs(target_folder, configs, tool_codes=tool_codes)

        # Process EXPORT markers on all .py files in Agent_Backend (main.py, db_load.py, src/)
        self.process_export_markers(agent_backend)
        
        return target_folder
    #------------------------------------------------------------------------
    async def export(self):
        """
        Export the agent(s) to a zip file.
        Frontend code is included via copy_static_template_base() which copies from
        Export_Agent/Agentcode (which includes Agent_Frontend extracted at server startup).
        
        Returns:
            str: Path to the generated zip archive.
        """
        configs = await self.gather_agent_configs()
        # print(configs)
        agent_folders = []
        if len(configs) == 1:
            for agent_id, agent_dict in configs.items():
                fpath = await self.build_agent_folder(agent_id, agent_dict)
                agent_folders.append(fpath)
        else:
            fpath = await self.build_multi_agent_folder(configs)
            agent_folders.append(fpath)
        zip_output = os.path.join(tempfile.gettempdir(), "ExportAgent")
        archive_path = shutil.make_archive(zip_output, 'zip', self.work_dir)
        return archive_path
    #------------------------------------------------------------------------
