import sys
import ast
from pathlib import Path
from typing import List, Dict, Set, Tuple
try:
    from importlib.metadata import distributions, distribution, PackageNotFoundError
except ImportError:
    # Fallback for Python < 3.8
    from importlib_metadata import distributions, distribution, PackageNotFoundError

parent_dir = Path(__file__).resolve().parent.parent
if str(parent_dir) not in sys.path:
    sys.path.insert(0, str(parent_dir))

from src.utils.analyze_dependencies import (
    DependencyAnalyzer,
    RequirementsComparator,
    ImportAnalyzer,
    StringImportExtractor
)

class ExportDependencyAnalyzer(DependencyAnalyzer):
    """
    Analyzes Export_Agent folder and tool code dependencies dynamically.
    """
    
    def __init__(self, export_agent_path: str, requirements_path: str, tool_code_strings: List[str] = None):
        super().__init__(export_agent_path, exclude_dirs=['__pycache__'])
        self.export_agent_path = Path(export_agent_path).resolve()
        self.requirements_path = Path(requirements_path).resolve()
        self.tool_code_strings = tool_code_strings or []
        self.requirements_comparator = None
        self.import_to_package_cache = {}  
    
    def map_import_to_package(self, import_name: str) -> str:
        """Map an import name to its corresponding package name."""
        top_level = import_name.split('.')[0]
        if top_level in self.import_to_package_cache:
            return self.import_to_package_cache[top_level]
        try:
            for dist in distributions():
                try:
                    if dist.read_text('top_level.txt'):
                        top_level_modules = dist.read_text('top_level.txt').split()
                        if top_level in top_level_modules:
                            pkg_name = dist.name
                            self.import_to_package_cache[top_level] = pkg_name
                            return pkg_name
                    
                    if dist.read_text('RECORD'):
                        record = dist.read_text('RECORD')
                        for line in record.split('\n')[:100]:
                            if line.startswith(f"{top_level}/"):
                                pkg_name = dist.name
                                self.import_to_package_cache[top_level] = pkg_name
                                return pkg_name
                except Exception:
                    continue
        except Exception:
            pass
        
        return top_level
    
    def _get_base_export_requirements(self) -> List[str]:
        """
        Dynamically analyze Export_Agent files to get base requirements.
        Scans all Export_Agent functionality files and extracts their dependencies.
        Also includes runtime dependencies that are required but not directly imported.
        
        Returns consistent base requirements for all export agents.
        """
        self.analyze_all_files()
        base_imports = self.get_all_unique_imports().copy()
        
        base_import_to_package = self._build_import_to_package_map(base_imports)
        
        base_requirements = self.requirements_comparator.generate_optimized_requirements(
            base_imports,
            base_import_to_package
        )
        
        base_packages = self._extract_package_names(base_requirements)
        
        runtime_deps = self._discover_runtime_dependencies(base_packages, base_imports)
        
        for pkg_name, version_spec in runtime_deps.items():
            req_line = f"{pkg_name}{version_spec}"
            if req_line not in base_requirements:
                base_requirements.append(req_line)
        
        return base_requirements
    
    def _discover_runtime_dependencies(self, base_packages: Set[str], base_imports: Set[str]) -> Dict[str, str]:
        """
        Discover runtime dependencies based on what's already imported.
        Dynamically finds related packages from requirements.txt by checking package name patterns.
        Handles package families and special keyword-based dependencies.
        
        Returns:
            Dict of {package_name: version_spec}
        """
        runtime_deps = {}
        
        all_available_packages = self.requirements_comparator.requirements
        detected_families = self._detect_package_families(base_packages)

        for family_root in detected_families:
            for available_pkg in all_available_packages:
                if available_pkg in base_packages or available_pkg in runtime_deps:
                    continue
                available_lower = available_pkg.lower()
                if available_lower.startswith(family_root + '-') or available_lower == family_root:
                    runtime_deps[available_pkg] = all_available_packages[available_pkg]
        keyword_mappings = self._get_keyword_package_mappings()

        for keyword, package_prefixes in keyword_mappings.items():
            if self._has_keyword_dependency(base_packages, base_imports, keyword):
                for available_pkg in all_available_packages:
                    if available_pkg in base_packages or available_pkg in runtime_deps:
                        continue
                    available_lower = available_pkg.lower()
                    if any(available_lower.startswith(prefix) for prefix in package_prefixes):
                        runtime_deps[available_pkg] = all_available_packages[available_pkg]
        
        for pkg in base_packages:
            pkg_lower = pkg.lower()
            
            for available_pkg in all_available_packages:
                if available_pkg in base_packages or available_pkg in runtime_deps:
                    continue
                available_lower = available_pkg.lower()
                
                if available_lower.startswith(pkg_lower + '-'):
                    runtime_deps[available_pkg] = all_available_packages[available_pkg]
                elif '-' in pkg_lower and '-' in available_lower:
                    pkg_root = pkg_lower.split('-')[0]
                    available_root = available_lower.split('-')[0]
                    if pkg_root == available_root and len(pkg_root) > 3:
                        runtime_deps[available_pkg] = all_available_packages[available_pkg]
        
        for imp in base_imports:
            imp_lower = imp.lower()
            imp_base = imp_lower.split('.')[0]
            
            for available_pkg in all_available_packages:
                if available_pkg in base_packages or available_pkg in runtime_deps:
                    continue
                    
                available_lower = available_pkg.lower()
                
                if available_lower.startswith(imp_base + '-'):
                    runtime_deps[available_pkg] = all_available_packages[available_pkg]
                elif imp_base in available_lower and len(imp_base) > 4:
                    runtime_deps[available_pkg] = all_available_packages[available_pkg]
        
        return runtime_deps
    
    def _detect_package_families(self, packages: Set[str]) -> Set[str]:
        """
        Detect package families by analyzing package name patterns.
        A family is detected when multiple related packages share a common prefix.
        
        Returns:
            Set of family root names (e.g., 'langgraph', 'opentelemetry')
        """
        families = set()
        all_available_packages = self.requirements_comparator.requirements
        
        for pkg in packages:
            pkg_lower = pkg.lower()
            parts = pkg_lower.split('-')
            
            if len(parts) > 1:
                base_name = parts[0]
                if len(base_name) > 3:
                    family_count = sum(
                        1 for avail_pkg in all_available_packages
                        if avail_pkg.lower().startswith(base_name + '-') or avail_pkg.lower() == base_name
                    )
                    if family_count > 1:
                        families.add(base_name)
        
        return families
    
    def _get_keyword_package_mappings(self) -> Dict[str, List[str]]:
        """
        Get keyword-to-package-prefix mappings for special dependencies.
        These handle cases where import names differ from package names.
        
        Returns:
            Dict mapping keywords to lists of package prefixes
        """
        return {
            'postgres': ['psycopg'],
            'mysql': ['mysql'],
        }
    
    def _has_keyword_dependency(self, packages: Set[str], imports: Set[str], keyword: str) -> bool:
        """
        Check if any package or import contains the given keyword.
        
        Returns:
            True if keyword is found in packages or imports
        """
        keyword_lower = keyword.lower()
        
        for pkg in packages:
            if keyword_lower in pkg.lower():
                return True
        
        for imp in imports:
            if keyword_lower in imp.lower():
                return True
        
        return False
        
    def find_python_files(self) -> List[Path]:
        """
        Find all Python files for Export_Agent functionality.
        Includes the complete export agent runtime framework.
        """
        python_files = []
        project_root = self.export_agent_path.parent
        
        for py_file in self.export_agent_path.rglob('*.py'):
            if '__pycache__' not in py_file.parts:
                python_files.append(py_file)
        
        shared_files = ['telemetry_wrapper.py', 'groundtruth.py', 'MultiDBConnection_Manager.py']
        for shared_file in shared_files:
            shared_path = project_root / shared_file
            if shared_path.exists():
                python_files.append(shared_path)
        
        src_path = project_root / 'src'
        if src_path.exists():
            exclude_folders = {'__pycache__', 'api', 'agent_templates'}
            for py_file in src_path.rglob('*.py'):
                if not any(excluded in py_file.parts for excluded in exclude_folders):
                    python_files.append(py_file)
        
        return python_files
    
    def analyze_tool_codes(self) -> None:
        """Analyze tool code strings for imports using AST parsing."""
        if not self.tool_code_strings:
            return
        if not self.requirements_comparator:
            self.requirements_comparator = RequirementsComparator(str(self.requirements_path))
        
        print(f"\n[Export Agent] Analyzing {len(self.tool_code_strings)} tool code(s) for dependencies...")
        
        tool_imports = set()
        
        for idx, code_string in enumerate(self.tool_code_strings):
            try:
                tree = ast.parse(code_string, filename=f'<tool_code_{idx}>')
                analyzer = ImportAnalyzer(f'<tool_code_{idx}>')
                analyzer.visit(tree)
                
                tool_imports.update(analyzer.imports)
                tool_imports.update(analyzer.conditional_imports)
                tool_imports.update(analyzer.dynamic_imports)
                tool_imports.update(analyzer.indirect_imports)
                
                string_imports = StringImportExtractor.extract_from_content(code_string)
                tool_imports.update(string_imports)
                
            except Exception as e:
                print(f"[Export Agent] Warning: Could not parse tool code {idx}: {e}")
                continue
        
        if tool_imports:
            print(f"[Export Agent] Raw imports from tool codes: {sorted(tool_imports)}")
        
        validated_tool_imports = self._validate_tool_imports(tool_imports)
        
        if validated_tool_imports:
            print(f"[Export Agent] Validated tool imports: {sorted(validated_tool_imports)}")
            self.all_imports['direct'].update(validated_tool_imports)
            self.validated_tool_imports = validated_tool_imports
            self._tool_imports_logged = True
        else:
            print("[Export Agent] No validated tool imports after filtering")
            self.validated_tool_imports = set()
    
    def _validate_tool_imports(self, tool_imports: Set[str]) -> Set[str]:
        """
        Validate tool imports to exclude user-defined modules and ensure they are real packages.
        """
        validated = set()
        skipped = []
        
        for imp in tool_imports:
            if not imp or not isinstance(imp, str):
                skipped.append((imp, "empty or invalid"))
                continue
            
            top_level = imp.split('.')[0]
            
            if top_level in self.stdlib_modules or imp in self.stdlib_modules:
                skipped.append((imp, "stdlib"))
                continue
            
            if not self._is_valid_import_name(top_level):
                skipped.append((imp, "invalid format"))
                continue
            
            is_real = self._is_real_package(top_level, imp)
            if is_real:
                validated.add(imp)
            else:
                if self._is_package_installable(top_level):
                    skipped.append((imp, "not installed"))
                else:
                    skipped.append((imp, "not a real package"))
        
        if skipped:
            print(f"[Export Agent] Skipped imports: {skipped[:5]}...")
        
        return validated
    
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
        Check if an import is a real installable package (not user-defined).
        Dynamically discovers mappings from requirements.txt and installed packages.
        """
        if not self.requirements_comparator:
            return False
        
        try:
            dist = distribution(top_level)
            pkg_name = self.requirements_comparator.normalize_package_name(dist.name)
            self.import_to_package_cache[top_level] = pkg_name
            return True
        except PackageNotFoundError:
            pass
        except Exception:
            pass
        
        normalized = self.requirements_comparator.normalize_package_name(top_level)
        if normalized in self.requirements_comparator.requirements:
            return True
        
        alt_names = [
            top_level.replace('_', '-'),
            top_level.lower(),
            top_level.lower().replace('_', '-')
        ]
        
        for alt_name in alt_names:
            normalized_alt = self.requirements_comparator.normalize_package_name(alt_name)
            if normalized_alt in self.requirements_comparator.requirements:
                return True
        
        try:
            for dist in distributions():
                try:
                    if dist.read_text('top_level.txt'):
                        top_level_modules = dist.read_text('top_level.txt').split()
                        if top_level in top_level_modules:
                            pkg_name = self.requirements_comparator.normalize_package_name(dist.name)
                            self.import_to_package_cache[top_level] = pkg_name
                            return True
                    
                    if dist.read_text('RECORD'):
                        record = dist.read_text('RECORD')
                        top_level_dirs = set()
                        for line in record.split('\n'):
                            if line.strip() and not line.startswith(dist.name.replace('-', '_')):
                                parts = line.split('/')
                                if len(parts) > 0 and not parts[0].endswith('.dist-info'):
                                    first_part = parts[0].split(',')[0]
                                    if first_part and not first_part.startswith('.') and first_part[0].isalpha():
                                        top_level_dirs.add(first_part)
                        
                        if top_level in top_level_dirs:
                            pkg_name = self.requirements_comparator.normalize_package_name(dist.name)
                            self.import_to_package_cache[top_level] = pkg_name
                            return True
                except Exception:
                    continue
        except Exception:
            pass
        
        if top_level in self.import_to_package_cache:
            return True
        
        try:
            mapped_package = self.map_import_to_package(top_level)
            if mapped_package and mapped_package != top_level:
                normalized_mapped = self.requirements_comparator.normalize_package_name(mapped_package)
                if normalized_mapped in self.requirements_comparator.requirements:
                    self.import_to_package_cache[top_level] = normalized_mapped
                    return True
                try:
                    distribution(mapped_package)
                    self.import_to_package_cache[top_level] = normalized_mapped
                    return True
                except PackageNotFoundError:
                    pass
        except Exception:
            pass
        
        return False
    
    def _is_package_installable(self, package_name: str) -> bool:
        if not package_name.isidentifier():
            return False
        if len(package_name) < 2:
            return False
        try:
            exec(f"import {package_name}")
            return False 
        except ModuleNotFoundError:
            return True
        except Exception:
            return False
    
    def generate_requirements(self) -> List[str]:
        """
        Generate requirements: Base export agent dependencies + tool-specific dependencies.
        """
        print("[Export Agent] Analyzing dependencies for export agent functionality...")
        
        self.requirements_comparator = RequirementsComparator(str(self.requirements_path))
        
        print("[Export Agent] Analyzing base export agent dependencies...")
        base_requirements = self._get_base_export_requirements()
        base_packages = self._extract_package_names(base_requirements)
        base_imports = self.get_all_unique_imports().copy()
        print(f"[Export Agent] Base export agent dependencies: {len(base_packages)} packages")
        
        if self.tool_code_strings:
            if not hasattr(self, 'validated_tool_imports'):
                self.analyze_tool_codes()
            
            if hasattr(self, 'validated_tool_imports') and self.validated_tool_imports:
                tool_imports = self.validated_tool_imports
                if not hasattr(self, '_tool_imports_logged'):
                    print(f"[Export Agent] Validated tool imports: {sorted(tool_imports)}")
                    self._tool_imports_logged = True
                
                tool_import_to_package = self._build_import_to_package_map(tool_imports)
                
                tool_packages_in_base = set()
                for imp in tool_imports:
                    pkg_name = tool_import_to_package.get(imp, imp)
                    normalized = self.requirements_comparator.normalize_package_name(pkg_name)
                    if normalized in base_packages:
                        tool_packages_in_base.add(normalized)
                
                if tool_packages_in_base:
                    print(f"[Export Agent] Tool packages already in base: {sorted(tool_packages_in_base)}")
                
                tool_requirements_from_base = self.requirements_comparator.generate_optimized_requirements(
                    tool_imports,
                    tool_import_to_package
                )
                
                tool_packages = self._extract_package_names(tool_requirements_from_base)
                new_tool_packages = tool_packages - base_packages
                
                if new_tool_packages:
                    print(f"[Export Agent] New tool packages from requirements.txt: {len(new_tool_packages)}")
                    for pkg in sorted(new_tool_packages):
                        if pkg in self.requirements_comparator.requirements:
                            req_line = f"{pkg}{self.requirements_comparator.requirements[pkg]}"
                            if req_line not in base_requirements:
                                base_requirements.append(req_line)
                                print(f"  + {req_line}")
                
                new_dependencies = self._discover_new_dependencies(
                    tool_imports, 
                    tool_import_to_package, 
                    base_packages
                )
                
                if new_dependencies:
                    print(f"[Export Agent] New tool packages from installed environment: {len(new_dependencies)}")
                    for pkg_name, version in sorted(new_dependencies.items()):
                        req_line = f"{pkg_name}{version}"
                        base_requirements.append(req_line)
                        print(f"  + {req_line}")
                
                if not new_tool_packages and not new_dependencies:
                    print("[Export Agent] No additional tool-specific dependencies needed (all covered by base)")
            else:
                print("[Export Agent] No validated tool imports detected")
        else:
            print("[Export Agent] No tool codes provided for analysis")
        
        sqlean_package = "sqlean.py==3.49.1"
        if sqlean_package not in base_requirements:
            base_requirements.append(sqlean_package)
        
        final_requirements = sorted(list(set(base_requirements)))
        
        default_packages = {'sqlean.py'}
        tool_specific_count = 0
        for req in final_requirements:
            pkg_name = req.split('==')[0].split('>=')[0].split('<=')[0].split('~=')[0].split('!=')[0]
            if pkg_name not in base_packages and pkg_name not in default_packages:
                tool_specific_count += 1
        
        print(f"\n[Export Agent] Total dependencies: {len(final_requirements)} packages")
        if tool_specific_count > 0:
            print(f"    (Base: {len(base_packages)}, Tool-specific additions: {tool_specific_count})\n")
        else:
            print(f"    (All dependencies covered by base requirements)\n")
        
        return final_requirements
    
    def _build_import_to_package_map(self, imports: Set[str]) -> Dict[str, str]:
        """Map import names to their actual package names."""
        import_to_package = {}
        for import_name in imports:
            package_name = self.map_import_to_package(import_name)
            import_to_package[import_name] = package_name
        return import_to_package
    
    def _extract_package_names(self, requirements: List[str]) -> Set[str]:
        """Extract package names from requirement strings."""
        import re
        package_names = set()
        for req in requirements:
            match = re.match(r'^([a-zA-Z0-9_.-]+)', req)
            if match:
                package_names.add(match.group(1))
        return package_names
    
    def _discover_new_dependencies(
        self, 
        all_imports: Set[str], 
        import_to_package: Dict[str, str], 
        matched_packages: Set[str]
    ) -> Dict[str, str]:
        """
        Discover new dependencies not in base requirements.txt.
        Only includes packages that are actually installed (not user-defined).
        
        Returns:
            Dict of {package_name: version_spec}
        """
        new_deps = {}
        
        for import_name in all_imports:
            if import_name in self.stdlib_modules:
                continue
            
            package_name = import_to_package.get(import_name, import_name)
            pkg_normalized = self.requirements_comparator.normalize_package_name(package_name)
            
            if pkg_normalized in matched_packages:
                continue
            if pkg_normalized in self.requirements_comparator.requirements:
                continue
            
            if not self._is_valid_package_name(pkg_normalized):
                continue
            
            top_level = import_name.split('.')[0]
            version_spec = self._get_installed_package_version(top_level)
            
            if version_spec:
                actual_package_name = self._get_actual_package_name(top_level)
                if actual_package_name:
                    normalized_actual = self.requirements_comparator.normalize_package_name(actual_package_name)
                    if normalized_actual not in matched_packages and normalized_actual not in new_deps:
                        new_deps[normalized_actual] = version_spec
        
        return new_deps
    
    def _get_actual_package_name(self, import_name: str) -> str:
        """
        Get the actual package name from an import.
        """
        return self.map_import_to_package(import_name)
    
    def _get_installed_package_version(self, import_name: str) -> str:
        """
        Get installed package version. Returns empty string if not installed.
        This also serves as validation that it's a real package, not user-defined.
        """
        try:
            dist = distribution(import_name)
            return f"=={dist.version}"
        except PackageNotFoundError:
            pass
        
        package_name = self.map_import_to_package(import_name)
        
        try:
            dist = distribution(package_name)
            return f"=={dist.version}"
        except PackageNotFoundError:
            pass
        
        alt_names = [
            package_name.replace('_', '-'),
            package_name.lower(),
            package_name.lower().replace('_', '-')
        ]
        
        for alt_name in alt_names:
            try:
                dist = distribution(alt_name)
                return f"=={dist.version}"
            except PackageNotFoundError:
                continue
        
        return ""
    
    def _is_valid_package_name(self, package_name: str) -> bool:
        """Validate package name format."""
        if not package_name or len(package_name) < 2:
            return False
        if package_name.startswith('-') or package_name.endswith('-'):
            return False
        if all(c in ('-', '_', '.') for c in package_name):
            return False
        return True


def generate_export_requirements(tool_code_strings: List[str] = None) -> List[str]:
    """
    Main function to generate requirements for Export Agent functionality.
    
    Args:
        tool_code_strings: List of tool code strings to analyze for dependencies
        
    Returns:
        List of requirement strings (e.g., ['package==1.0.0', ...])
    """
    current_file = Path(__file__).resolve()
    export_agent_path = current_file.parent
    project_root = export_agent_path.parent
    requirements_path = project_root / 'requirements.txt'
    
    analyzer = ExportDependencyAnalyzer(
        export_agent_path=str(export_agent_path),
        requirements_path=str(requirements_path),
        tool_code_strings=tool_code_strings or []
    )
    
    requirements_list = analyzer.generate_requirements()
    return requirements_list
