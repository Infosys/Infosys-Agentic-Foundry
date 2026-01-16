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

try:
    from importlib.metadata import distributions, distribution, PackageNotFoundError
except ImportError:
    from importlib_metadata import distributions, distribution, PackageNotFoundError


class ToolCodeDependencyExtractor:
    """
    Extract and analyze dependencies from tool code snippets stored in database.
    
    This class connects to a database to retrieve tool code snippets, analyzes their
    import statements, validates them against PyPI and remote VM environments, and
    identifies missing packages that need installation.
    """
    
    def __init__(self, db_config: dict, requirements_file: str):
        """
        Initialize the dependency extractor.
        """
        self.db_config = db_config
        self.requirements_file = Path(requirements_file)
        temp_analyzer = DependencyAnalyzer(".")
        self.stdlib_modules = temp_analyzer.stdlib_modules
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
    
    async def _get_llm_model(self, model_name: str):
        """Initialize LLM using ModelService."""
        from src.api.dependencies import ServiceProvider
        model_service = ServiceProvider.get_model_service()
        return await model_service.get_llm_model(model_name=model_name, temperature=0.0) 
    
    def get_code_snippets_from_db(self) -> List[str]:
        """
        Retrieve tool code snippets from PostgreSQL database.
        """
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
            cursor.execute("SELECT code_snippet FROM tool_table;")
            records = cursor.fetchall()
            
            for row in records:
                if row[0]:
                    code_snippets.append(row[0])
                    
        except (Exception, psycopg2.Error) as error:
            print(f"Database error: {error}")
        finally:
            if cursor:
                cursor.close()
            if connection:
                connection.close()
        
        return code_snippets
    
    def _check_pypi_package_exists(self, package_name: str) -> bool:
        """
        Check if package exists on PyPI using JSON API.
        """
        if package_name in self.pypi_cache:
            return self.pypi_cache[package_name]
        
        try:
            url = f"https://pypi.org/pypi/{quote(package_name)}/json"
            response = requests.get(url, timeout=5)
            exists = response.status_code == 200
            self.pypi_cache[package_name] = exists
            time.sleep(0.05)
            return exists
        except Exception as e:
            return False
    
    def _verify_package_provides_module(self, package_name: str, module_name: str) -> bool:
        """Verify that a PyPI package actually provides the specified module."""
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
        
        pkg_normalized = package_name.lower().replace('-', '').replace('_', '')
        mod_normalized = module_name.lower().replace('-', '').replace('_', '')
        
        if pkg_normalized == mod_normalized:
            return True
        
        try:
            req_dist = distribution(package_name)
            top_level_txt = req_dist.read_text('top_level.txt')
            if top_level_txt and module_name in top_level_txt.split():
                return True
        except Exception:
            pass
        
        return False
    
    def _find_pypi_package_for_import(self, import_name: str) -> Optional[str]:
        """
        find the correct PyPI package name for an import.
        """
        if import_name in self.pypi_import_mapping_cache:
            return self.pypi_import_mapping_cache[import_name]
        
        top_level = import_name.split('.')[0]
        if self._check_pypi_package_exists(top_level):
            if self._verify_package_provides_module(top_level, top_level):
                self.pypi_import_mapping_cache[import_name] = top_level
                return top_level
        
        variations = [
            top_level.replace('_', '-'),
            f"python-{top_level}",
            f"{top_level}-python",  
        ]
        
        if top_level.isalpha() and len(top_level) <= 4:
            variations.extend([
                f"py{top_level}", 
                f"{top_level}lib",  
            ])
        
        for variant in variations:
            if self._check_pypi_package_exists(variant):
                if self._verify_package_provides_module(variant, top_level):
                    self.pypi_import_mapping_cache[import_name] = variant
                    return variant
        try:
            for dist in distributions():
                try:
                    top_level_txt = dist.read_text('top_level.txt')
                    if top_level_txt:
                        top_level_modules = top_level_txt.split()
                        if top_level in top_level_modules:
                            pkg_name = dist.name
                            # Verify this package exists on PyPI
                            if self._check_pypi_package_exists(pkg_name):
                                self.pypi_import_mapping_cache[import_name] = pkg_name
                                return pkg_name
                except (FileNotFoundError, KeyError, AttributeError):
                    continue
        except Exception:
            pass
        
        req_lower = top_level.lower()
        for req_name in self.requirements_comparator.requirements.keys():
            req_name_lower = req_name.lower()
            if req_lower in req_name_lower or req_name_lower in req_lower:
                if self._check_pypi_package_exists(req_name):
                    if self._verify_package_provides_module(req_name, top_level):
                        self.pypi_import_mapping_cache[import_name] = req_name
                        return req_name
        self.pypi_import_mapping_cache[import_name] = None
        return None
    
    def parse_tool_codes(self, code_snippets: List[str]) -> Set[str]:
        """
        Parse tool code snippets using AST to extract all imports.
        """
        all_imports = set()
        for idx, code_string in enumerate(code_snippets):
            if not code_string or not code_string.strip():
                continue
            try:
                tree = ast.parse(code_string, filename=f'<tool_code_{idx}>')
                analyzer = ImportAnalyzer(f'<tool_code_{idx}>')
                analyzer.visit(tree)
                all_imports.update(analyzer.imports)
                all_imports.update(analyzer.conditional_imports)
                all_imports.update(analyzer.dynamic_imports)
                all_imports.update(analyzer.indirect_imports)
                string_imports = StringImportExtractor.extract_from_content(code_string)
                all_imports.update(string_imports)
            except (SyntaxError, Exception):
                continue
        
        return all_imports
    
    def validate_imports(self, raw_imports: Set[str]) -> Set[str]:
        """
        Validate imports to filter out user-defined modules and keep only real packages.
        """
        validated = set()
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
            if not self._is_valid_import_name(top_level):
                skipped.append((imp, "invalid format"))
                continue
            if self._is_generic_or_custom_module(top_level):
                skipped.append((imp, "generic/custom module"))
                continue
            if self._is_real_package(top_level, imp):
                validated.add(imp)
            else:
                skipped.append((imp, "not a real package"))
        
        return validated
    
    def _is_generic_or_custom_module(self, name: str) -> bool:
        """
        Check if a module name is obviously generic, project-specific, or custom.
        Returns True for names that are likely NOT real PyPI packages.
        """
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
    
    def _is_valid_import_name(self, name: str) -> bool:
        """Validate import name format."""
        if len(name) < 2:
            return False
        if not name[0].isalpha():
            return False
        if name.startswith('_'):
            return False
        return True
    
    def _is_real_package(self, top_level: str, full_import: str) -> bool:
        """
        Check if an import is a real installable package.
        """
        if top_level in self.import_to_package_cache:
            return True
        try:
            dist = distribution(top_level)
            if self._check_pypi_package_exists(dist.name):
                if self._verify_package_provides_module(dist.name, top_level):
                    self.import_to_package_cache[top_level] = dist.name
                    return True
        except PackageNotFoundError:
            pass
        except Exception:
            pass
        
        normalized = self.requirements_comparator.normalize_package_name(top_level)
        if normalized in self.requirements_comparator.requirements:
            for req_name in self.requirements_comparator.requirements.keys():
                if self.requirements_comparator.normalize_package_name(req_name) == normalized:
                    if self._check_pypi_package_exists(req_name):
                        if self._verify_package_provides_module(req_name, top_level):
                            self.import_to_package_cache[top_level] = req_name
                            return True
        
        alt_names = [
            top_level.replace('_', '-'),
            top_level.lower(),
            top_level.lower().replace('_', '-')
        ]
        
        for alt_name in alt_names:
            normalized_alt = self.requirements_comparator.normalize_package_name(alt_name)
            if normalized_alt in self.requirements_comparator.requirements:
                for req_name in self.requirements_comparator.requirements.keys():
                    if self.requirements_comparator.normalize_package_name(req_name) == normalized_alt:
                        if self._check_pypi_package_exists(req_name):
                            if self._verify_package_provides_module(req_name, top_level):
                                self.import_to_package_cache[top_level] = req_name
                                return True
        try:
            for dist in distributions():
                try:
                    top_level_txt = dist.read_text('top_level.txt')
                    if top_level_txt:
                        top_level_modules = top_level_txt.split()
                        if top_level in top_level_modules:
                            if self._check_pypi_package_exists(dist.name):
                                self.import_to_package_cache[top_level] = dist.name
                                return True
                except (FileNotFoundError, KeyError, AttributeError):
                    continue
                except Exception:
                    continue
        except Exception:
            pass
        
        pypi_package = self._find_pypi_package_for_import(top_level)
        if pypi_package:
            self.import_to_package_cache[top_level] = pypi_package
            return True
        return False
    
    def map_import_to_package(self, import_name: str) -> str:
        """
        Map an import name to its corresponding package name.
        """
        top_level = import_name.split('.')[0]
        if top_level in self.import_to_package_cache:
            return self.import_to_package_cache[top_level]
        
        if top_level in self.pypi_import_mapping_cache and self.pypi_import_mapping_cache[top_level]:
            return self.pypi_import_mapping_cache[top_level]
        try:
            for dist in distributions():
                try:
                    top_level_txt = dist.read_text('top_level.txt')
                    if top_level_txt:
                        top_level_modules = top_level_txt.split()
                        if top_level in top_level_modules:
                            pkg_name = dist.name
                            # Verify on PyPI
                            if self._check_pypi_package_exists(pkg_name):
                                self.import_to_package_cache[top_level] = pkg_name
                                return pkg_name
                except (FileNotFoundError, KeyError, AttributeError, TypeError):
                    pass
                except Exception:
                    pass
        except Exception:
            pass
        try:
            for req_name in self.requirements_comparator.requirements.keys():
                try:
                    dist = distribution(req_name)
                    top_level_txt = dist.read_text('top_level.txt')
                    if top_level_txt:
                        top_level_modules = top_level_txt.split()
                        if top_level in top_level_modules:
                            if self._check_pypi_package_exists(req_name):
                                self.import_to_package_cache[top_level] = req_name
                                return req_name
                except (PackageNotFoundError, FileNotFoundError, KeyError, AttributeError):
                    continue
                except Exception:
                    continue
        except Exception:
            pass

        for req_name in self.requirements_comparator.requirements.keys():
            req_lower = req_name.lower()
            import_lower = top_level.lower()
            if req_lower == import_lower:
                if self._check_pypi_package_exists(req_name):
                    if self._verify_package_provides_module(req_name, top_level):
                        self.import_to_package_cache[top_level] = req_name
                        return req_name
            if import_lower in req_lower or req_lower in import_lower:
                if req_lower.startswith(import_lower) or req_lower.endswith(import_lower):
                    if self._check_pypi_package_exists(req_name):
                        if self._verify_package_provides_module(req_name, top_level):
                            self.import_to_package_cache[top_level] = req_name
                            return req_name
                if '-' + import_lower in req_lower or import_lower + '-' in req_lower:
                    if self._check_pypi_package_exists(req_name):
                        if self._verify_package_provides_module(req_name, top_level):
                            self.import_to_package_cache[top_level] = req_name
                            return req_name
        
        try:
            for dist in distributions():
                try:
                    if dist.files:
                        for file in dist.files:
                            file_str = str(file).replace('\\', '/')
                            if file_str == f'{top_level}/__init__.py':
                                pkg_name = dist.name
                                # Verify on PyPI
                                if self._check_pypi_package_exists(pkg_name):
                                    self.import_to_package_cache[top_level] = pkg_name
                                    return pkg_name
                except (AttributeError, TypeError):
                    pass
                except Exception:
                    pass
        except Exception:
            pass
        
        pypi_package = self._find_pypi_package_for_import(top_level)
        if pypi_package:
            return pypi_package
        
        return top_level
    
    def match_with_requirements(self, validated_imports: Set[str]) -> Dict[str, Dict[str, str]]:
        """
        Match validated imports with requirements_original.txt.
        """
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
                if self._check_pypi_package_exists(package_name):
                    matched_packages[package_name] = version_spec
        
        
        matched_pkg_names_lower = {self.requirements_comparator.normalize_package_name(pkg) 
                                    for pkg in matched_packages.keys()}
        
        for import_name in validated_imports:
            pkg_name = import_to_package_map[import_name]
            normalized = self.requirements_comparator.normalize_package_name(pkg_name)

            if normalized not in matched_pkg_names_lower:
                if self._check_pypi_package_exists(pkg_name):
                    top_level_import = import_name.split('.')[0]
                    if self._verify_package_provides_module(pkg_name, top_level_import):
                        new_packages[pkg_name] = ""
        
        return {
            'matched': matched_packages,
            'new': new_packages
        }
    
    async def _correct_package_names_with_llm(self, package_names: List[str], model_name: str) -> List[str]:
        """
        Use LLM to correct package names from import names to PyPI package names.
        """
        try:
            llm = await self._get_llm_model(model_name)
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
                print("Warning: LLM returned invalid response format, using original names")
                return package_names
            
            return corrected_names
            
        except Exception as e:
            print(f"Warning: LLM correction failed: {e}")
            return package_names
        
    def _format_package_list_display(self, packages, max_display=3, use_parentheses=True):
        if not packages:
            return ""
        pkg_list = sorted(list(packages)[:max_display])
        ellipsis = '...' if len(packages) > max_display else ''
        formatted = f"{', '.join(pkg_list)}{ellipsis}"
        return f" ({formatted})" if use_parentheses else formatted
    
    def _run_sync(self, model_name: str = None) -> List[str]:
        """
        Synchronous version of the dependency analysis workflow.
        Called by run() via asyncio.to_thread to avoid blocking the event loop.
        """
        
        if model_name is None:
            try:
                from src.api.dependencies import ServiceProvider
                model_service = ServiceProvider.get_model_service()
                model_name = model_service.available_models[0] if model_service.available_models else None
            except Exception:
                model_name = None
        
        code_snippets = self.get_code_snippets_from_db()
        self.stats['total_tools'] = len(code_snippets)
        print(f"Retrieved code from {self.stats['total_tools']} tools")
        
        if not code_snippets:
            print("No code snippets found in database")
            return []

        raw_imports = self.parse_tool_codes(code_snippets)
        self.stats['raw_imports'] = sorted(raw_imports)
        print(f"Extracted {len(raw_imports)} raw imports: {self._format_package_list_display(raw_imports, max_display=5, use_parentheses=False)}{'...' if len(raw_imports) > 5 else ''}")

        if not raw_imports:
            print("No imports found in code snippets")
            return []

        validated_imports = self.validate_imports(raw_imports)
        self.stats['after_stdlib_filter'] = sorted(validated_imports)
        filtered_count = len(raw_imports) - len(validated_imports)
        print(f"After filtering: {len(validated_imports)} third-party imports: {self._format_package_list_display(validated_imports, max_display=5, use_parentheses=False)}{'...' if len(validated_imports) > 5 else ''} (filtered out {filtered_count} stdlib/user modules)")
        
        if not validated_imports:
            print("No third-party imports found after filtering")
            return []
        
        package_names = list(set([self.map_import_to_package(imp) for imp in validated_imports]))
        print(f"Mapped to {len(package_names)} unique packages: {', '.join(sorted(package_names[:5]))}{'...' if len(package_names) > 5 else ''}")
        
        if model_name:
            try:
                loop = asyncio.new_event_loop()
                try:
                    corrected_packages = loop.run_until_complete(self._correct_package_names_with_llm(package_names, model_name))
                finally:
                    loop.close()
                corrections_made = []
                for orig, corrected in zip(package_names, corrected_packages):
                    if orig != corrected:
                        corrections_made.append(f"{orig} -> {corrected}")
                
                if corrections_made:
                    print(f"LLM corrected {len(corrections_made)} package names")
                
                package_names_corrected = corrected_packages
            except Exception as e:
                print(f"Warning: LLM correction failed, using original names: {e}")
                package_names_corrected = package_names
        else:
            print("No model available, skipping LLM correction")
            package_names_corrected = package_names

        packages_in_requirements = set()
        packages_not_in_requirements = []
        
        for pkg in package_names_corrected:
            normalized = self.requirements_comparator.normalize_package_name(pkg)
            if normalized in self.requirements_comparator.requirements:
                packages_in_requirements.add(pkg)
            else:
                packages_not_in_requirements.append(pkg)
        
        print(f"Requirements check: {len(packages_in_requirements)} already in requirements.txt{self._format_package_list_display(packages_in_requirements)}, {len(packages_not_in_requirements)} missing{self._format_package_list_display(packages_not_in_requirements)}")
        packages_installed_not_in_req = set()
        packages_need_installation = []
        
        try:
            local_packages = {dist.metadata['name'].lower() for dist in distributions()}
            
            for pkg in packages_not_in_requirements:
                pkg_lower = pkg.lower().replace('-', '_')
                if any(pkg_lower == local_pkg.replace('-', '_') or pkg.lower() == local_pkg 
                      for local_pkg in local_packages):
                    packages_installed_not_in_req.add(pkg)
                else:
                    packages_need_installation.append(pkg)
            
            print(f"Local check: {len(packages_installed_not_in_req)} already installed{self._format_package_list_display(packages_installed_not_in_req)}, {len(packages_need_installation)} need installation{self._format_package_list_display(packages_need_installation)}")
            
        except Exception as e:
            print(f"Warning: Could not check local packages, assuming all need installation")
            packages_installed_not_in_req = set()
            packages_need_installation = packages_not_in_requirements

        self.stats['not_in_requirements'] = sorted(packages_need_installation)
        self.stats['installed_not_in_requirements'] = sorted(packages_installed_not_in_req)
        self.stats['after_llm_correction'] = sorted(packages_need_installation)
        self.stats['final_packages'] = sorted(packages_need_installation)
        
        if not packages_need_installation:
            print("\nAll required packages are already available!")
    
        return packages_need_installation

    async def run(self, model_name: str = None) -> List[str]:
        """
        Execute the complete dependency analysis workflow.
        Returns:
            List of package names that need installation
        """
        return await asyncio.to_thread(self._run_sync, model_name)