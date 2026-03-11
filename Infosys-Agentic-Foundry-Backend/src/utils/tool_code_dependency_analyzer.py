import psycopg2
import ast
import sys
import os
import json
import asyncio
from pathlib import Path
from typing import Set, List, Dict, Optional, Any
import requests
from urllib.parse import quote
import time
import dotenv
from concurrent.futures import ThreadPoolExecutor, as_completed
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

dotenv.load_dotenv()
project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.utils.analyze_dependencies import (
    ImportAnalyzer,
    StringImportExtractor,
    DependencyAnalyzer,
    RequirementsComparator
)
from src.config.constants import TableNames
from telemetry_wrapper import logger as log

try:
    from importlib.metadata import distributions, distribution, PackageNotFoundError
except ImportError:
    from importlib_metadata import distributions, distribution, PackageNotFoundError


class ToolCodeDependencyExtractor:
    """Extract and analyze dependencies from tool code snippets stored in database."""
    
    def __init__(self, db_config: dict, requirements_file: str):
        """Initialize the dependency extractor."""
        self.db_config = db_config
        self.requirements_file = Path(requirements_file)
        self._dependency_analyzer = DependencyAnalyzer(".")
        self.stdlib_modules = self._dependency_analyzer.stdlib_modules
        self.import_to_package_cache = {}
        self.pypi_cache = {}
        self.pypi_import_mapping_cache = {}
        self.requirements_comparator = RequirementsComparator(str(requirements_file))

        self.stats = {
            'total_tools': 0,
            'raw_imports': [],
            'after_stdlib_filter': [],
            'not_in_requirements': [],
            'after_llm_correction': [],
            'final_packages': []
        }
    
    @staticmethod
    def reset_cache():
        """Reset all caches."""
        DependencyAnalyzer.reset_cache()
    
    @property
    def distributions_cache(self):
        """Access DependencyAnalyzer's distribution cache."""
        return DependencyAnalyzer._distributions_cache
    
    @property
    def top_level_to_package_cache(self):
        """Access DependencyAnalyzer's top_level_to_package cache."""
        return DependencyAnalyzer._top_level_to_package_cache
    
    async def get_llm_model(self, model_name: str):
        """Initialize LLM using ModelService."""
        from src.api.dependencies import ServiceProvider
        model_service = ServiceProvider.get_model_service()
        return await model_service.get_llm_model(model_name=model_name, temperature=0.0) 
    
    def get_code_snippets_from_db(self) -> List[str]:
        """Retrieve tool code snippets from PostgreSQL database."""
        code_snippets = []
        connection = None
        cursor = None
        
        try:
            connection = psycopg2.connect(
                host=self.db_config['host'],
                database=self.db_config['database'],
                user=self.db_config['user'],
                password=self.db_config['password'],
                port=self.db_config['port']
            )
            cursor = connection.cursor()
            cursor.execute(f"SELECT code_snippet FROM {TableNames.TOOL.value};")
            records = cursor.fetchall()
            
            for row in records:
                if row[0]:
                    code_snippets.append(row[0])
                    
        except (Exception, psycopg2.Error) as error:
            log.error(f"Database error: {error}")
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
        
        return code_snippets
    
    def check_pypi_package_exists(self, package_name: str) -> bool:
        """Check if package exists on PyPI with caching."""
        if package_name in self.pypi_cache:
            return self.pypi_cache[package_name]
        
        normalized = self.requirements_comparator.normalize_package_name(package_name)
        if normalized in self.requirements_comparator.requirements:
            self.pypi_cache[package_name] = True
            return True
        
        pkg_lower = package_name.lower().replace('_', '-')
        if pkg_lower in self.distributions_cache:
            self.pypi_cache[package_name] = True
            return True
        
        try:
            url = f"https://pypi.org/pypi/{quote(package_name)}/json"
            response = requests.get(url, timeout=5)
            exists = response.status_code == 200
            self.pypi_cache[package_name] = exists
            return exists
        except Exception as e:
            self.pypi_cache[package_name] = False
            return False
    
    def batch_check_pypi_packages(self, package_names: List[str], max_workers: int = 20) -> Dict[str, bool]:
        """Check multiple packages on PyPI in parallel using thread pool."""
        results = {}
        packages_to_check = []
        
        for pkg in package_names:
            if pkg in self.pypi_cache:
                results[pkg] = self.pypi_cache[pkg]
            else:
                normalized = self.requirements_comparator.normalize_package_name(pkg)
                if normalized in self.requirements_comparator.requirements:
                    self.pypi_cache[pkg] = True
                    results[pkg] = True
                elif pkg.lower().replace('_', '-') in self.distributions_cache:
                    self.pypi_cache[pkg] = True
                    results[pkg] = True
                else:
                    packages_to_check.append(pkg)
        
        if not packages_to_check:
            return results
        
        def check_single_package(pkg_name: str) -> tuple:
            try:
                url = f"https://pypi.org/pypi/{quote(pkg_name)}/json"
                response = requests.get(url, timeout=5)
                exists = response.status_code == 200
                return (pkg_name, exists)
            except Exception:
                return (pkg_name, False)
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(check_single_package, pkg): pkg for pkg in packages_to_check}
            for future in as_completed(futures):
                pkg_name, exists = future.result()
                self.pypi_cache[pkg_name] = exists
                results[pkg_name] = exists
        
        return results
    
    def verify_package_provides_module(self, package_name: str, module_name: str) -> bool:
        """Verify that a PyPI package provides the specified module."""
        pkg_normalized = package_name.lower().replace('_', '-')
        if module_name in self.top_level_to_package_cache:
            cached_pkg = self.top_level_to_package_cache[module_name]
            if cached_pkg == pkg_normalized:
                return True
        if module_name.lower() in self.top_level_to_package_cache:
            cached_pkg = self.top_level_to_package_cache[module_name.lower()]
            if cached_pkg == pkg_normalized:
                return True
        
        if pkg_normalized in self.distributions_cache:
            dist = self.distributions_cache[pkg_normalized]
            try:
                top_level_txt = dist.read_text('top_level.txt')
                if top_level_txt:
                    top_level_modules = top_level_txt.split()
                    if module_name in top_level_modules:
                        return True
            except Exception:
                pass
        
        mod_normalized = module_name.lower().replace('-', '').replace('_', '')
        pkg_check = package_name.lower().replace('-', '').replace('_', '')
        if pkg_check == mod_normalized:
            return True
        
        try:
            dist = distribution(package_name)
            try:
                top_level_txt = dist.read_text('top_level.txt')
                if top_level_txt:
                    top_level_modules = top_level_txt.split()
                    return module_name in top_level_modules
            except (FileNotFoundError, KeyError, AttributeError):
                pass

            if dist.files:
                for file in dist.files:
                    file_str = str(file).replace('\\', '/')
                    if file_str == f'{module_name}/__init__.py' or file_str == f'{module_name}.py':
                        return True
        except PackageNotFoundError:
            pass
        except Exception:
            pass
        
        return False
    
    def find_pypi_package_for_import(self, import_name: str) -> Optional[str]:
        """Find the correct PyPI package name for an import."""
        if import_name in self.pypi_import_mapping_cache:
            return self.pypi_import_mapping_cache[import_name]
        
        top_level = import_name.split('.')[0]
        
        cached = self.lookup_in_cache(top_level)
        if cached:
            self.pypi_import_mapping_cache[import_name] = cached
            return cached
        
        req_pkg = self.lookup_in_requirements(top_level)
        if req_pkg:
            self.pypi_import_mapping_cache[import_name] = req_pkg
            return req_pkg
        
        if self.check_pypi_package_exists(top_level):
            self.pypi_import_mapping_cache[import_name] = top_level
            return top_level
        
        self.pypi_import_mapping_cache[import_name] = None
        return None
    
    def parse_single_code(self, code_string: str, idx: int) -> Set[str]:
        """Parse a single code snippet and return its imports."""
        imports = set()
        if not code_string or not code_string.strip():
            return imports
        try:
            tree = ast.parse(code_string, filename=f'<tool_code_{idx}>')
            analyzer = ImportAnalyzer(f'<tool_code_{idx}>')
            analyzer.visit(tree)
            imports.update(analyzer.imports)
            imports.update(analyzer.conditional_imports)
            imports.update(analyzer.dynamic_imports)
            imports.update(analyzer.indirect_imports)
            string_imports = StringImportExtractor.extract_from_content(code_string)
            imports.update(string_imports)
        except (SyntaxError, Exception):
            pass
        return imports
    
    def parse_tool_codes(self, code_snippets: List[str]) -> Set[str]:
        """Parse tool code snippets using AST to extract all imports in parallel."""
        all_imports = set()
        
        with ThreadPoolExecutor(max_workers=min(32, len(code_snippets) or 1)) as executor:
            futures = [executor.submit(self.parse_single_code, code, idx) 
                      for idx, code in enumerate(code_snippets)]
            for future in as_completed(futures):
                all_imports.update(future.result())
        
        return all_imports
    
    def validate_imports(self, raw_imports: Set[str]) -> Set[str]:
        """Validate imports to filter out user-defined modules and keep only real packages."""
        validated = set()
        needs_pypi_check = []
        skipped = []
        
        for imp in raw_imports:
            if not imp or not isinstance(imp, str):
                skipped.append((imp, "empty or invalid"))
                continue
            if imp.endswith(('.db', '.sqlite', '.sqlite3', '.py', '.pyw', '.txt', '.json', '.log')):
                skipped.append((imp, "file extension"))
                continue
            top_level = imp.split('.')[0]
            if top_level in self.stdlib_modules or imp in self.stdlib_modules:
                skipped.append((imp, "stdlib"))
                continue
            if len(top_level) < 2 or not top_level[0].isalpha() or top_level.startswith('_'):
                skipped.append((imp, "invalid format"))
                continue
            if self.is_generic_or_custom_module(top_level):
                skipped.append((imp, "generic/custom module"))
                continue
            
            if self.is_locally_known_package(top_level):
                validated.add(imp)
            else:
                needs_pypi_check.append((imp, top_level))
        
        if needs_pypi_check:
            unique_top_levels = list(set(tl for _, tl in needs_pypi_check))
            pypi_results = self.batch_check_pypi_packages(unique_top_levels)
            
            for imp, top_level in needs_pypi_check:
                if pypi_results.get(top_level, False):
                    validated.add(imp)
                    self.import_to_package_cache[top_level] = top_level
                else:
                    skipped.append((imp, "not a real package"))
        
        return validated
    
    def is_locally_known_package(self, top_level: str) -> bool:
        """Check if a package is known locally without HTTP calls."""
        if self.lookup_in_cache(top_level):
            return True
        if self.lookup_in_requirements(top_level):
            return True
        if self.lookup_local_distribution(top_level):
            return True
        return False
    
    def is_generic_or_custom_module(self, name: str) -> bool:
        """Check if a module name is generic or project-specific."""
        name_lower = name.lower()
        generic_names = {
            'agents', 'tools', 'database', 'databases', 'db', 'drivers', 'driver',
            'mailer', 'utils', 'helpers', 'services', 'models', 'views', 'controllers',
            'app', 'src', 'lib', 'core', 'config', 'settings', 'api', 'cli',
            'sql', 'sqli', 'sqlite', 'mongodb', 'postgres', 'postgresql',
            'github_utils', 'jiraconnector', 'jira_connector',
            'final_sql', 'monitor_processes', 'sql_injection'
        }
        
        if name_lower in generic_names:
            return True
        if '_' in name_lower:
            custom_patterns = ['_utils', '_helper', '_connector', '_client', '_manager',
                             '_service', '_handler', '_driver', '_agent', '_tool']
            if any(pattern in name_lower for pattern in custom_patterns):
                return True
            
            if any(name_lower.endswith(pattern) for pattern in custom_patterns):
                return True
        
        return False
    
    def lookup_in_cache(self, top_level: str) -> Optional[str]:
        """Unified cache lookup for package name resolution."""
        if top_level in self.import_to_package_cache:
            return self.import_to_package_cache[top_level]
        
        if top_level in self.top_level_to_package_cache:
            pkg_name = self.top_level_to_package_cache[top_level]
            self.import_to_package_cache[top_level] = pkg_name
            return pkg_name
        
        top_lower = top_level.lower()
        if top_lower in self.top_level_to_package_cache:
            pkg_name = self.top_level_to_package_cache[top_lower]
            self.import_to_package_cache[top_level] = pkg_name
            return pkg_name
        
        if top_level in self.pypi_import_mapping_cache and self.pypi_import_mapping_cache[top_level]:
            return self.pypi_import_mapping_cache[top_level]
        
        alt_names = [
            top_level.replace('_', '-'),
            top_lower.replace('_', '-'),
            top_level.replace('-', '_'),
            top_lower.replace('-', '_')
        ]
        for alt_name in alt_names:
            if alt_name in self.top_level_to_package_cache:
                pkg_name = self.top_level_to_package_cache[alt_name]
                self.import_to_package_cache[top_level] = pkg_name
                return pkg_name
        
        return None
    
    def lookup_in_requirements(self, top_level: str) -> Optional[str]:
        """Check if package exists in requirements.txt."""
        normalized = self.requirements_comparator.normalize_package_name(top_level)
        if normalized in self.requirements_comparator.requirements:
            self.import_to_package_cache[top_level] = normalized
            return normalized
        
        top_lower = top_level.lower()
        variations = [
            top_level.replace('_', '-'),
            top_lower.replace('_', '-'),
        ]
        for variant in variations:
            normalized_var = self.requirements_comparator.normalize_package_name(variant)
            if normalized_var in self.requirements_comparator.requirements:
                self.import_to_package_cache[top_level] = normalized_var
                return normalized_var
        
        for req_name in self.requirements_comparator.requirements.keys():
            req_lower = req_name.lower()
            if req_lower == top_lower:
                self.import_to_package_cache[top_level] = req_name
                return req_name
            if top_lower in req_lower or req_lower in top_lower:
                if req_lower.startswith(top_lower) or req_lower.endswith(top_lower):
                    self.import_to_package_cache[top_level] = req_name
                    return req_name
                if '-' + top_lower in req_lower or top_lower + '-' in req_lower:
                    self.import_to_package_cache[top_level] = req_name
                    return req_name
        
        return None
    
    def lookup_local_distribution(self, top_level: str) -> Optional[str]:
        """Check if package is locally installed via importlib."""
        try:
            dist = distribution(top_level)
            self.import_to_package_cache[top_level] = dist.name
            return dist.name
        except PackageNotFoundError:
            pass
        except Exception:
            pass
        return None

    def map_import_to_package(self, import_name: str) -> str:
        """Map an import name to its corresponding package name."""
        top_level = import_name.split('.')[0]
        
        cached = self.lookup_in_cache(top_level)
        if cached:
            return cached
        
        req_pkg = self.lookup_in_requirements(top_level)
        if req_pkg:
            return req_pkg
        
        local_pkg = self.lookup_local_distribution(top_level)
        if local_pkg:
            return local_pkg
        
        pypi_package = self.find_pypi_package_for_import(top_level)
        if pypi_package:
            return pypi_package
        
        return top_level
    
    def match_with_requirements(self, validated_imports: Set[str]) -> Dict[str, Dict[str, str]]:
        """Match validated imports with requirements.txt."""
        matched_packages = {}
        new_packages = {}
        import_to_package_map = {}
        
        for import_name in validated_imports:
            package_name = self.map_import_to_package(import_name)
            import_to_package_map[import_name] = package_name
        
        optimized_requirements = self.requirements_comparator.generate_optimized_requirements(
            validated_imports,
            import_to_package_map
        )
        
        import re
        for req_line in optimized_requirements:
            match = re.match(r'^([a-zA-Z0-9_.-]+)(.*?)$', req_line)
            if match:
                package_name = match.group(1)
                version_spec = match.group(2).strip()
                if self.check_pypi_package_exists(package_name):
                    matched_packages[package_name] = version_spec
        
        
        matched_pkg_names_lower = {self.requirements_comparator.normalize_package_name(pkg) 
                                    for pkg in matched_packages.keys()}
        
        for import_name in validated_imports:
            pkg_name = import_to_package_map[import_name]
            normalized = self.requirements_comparator.normalize_package_name(pkg_name)

            if normalized not in matched_pkg_names_lower:
                if self.check_pypi_package_exists(pkg_name):
                    top_level_import = import_name.split('.')[0]
                    if self.verify_package_provides_module(pkg_name, top_level_import):
                        new_packages[pkg_name] = ""
        
        return {
            'matched': matched_packages,
            'new': new_packages
        }
    
    async def correct_package_names_with_llm(self, package_names: List[str], model_name: str) -> List[str]:
        """Use LLM to correct package names from import names to PyPI package names."""
        try:
            llm = await self.get_llm_model(model_name)
            prompt_template = ChatPromptTemplate.from_messages([
                ("system",
                """You are an expert in Python packages. Map import module names to PyPI package names.

                Examples:
                - sklearn → scikit-learn
                - cv2 → opencv-python
                - PIL → Pillow
                - yaml → PyYAML
                - bs4 → beautifulsoup4

                Return ONLY a JSON array of corrected names in the same order.
                No markdown, code blocks, or extra text.
                
                Example output: ["scikit-learn", "opencv-python", "requests"]
                """),
                ("human", "Convert these module names:\n{modules}")
            ])
            
            chain = prompt_template | llm | StrOutputParser()
            response = await chain.ainvoke({"modules": json.dumps(package_names)})
            response_clean = response.strip()
            if response_clean.startswith("```"):
                lines = [l for l in response_clean.split("\n") if not l.startswith("```")]
                response_clean = "\n".join(lines)
            
            corrected_names = json.loads(response_clean)
            
            if not isinstance(corrected_names, list) or len(corrected_names) != len(package_names):
                log.warning("Warning: LLM returned invalid response format, using original names")
                return package_names
            
            return corrected_names
            
        except Exception as e:
            log.warning(f"Warning: LLM correction failed: {e}")
            return package_names
        
    def format_package_list_display(self, packages, max_display=3, use_parentheses=True):
        """Format package list for display output."""
        if not packages:
            return ""
        pkg_list = sorted(list(packages)[:max_display])
        ellipsis = '...' if len(packages) > max_display else ''
        formatted = f"{', '.join(pkg_list)}{ellipsis}"
        return f" ({formatted})" if use_parentheses else formatted
    
    def run_sync(self, model_name: str = None) -> List[str]:
        """Synchronous version of the dependency analysis workflow."""
        if model_name is None:
            try:
                from src.api.dependencies import ServiceProvider
                model_service = ServiceProvider.get_model_service()
                model_name = model_service.available_models[0] if model_service.available_models else None
            except Exception:
                model_name = None
        
        code_snippets = self.get_code_snippets_from_db()
        self.stats['total_tools'] = len(code_snippets)
        log.info(f"Retrieved code from {self.stats['total_tools']} tools")
        
        if not code_snippets:
            log.info("No code snippets found in database")
            return []

        raw_imports = self.parse_tool_codes(code_snippets)
        self.stats['raw_imports'] = sorted(raw_imports)
        log.info(f"Extracted {len(raw_imports)} raw imports: {self.format_package_list_display(raw_imports, max_display=5, use_parentheses=False)}{'...' if len(raw_imports) > 5 else ''}")

        if not raw_imports:
            log.info("No imports found in code snippets")
            return []

        validated_imports = self.validate_imports(raw_imports)
        self.stats['after_stdlib_filter'] = sorted(validated_imports)
        filtered_count = len(raw_imports) - len(validated_imports)
        log.info(f"After filtering: {len(validated_imports)} third-party imports: {self.format_package_list_display(validated_imports, max_display=5, use_parentheses=False)}{'...' if len(validated_imports) > 5 else ''} (filtered out {filtered_count} stdlib/user modules)")
        
        if not validated_imports:
            log.info("No third-party imports found after filtering")
            return []
        
        package_names = list(set([self.map_import_to_package(imp) for imp in validated_imports]))
        log.info(f"Mapped to {len(package_names)} unique packages: {', '.join(sorted(package_names[:5]))}{'...' if len(package_names) > 5 else ''}")
        
        if model_name:
            try:
                loop = asyncio.new_event_loop()
                try:
                    corrected_packages = loop.run_until_complete(self.correct_package_names_with_llm(package_names, model_name))
                finally:
                    loop.close()
                corrections_made = []
                for orig, corrected in zip(package_names, corrected_packages):
                    if orig != corrected:
                        corrections_made.append(f"{orig} -> {corrected}")
                
                if corrections_made:
                    log.info(f"LLM corrected {len(corrections_made)} package names")
                
                package_names_corrected = corrected_packages
            except Exception as e:
                log.warning(f"Warning: LLM correction failed, using original names: {e}")
                package_names_corrected = package_names
        else:
            log.info("No model available, skipping LLM correction")
            package_names_corrected = package_names

        packages_in_requirements = set()
        packages_not_in_requirements = []
        
        for pkg in package_names_corrected:
            normalized = self.requirements_comparator.normalize_package_name(pkg)
            if normalized in self.requirements_comparator.requirements:
                packages_in_requirements.add(pkg)
            else:
                packages_not_in_requirements.append(pkg)
        
        log.info(f"Requirements check: {len(packages_in_requirements)} already in requirements.txt{self.format_package_list_display(packages_in_requirements)}, {len(packages_not_in_requirements)} missing{self.format_package_list_display(packages_not_in_requirements)}")
        packages_installed_not_in_req = set()
        packages_need_installation = []
        
        try:
            local_packages = set(self.distributions_cache.keys())
            
            for pkg in packages_not_in_requirements:
                pkg_lower = pkg.lower().replace('_', '-')
                if pkg_lower in local_packages:
                    packages_installed_not_in_req.add(pkg)
                else:
                    packages_need_installation.append(pkg)
            
            log.info(f"Local check: {len(packages_installed_not_in_req)} already installed{self.format_package_list_display(packages_installed_not_in_req)}, {len(packages_need_installation)} need installation{self.format_package_list_display(packages_need_installation)}")
            
        except Exception as e:
            log.warning(f"Warning: Could not check local packages, assuming all need installation")
            packages_installed_not_in_req = set()
            packages_need_installation = packages_not_in_requirements

        self.stats['not_in_requirements'] = sorted(packages_need_installation)
        self.stats['installed_not_in_requirements'] = sorted(packages_installed_not_in_req)
        self.stats['after_llm_correction'] = sorted(packages_need_installation)
        self.stats['final_packages'] = sorted(packages_need_installation)
        
        if not packages_need_installation:
            log.info("\nAll required packages are already available!")
    
        return packages_need_installation

    async def run(self, model_name: str = None) -> List[str]:
        """Execute the complete dependency analysis workflow."""
        return await asyncio.to_thread(self.run_sync, model_name)