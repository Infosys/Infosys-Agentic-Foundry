import os
import sys
import json
import black
import shutil
import asyncio
import asyncpg
import tempfile
import subprocess
from fastapi import HTTPException
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.database.services import ToolService, AgentService

if sys.platform.startswith('win'):
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

class AgentExporter:
    STATIC_TEMPLATE_FOLDER = 'Export_Agent/Agentcode'    # Final export template base (configs etc.)
    STATIC_EXPORT_ROOT = 'Export_Agent/export_root'      # Backend package source root for wheel build

    ENDPOINTS = {
        'react_agent': 'Export_Agent/endpoints/react_agent_endpoints.py',
        'react_critic_agent': 'Export_Agent/endpoints/react_critic_agent_endpoints.py',
        'planner_executor_agent': 'Export_Agent/endpoints/planner_executor_agent_endpoints.py',
        'multi_agent': 'Export_Agent/endpoints/planner_executor_critic_agent_endpoints.py',
        'meta_agent': 'Export_Agent/endpoints/meta_agent_endpoints.py',
        'planner_meta_agent': 'Export_Agent/endpoints/planner_meta_agent_endpoints.py',
        'multiple': 'Export_Agent/endpoints/multiple_agent_endpoints.py',
    }

    INFERENCE_SCRIPTS = {
        'react_agent': ['src/inference/inference_utils.py', 'src/inference/react_agent_inference.py'],
        'react_critic_agent': ['src/inference/inference_utils.py', 'src/inference/react_critic_agent_inference.py', 'src/inference/react_agent_inference.py'],
        'planner_executor_agent': ['src/inference/inference_utils.py', 'src/inference/planner_executor_agent_inference.py', 'src/inference/react_agent_inference.py'],
        'multi_agent': ['src/inference/inference_utils.py', 'src/inference/planner_executor_critic_agent_inference.py', 'src/inference/react_agent_inference.py'],
        'meta_agent': ['src/inference/inference_utils.py', 'src/inference/meta_agent_inference.py', 'src/inference/react_agent_inference.py'],
        'planner_meta_agent': ['src/inference/inference_utils.py', 'src/inference/planner_meta_agent_inference.py', 'src/inference/react_agent_inference.py'],
        'multiple': [
            'src/inference/inference_utils.py',
            'src/inference/react_critic_agent_inference.py',
            'src/inference/react_agent_inference.py',
            'src/inference/planner_executor_agent_inference.py',
            'src/inference/planner_executor_critic_agent_inference.py',
            'src/inference/meta_agent_inference.py',
            'src/inference/planner_meta_agent_inference.py',
        ],
    }

    SHARED_FILES = [
        ('telemetry_wrapper.py', 'iaf/exportagent'),
        ('groundtruth.py', 'iaf/exportagent'),
        ('MultiDBConnection_Manager.py','iaf/exportagent'),
        ('src/database/core_evaluation_service.py', 'iaf/exportagent/src/database'),
        ('src/database/redis_postgres_manager.py', 'iaf/exportagent/src/database'),
        ('src/utils/secrets_handler.py', 'iaf/exportagent/src/utils'),
        ('src/utils/stream_sse.py', 'iaf/exportagent/src/utils'),
        ('src/inference/base_agent_inference.py', 'iaf/exportagent/src/inference'),
    ]

    def __init__(
        self,
        agent_ids: List[str],
        user_email: str,
        tool_service,
        agent_service,
        export_repo
    ):
        self.agent_ids = agent_ids
        self.user_email = user_email
        self.work_dir = tempfile.mkdtemp(prefix='Agent_code_')
        self.exp_dir = tempfile.mkdtemp(prefix='backend_build_')
        self.tool_service = tool_service
        self.agent_service = agent_service
        self.export_repo = export_repo
    #------------------------------------------------------------------------
    def patch_imports(self, pyfile: str):
        replacements = [
            ("from src.", "from exportagent.src."),
            ("import src.", "import exportagent.src."),
            ("from telemetry_wrapper", "from exportagent.telemetry_wrapper"),
            ("from evaluation_metrics", "from exportagent.evaluation_metrics"),
            ("from database_manager", "from exportagent.database_manager"),
            ("from database_creation", "from exportagent.database_creation"),
            ("from groundtruth", "from exportagent.groundtruth"),
            ("from MultiDBConnection_Manager", "from exportagent.MultiDBConnection_Manager")
        ]
        with open(pyfile, 'r', encoding='utf-8') as f:
            code = f.read()
        for old, new in replacements:
            if old in code:
                code = code.replace(old, new)
        with open(pyfile, 'w', encoding='utf-8') as f:
            f.write(code)
    #------------------------------------------------------------------------
    async def gather_agent_configs(self) -> Dict[str, Any]:
        configs = {}
        for agent_id in self.agent_ids:
            data =await self.agent_service.get_agent(agentic_application_id=agent_id)
            if not data or not isinstance(data, list):
                raise Exception(f"No data found for Agent ID {agent_id}")
            agent_dict = data[0]
            configs[agent_id] = self.serialize_agent(agent_dict)
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
    async def get_tool_data(self,agent_data, export_path, tool_service: ToolService = None, tools=[]):
        if not tool_service:
            raise ValueError("ToolService instance is required to fetch tool data.")
        import json
        if not tools:
            tools_id_str = agent_data.get("tools_id")
            tool_ids = tools_id_str
        else:
            tool_ids = tools
        if (any(s.startswith('mcp_file') for s in list(tool_ids)) or any(s.startswith('mcp_url') for s in list(tool_ids))) and len(self.agent_ids)==1:
            # raise ValueError("Cannot Export Agent having MCP Tools. Please Ignore and select other agent")
            raise ValueError("Current version does not support MCP agents Export.Hence this agent cannot be exported")
        tools_data = {}  
        for tool_id in tool_ids:
            tool_data = await tool_service.get_tool(tool_id=tool_id)
            if tool_data:
                tool_dict= tool_data[0]
                processed_tool_dict = {}
                for key, value in tool_dict.items():
                    if key not in ["created_on", "updated_on", "tags","db_connection_name","is_public","status","comments","approved_at","approved_by"]:
                        if isinstance(value, datetime):
                            processed_tool_dict[key] = value.isoformat()
                        else:
                            processed_tool_dict[key] = value
                name=tool_dict["tool_name"]
                raw_code=tool_dict["code_snippet"]
                final_code=self.format_python_code_string(raw_code)
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
    #------------------------------------------------------------------------
    def serialize_agent(self, agent_dict):
        agent_for_json_dump = {}#agent_dict.copy()
        for key, value in agent_dict.items():
            if key not in ["created_on", "updated_on", "tags","db_connection_name","is_public","status","comments","approved_at","approved_by"]:
                if isinstance(value, datetime):
                    agent_for_json_dump[key] = value.isoformat()
                else:
                    agent_for_json_dump[key] = value
        return agent_for_json_dump
    #------------------------------------------------------------------------    
    async def get_user_from_email(self,user_email: str) -> Optional[tuple]:
        conn = await asyncpg.connect(
            host=os.getenv('POSTGRESQL_HOST', 'localhost'),
            database='login',
            user=os.getenv('POSTGRESQL_USER', 'postgres'),
            password=os.getenv('POSTGRESQL_PASSWORD', 'password'),
        )
        user_data = await conn.fetchrow(
            "SELECT user_name, role FROM login_credential WHERE mail_id = $1", user_email
        )
        await conn.close()
        if user_data:
            return user_data[0], user_data[1]
        return None
    #------------------------------------------------------------------------   
    async def store_logs(self,agentic_application_id,agentic_application_name,user_email,user_name):
        import uuid
        eid=str(uuid.uuid4())
        ts=datetime.now()
        await self.export_repo.insert_export_log(
            export_id=eid,
            agent_id=agentic_application_id,
            agent_name=agentic_application_name,
            user_email=user_email,
            user_name=user_name,
            export_time=ts
        ) 
    #------------------------------------------------------------------------
    async def write_env_and_configs(self, target_path: str, agent_dict: dict):
        user = role = None
        if self.user_email:
            res = await self.get_user_from_email(self.user_email)
            if res: user, role = res[0], res[1]

        env_path = os.path.join(target_path, 'Agent_Backend/.env')
        with open(env_path, 'a') as f:
            f.write(f"\nUSER_EMAIL={self.user_email or ''}\nUSER_NAME={user or ''}\nROLE={role or ''}\n")
        config_py_path = os.path.join(target_path, 'Agent_Backend/agent_config.py')
        with open(config_py_path, 'w') as f:
            f.write('agent_data = ')
            json.dump({agent_dict['agentic_application_id']: agent_dict}, f, indent=4)
        req_path =os.path.join(target_path, 'Agent_Backend/requirements.txt')
        shutil.copy('requirements.txt', req_path)
        pack="exportagent-0.1.0-py3-none-any.whl"
        with open(req_path, 'a',encoding='utf-16') as f:
            f.write(f'\n{pack}\n')
        await self.store_logs(agent_dict['agentic_application_id'],agent_dict['agentic_application_name'],self.user_email,user)
    #------------------------------------------------------------------------
    async def write_env_and_agentconfigs(self, target_path: str, configs: dict):
        user = role = None
        if self.user_email:
            res = await self.get_user_from_email(self.user_email)
            if res: user, role = res[0], res[1]

        env_path = os.path.join(target_path, 'Agent_Backend/.env')
        with open(env_path, 'a') as f:
            f.write(f"\nUSER_EMAIL={self.user_email or ''}\nUSER_NAME={user or ''}\nROLE={role or ''}\n")

        config_py_path = os.path.join(target_path, 'Agent_Backend/agent_config.py')
        adict = {agent_id: agent_dict for agent_id, agent_dict in configs.items()}
        with open(config_py_path, 'w') as f:
            f.write('agent_data = ')
            json.dump(adict, f, indent=4)
        req_path =os.path.join(target_path, 'Agent_Backend/requirements.txt')
        shutil.copy('requirements.txt', req_path)
        pack="exportagent-0.1.0-py3-none-any.whl"
        with open(req_path, 'a',encoding='utf-16') as f:
            f.write(f'\n{pack}\n')
        for agent_id, agent_dict in configs.items():
            await self.store_logs(agent_dict['agentic_application_id'],agent_dict['agentic_application_name'],self.user_email,user)
    #------------------------------------------------------------------------
    def copy_static_template_base(self, dst_folder: str):
        shutil.copytree(self.STATIC_TEMPLATE_FOLDER, dst_folder)
    #------------------------------------------------------------------------
    def copy_static_export_base(self, dst_folder: str):
        shutil.copytree(self.STATIC_EXPORT_ROOT, dst_folder)
    #------------------------------------------------------------------------
    def copy_shared_files(self, target_folder: str):
        for src, subdir in self.SHARED_FILES:
            subdir_target = os.path.join(target_folder, subdir)
            os.makedirs(subdir_target, exist_ok=True)
            shutil.copy(src, subdir_target)
            py_target = os.path.join(subdir_target, os.path.basename(src))
            if py_target.endswith('.py'):
                self.patch_imports(py_target)
    #------------------------------------------------------------------------
    def copy_inference_files(self, agent_type: str, target_folder: str):
        scripts = self.INFERENCE_SCRIPTS.get(agent_type, [])
        inference_dir = os.path.join(target_folder, 'iaf/exportagent/src/inference')
        os.makedirs(inference_dir, exist_ok=True)
        for script in scripts:
            shutil.copy(script, inference_dir)
            py_target = os.path.join(inference_dir, os.path.basename(script))
            if py_target.endswith('.py'):
                self.patch_imports(py_target)
    #------------------------------------------------------------------------
    def copy_agent_endpoints(self, agent_type: str, target_folder: str):
        endpoints = self.ENDPOINTS.get(agent_type)
        if endpoints:
            backend_path = os.path.join(target_folder, 'iaf/exportagent')
            os.makedirs(backend_path, exist_ok=True)
            destination = os.path.join(backend_path, 'agent_endpoints.py')
            shutil.copy(endpoints, destination)
            self.patch_imports(destination)
        else:
            pass
    #------------------------------------------------------------------------
    def build_wheel(self, build_folder: str, target_agent_backend: str):
        dist_dir = os.path.join(build_folder, "dist")
        if os.path.exists(dist_dir):
            shutil.rmtree(dist_dir)

        result = subprocess.run(
            [sys.executable, "-m", "build", "--wheel", "--outdir", dist_dir],
            cwd=build_folder,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError("Wheel build failed")

        wheels = [f for f in os.listdir(dist_dir) if f.endswith(".whl")]
        if not wheels:
            raise RuntimeError("No wheel file found after build")

        wheel_file = wheels[0]
        wheel_source_path = os.path.join(dist_dir, wheel_file)

        os.makedirs(target_agent_backend, exist_ok=True)
        wheel_target_path = os.path.join(target_agent_backend, wheel_file)
        shutil.move(wheel_source_path, wheel_target_path)
        shutil.rmtree(dist_dir)
        return wheel_target_path
    #------------------------------------------------------------------------
    async def build_agent_folder(self, agent_id: str, agent_dict: dict) -> str:
        unique_id = os.urandom(6).hex()
        agent_type = agent_dict['agentic_application_type']
        if agent_type== 'react_agent':
            foldername='React Agent'
        elif agent_type == 'react_critic_agent':
            foldername='React Critic Agent'
        elif agent_type == 'planner_executor_agent':
            foldername='Planner Executor Agent'
        elif agent_type == 'multi_agent':
            foldername="Multi Agent"
        elif agent_type == 'meta_agent':
            foldername='Meta Agent'
        elif agent_type == 'planner_meta_agent':
            foldername='Planner Meta Agent'
        target_folder = os.path.join(self.work_dir, f"{foldername}")
        build_folder = os.path.join(self.exp_dir, f"{foldername}_{unique_id}")

        self.copy_static_template_base(target_folder)     # final export folder (Agent_code)
        self.copy_static_export_base(build_folder)        # backend code package copy for build
        await self.write_env_and_configs(target_folder, agent_dict)
        self.copy_shared_files(build_folder)
        self.copy_inference_files(agent_type, build_folder)
        self.copy_agent_endpoints(agent_type, build_folder)
        agent_backend = os.path.join(target_folder, 'Agent_Backend')
        os.makedirs(agent_backend, exist_ok=True)
        if agent_type in {"meta_agent", "planner_meta_agent"}:
            worker_agent_ids = agent_dict.get("tools_id")
            worker_agents = {}
            for wid in worker_agent_ids:
                worker_data =await self.agent_service.get_agent(agentic_application_id=wid)
                if worker_data:
                    worker_dict = worker_data[0]
                    processed_dict={}
                    for k, v in worker_dict.items():
                        if k not in ["created_on", "updated_on", "tags","db_connection_name","is_public","status","comments","approved_at","approved_by"]:
                            if isinstance(v, datetime):
                                processed_dict[k] = v.isoformat()
                            else:
                                processed_dict[k] = v
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
            await self.get_tool_data(agent_dict, export_path=target_folder,tool_service=self.tool_service,tools=tools_ids)
        else:
            worker_agents_path = os.path.join(agent_backend, "worker_agents_config.py")
            with open(worker_agents_path, 'w') as f:
                f.write('worker_agents = {}\n')
            await self.get_tool_data(agent_dict, export_path=target_folder,tool_service=self.tool_service)

        self.build_wheel(build_folder, agent_backend)
        return target_folder
    #------------------------------------------------------------------------
    async def test_mcp(self, tools_id_list):
        for wid in tools_id_list:
            worker_data =await self.agent_service.get_agent(agentic_application_id=wid)
            if worker_data:
                worker_dict = worker_data[0]
                worker_tool_ids = worker_dict.get("tools_id")
                if any(s.startswith('mcp_file') for s in list(worker_tool_ids)) or any(s.startswith('mcp_url') for s in list(worker_tool_ids)):
                    return True

    async def build_multi_agent_folder(self, configs: Dict[str, Any]) -> str:
        target_folder = os.path.join(self.work_dir, "Multiple_Agents")
        unique_id = os.urandom(6).hex()
        build_folder = os.path.join(self.exp_dir, f"multiple_{unique_id}")
        self.copy_static_template_base(target_folder)
        self.copy_static_export_base(build_folder)
        await self.write_env_and_agentconfigs(target_folder, configs)
        self.copy_shared_files(build_folder)
        self.copy_inference_files("multiple", build_folder)
        self.copy_agent_endpoints("multiple", build_folder)
        agent_backend = os.path.join(target_folder, 'Agent_Backend')
        os.makedirs(agent_backend, exist_ok=True)
        tools_ids = set()
        worker_ids = set()
        test=[]
        for agent in configs.values():
            atype = agent['agentic_application_type']
            if atype in {"meta_agent", "planner_meta_agent"}:
                worker_agent_ids = agent.get("tools_id")
                if await self.test_mcp(worker_agent_ids):
                    test.append(agent['agentic_application_name'])
                else:
                    worker_ids.update(worker_agent_ids)
            else:
                tool_ids_list = agent.get('tools_id')
                if any(s.startswith('mcp_file') for s in list(tool_ids_list)) or any(s.startswith('mcp_url') for s in list(tool_ids_list)):
                    test.append(agent['agentic_application_name'])
                tools_ids.update(tool_ids_list)
        if test:
            if len(test)==1:
                raise ValueError(f"Current version does not support MCP agents Export.Hence Agent: \"{test[0]}\" is not exported")
            test = ", ".join(test)
            raise ValueError(f"Current version does not support MCP agents Export.Hence Agent: \"{test}\" are not exported")
        worker_agents = {}
        for wid in worker_ids:
            worker_data =await self.agent_service.get_agent(agentic_application_id=wid)
            if worker_data:
                worker_dict = worker_data[0]
                processed_dict={}
                for k, v in worker_dict.items():
                    if k not in ["created_on", "updated_on", "tags","db_connection_name","is_public","status","comments","approved_at","approved_by"]:
                        if isinstance(v, datetime):
                            processed_dict[k] = v.isoformat()
                        else:
                            processed_dict[k] = v
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
        await self.get_tool_data(configs, export_path=target_folder,tool_service=self.tool_service,tools=tools_ids)
        self.build_wheel(build_folder, agent_backend)
        return target_folder
    #------------------------------------------------------------------------
    async def export(self):
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

