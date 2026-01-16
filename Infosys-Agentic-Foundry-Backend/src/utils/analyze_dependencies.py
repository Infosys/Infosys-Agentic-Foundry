import ast
import re
import sys
import argparse
from pathlib import Path
from typing import Set, Dict, List, Tuple, Optional
import subprocess
import importlib.util
try:
    from importlib.metadata import distributions, distribution, PackageNotFoundError
except ImportError:
    # Fallback for Python < 3.8
    from importlib_metadata import distributions, distribution, PackageNotFoundError

class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor to extract all types of imports from Python source code."""

    def __init__(self, filepath: str):
        self.filepath = filepath
        self.imports = set()
        self.conditional_imports = set()
        self.dynamic_imports = set()
        self.indirect_imports = set()
        self.current_scope = []

    def visit_Import(self, node: ast.Import) -> None:
        """Extract imports from 'import module' statements."""
        for alias in node.names:
            full_module = alias.name
            top_level = full_module.split('.')[0]
            if self.current_scope:
                self.indirect_imports.add(top_level)
                self.indirect_imports.add(full_module)
            else:
                self.imports.add(top_level)
                self.imports.add(full_module)
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Extract imports from 'from module import ...' statements."""
        if node.module:
            full_module = node.module
            parts = full_module.split('.')
            if self.current_scope:
                self.indirect_imports.add(parts[0])
                for i in range(1, len(parts) + 1):
                    self.indirect_imports.add('.'.join(parts[:i]))
            else:
                self.imports.add(parts[0])
                for i in range(1, len(parts) + 1):
                    self.imports.add('.'.join(parts[:i]))
        self.generic_visit(node)
    
    def visit_Try(self, node: ast.Try) -> None:
        """Extract conditional imports from try/except blocks."""
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        self.conditional_imports.add(alias.name.split('.')[0])
                elif isinstance(child, ast.ImportFrom) and child.module:
                    self.conditional_imports.add(child.module.split('.')[0])
        self.generic_visit(node)
    
    def visit_If(self, node: ast.If) -> None:
        """Extract conditional imports from if statements."""
        for child in ast.walk(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                if isinstance(child, ast.Import):
                    for alias in child.names:
                        self.conditional_imports.add(alias.name.split('.')[0])
                elif isinstance(child, ast.ImportFrom) and child.module:
                    self.conditional_imports.add(child.module.split('.')[0])
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call) -> None:
        """Extract dynamic imports like __import__() and importlib.import_module()."""
        if isinstance(node.func, ast.Name) and node.func.id == '__import__':
            if node.args and isinstance(node.args[0], ast.Constant):
                self.dynamic_imports.add(node.args[0].value.split('.')[0])
        
        if isinstance(node.func, ast.Attribute):
            if (isinstance(node.func.value, ast.Name) and 
                node.func.value.id == 'importlib' and 
                node.func.attr == 'import_module'):
                if node.args and isinstance(node.args[0], ast.Constant):
                    self.dynamic_imports.add(node.args[0].value.split('.')[0])
        
        self.generic_visit(node)
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Track function scope for indirect imports."""
        self.current_scope.append(node.name)
        self.generic_visit(node)
        self.current_scope.pop()
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Track async function scope for indirect imports."""
        self.current_scope.append(node.name)
        self.generic_visit(node)
        self.current_scope.pop()
    
    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Track class scope for indirect imports."""
        self.current_scope.append(node.name)
        self.generic_visit(node)
        self.current_scope.pop()


class StringImportExtractor:
    """Extract imports from string patterns using regex."""
    
    @staticmethod
    def extract_from_content(content: str) -> Set[str]:
        """Extract potential module names from string patterns and runtime dependencies."""
        imports = set()
        
        imports.update(re.findall(r'__import__\s*\(\s*["\']([a-zA-Z0-9_\.]+)["\']', content))
        imports.update(re.findall(r'import_module\s*\(\s*["\']([a-zA-Z0-9_\.]+)["\']', content))
        imports.update(re.findall(r'(?:exec|eval)\s*\([^)]*import\s+([a-zA-Z0-9_\.]+)', content))
        
        potential_modules = re.findall(r'["\']([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)["\']', content.lower())
        
        for module in potential_modules:
            if any(pattern in module for pattern in ['sql', 'db', 'connector', 'driver', 'database']):
                if re.search(rf'["\'{module}["\'].*(?:connection|database|driver|connector)', content, re.IGNORECASE):
                    imports.add(module)
        
        file_extensions = re.findall(r'\.([a-z]{2,5})["\']', content.lower())
        for ext in set(file_extensions):
            if ext in ['xlsx', 'xls', 'xlsm', 'xlsb']:
                if re.search(r'(?:load_workbook|Workbook|openpyxl|read_excel|to_excel)', content, re.IGNORECASE):
                    imports.add('openpyxl')
            elif ext in ['db', 'sqlite', 'sqlite3']:
                imports.add('sqlite3')
        
        vector_classes = re.findall(r'(?:from\s+[\w.]+\s+import\s+|class\s+)([A-Z][A-Z]+)\b', content)
        for cls in vector_classes:
            if re.search(rf'{cls}.*(?:vector|embedding|index|store)', content, re.IGNORECASE) or \
               re.search(rf'(?:vector|embedding|index|store).*{cls}', content, re.IGNORECASE):
                imports.add(cls.lower())
        
        return imports


class DependencyAnalyzer:
    """Analyzes project dependencies by scanning Python files for all import types."""
    
    def __init__(self, project_path: str, exclude_dirs: Optional[List[str]] = None):
        self.project_path = Path(project_path).resolve()
        self.exclude_dirs = set(exclude_dirs or [
            '__pycache__', '.git', '.venv', 'venv', 'env',
            'node_modules', '.tox', '.pytest_cache', '.mypy_cache',
            'build', 'dist', '*.egg-info'
        ])
        self.all_imports = {
            'direct': set(),
            'conditional': set(),
            'dynamic': set(),
            'indirect': set(),
            'string_based': set()
        }
        self.stdlib_modules = self._get_stdlib_modules()
        
    def _get_stdlib_modules(self) -> Set[str]:
        """Get set of Python standard library modules."""
        import sys
        stdlib = set(sys.builtin_module_names)
        
        stdlib_list = [
            'abc', 'aifc', 'argparse', 'array', 'ast', 'asynchat', 'asyncio',
            'asyncore', 'atexit', 'audioop', 'base64', 'bdb', 'binascii', 'binhex',
            'bisect', 'builtins', 'bz2', 'calendar', 'cgi', 'cgitb', 'chunk',
            'cmath', 'cmd', 'code', 'codecs', 'codeop', 'collections', 'colorsys',
            'compileall', 'concurrent', 'configparser', 'contextlib', 'contextvars',
            'copy', 'copyreg', 'cProfile', 'crypt', 'csv', 'ctypes', 'curses',
            'dataclasses', 'datetime', 'dbm', 'decimal', 'difflib', 'dis', 'distutils',
            'doctest', 'dummy_threading', 'email', 'encodings', 'enum', 'errno',
            'faulthandler', 'fcntl', 'filecmp', 'fileinput', 'fnmatch', 'formatter',
            'fractions', 'ftplib', 'functools', 'gc', 'getopt', 'getpass', 'gettext',
            'glob', 'graphlib', 'grp', 'gzip', 'hashlib', 'heapq', 'hmac', 'html',
            'http', 'imaplib', 'imghdr', 'imp', 'importlib', 'inspect', 'io',
            'ipaddress', 'itertools', 'json', 'keyword', 'lib2to3', 'linecache',
            'locale', 'logging', 'lzma', 'mailbox', 'mailcap', 'marshal', 'math',
            'mimetypes', 'mmap', 'modulefinder', 'msilib', 'msvcrt', 'multiprocessing',
            'netrc', 'nis', 'nntplib', 'numbers', 'operator', 'optparse', 'os',
            'ossaudiodev', 'parser', 'pathlib', 'pdb', 'pickle', 'pickletools',
            'pipes', 'pkgutil', 'platform', 'plistlib', 'poplib', 'posix', 'posixpath',
            'pprint', 'profile', 'pstats', 'pty', 'pwd', 'py_compile', 'pyclbr',
            'pydoc', 'queue', 'quopri', 'random', 're', 'readline', 'reprlib',
            'resource', 'rlcompleter', 'runpy', 'sched', 'secrets', 'select',
            'selectors', 'shelve', 'shlex', 'shutil', 'signal', 'site', 'smtpd',
            'smtplib', 'sndhdr', 'socket', 'socketserver', 'spwd', 'sqlite3', 'ssl',
            'stat', 'statistics', 'string', 'stringprep', 'struct', 'subprocess',
            'sunau', 'symbol', 'symtable', 'sys', 'sysconfig', 'syslog', 'tabnanny',
            'tarfile', 'telnetlib', 'tempfile', 'termios', 'test', 'textwrap', 'threading',
            'time', 'timeit', 'tkinter', 'token', 'tokenize', 'tomllib', 'trace',
            'traceback', 'tracemalloc', 'tty', 'turtle', 'turtledemo', 'types',
            'typing', 'typing_extensions', 'unicodedata', 'unittest', 'urllib', 'uu',
            'uuid', 'venv', 'warnings', 'wave', 'weakref', 'webbrowser', 'winreg',
            'winsound', 'wsgiref', 'xdrlib', 'xml', 'xmlrpc', 'zipapp', 'zipfile',
            'zipimport', 'zlib', '_thread'
        ]
        stdlib.update(stdlib_list)
        
        return stdlib
    
    def _should_exclude(self, path: Path) -> bool:
        """Check if path should be excluded from analysis."""
        parts = path.parts
        for part in parts:
            for exclude in self.exclude_dirs:
                if exclude.endswith('*'):
                    if part.startswith(exclude[:-1]):
                        return True
                elif part == exclude:
                    return True
        return False
    
    def find_python_files(self) -> List[Path]:
        """Find all Python files in the project, excluding specified directories."""
        python_files = []
        for py_file in self.project_path.rglob('*.py'):
            if not self._should_exclude(py_file):
                python_files.append(py_file)
        return python_files
    
    def analyze_file(self, filepath: Path) -> Dict[str, Set[str]]:
        """Analyze a single Python file for all import types."""
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            
            tree = ast.parse(content, filename=str(filepath))
            analyzer = ImportAnalyzer(str(filepath))
            analyzer.visit(tree)
            string_imports = StringImportExtractor.extract_from_content(content)
            namespace_deps = self._detect_namespace_dependencies(analyzer.imports | analyzer.indirect_imports)
            
            return {
                'direct': analyzer.imports,
                'conditional': analyzer.conditional_imports,
                'dynamic': analyzer.dynamic_imports,
                'indirect': analyzer.indirect_imports,
                'string_based': string_imports | namespace_deps
            }
            
        except Exception as e:
            print(f"Warning: Could not analyze {filepath}: {e}", file=sys.stderr)
            return {
                'direct': set(),
                'conditional': set(),
                'dynamic': set(),
                'indirect': set(),
                'string_based': set()
            }
    
    def _detect_namespace_dependencies(self, imports: Set[str]) -> Set[str]:
        """Detect hidden dependencies based on package namespaces."""
        namespace_deps = set()
        
        for import_name in imports:
            if '.' in import_name:
                parts = import_name.split('.')
                
                for part in parts:
                    potential_deps = self._extract_potential_deps_from_name(part)
                    namespace_deps.update(potential_deps)
                
                if len(parts) >= 2:
                    last_part = parts[-1]
                    potential_deps = self._extract_potential_deps_from_name(last_part)
                    namespace_deps.update(potential_deps)
        
        return namespace_deps
    
    def _extract_potential_deps_from_name(self, name: str) -> Set[str]:
        """Extract potential dependency names from a module/class name."""
        potential_deps = set()
        name_lower = name.lower()
        
        if '_' in name_lower:
            no_underscore = name_lower.replace('_', '')
            potential_deps.add(no_underscore)
            hyphenated = name_lower.replace('_', '-')
            potential_deps.add(hyphenated)
            parts = name_lower.split('_')
            if len(parts) == 2:
                potential_deps.add(''.join(parts))
        
        if name != name_lower:
            potential_deps.add(name_lower)
        
        for suffix in ['lib', 'client', 'api', 'wrapper', 'adapter']:
            if name_lower.endswith(suffix):
                base = name_lower[:-len(suffix)]
                if base:
                    potential_deps.add(base)
        
        return potential_deps
    
    def analyze_all_files(self) -> None:
        """Analyze all Python files in the project and aggregate imports."""
        python_files = self.find_python_files()
        
        for py_file in python_files:
            file_imports = self.analyze_file(py_file)
            for import_type, imports in file_imports.items():
                self.all_imports[import_type].update(imports)
    
    def get_all_unique_imports(self) -> Set[str]:
        """Get all unique imports across all types, excluding standard library."""
        all_imports = set()
        for imports in self.all_imports.values():
            all_imports.update(imports)
        
        return {imp for imp in all_imports if imp not in self.stdlib_modules}
    
    def get_transitive_dependencies(self, package: str) -> Set[str]:
        """Get transitive dependencies of a package using pip show."""
        try:
            result = subprocess.run(
                [sys.executable, '-m', 'pip', 'show', package],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if line.startswith('Requires:'):
                        deps = line.split(':', 1)[1].strip()
                        if deps:
                            clean_deps = set()
                            for dep in deps.split(','):
                                dep = dep.strip()
                                # Remove version specifiers
                                dep = re.split(r'[<>=!]', dep)[0].strip()
                                if dep:
                                    clean_deps.add(dep)
                            return clean_deps
            return set()
        except Exception:
            return set()
    
    def get_all_package_dependencies(self, packages: Set[str]) -> Set[str]:
        """Get all transitive dependencies for a set of packages recursively."""
        all_deps = set()
        to_check = set(packages)
        checked = set()
        
        print(f"  Checking {len(to_check)} packages for dependencies...")
        
        while to_check:
            package = to_check.pop()
            if package in checked:
                continue
            
            checked.add(package)
            deps = self.get_transitive_dependencies(package)
            
            if deps:
                for dep in deps:
                    dep_normalized = dep.lower().replace('_', '-')
                    if dep_normalized and dep_normalized not in checked:
                        all_deps.add(dep_normalized)
                        to_check.add(dep_normalized)
        
        return all_deps
    
    def map_import_to_package(self, import_name: str) -> Optional[str]:
        """
        Map an import name to its package name using dynamic discovery.
        Uses installed package metadata to find the correct package name.
        """
        if '.' in import_name:
            return import_name.replace('.', '-')
        
        top_level = import_name.split('.')[0]
        
        try:
            for dist in distributions():
                try:
                    if dist.read_text('top_level.txt'):
                        top_level_modules = dist.read_text('top_level.txt').split()
                        if top_level in top_level_modules:
                            return dist.name
                        if import_name in top_level_modules:
                            return dist.name
                except Exception:
                    continue
        except Exception:
            pass
        
        return import_name

class RequirementsComparator:
    """Parse requirements.txt and match with discovered imports."""
    
    def __init__(self, requirements_path: str, is_content: bool = False):
        """
        Initialize RequirementsComparator.
        
        Args:
            requirements_path: Path to requirements.txt file OR content string
            is_content: If True, requirements_path is treated as file content
        """
        self.is_content = is_content
        if is_content:
            self.requirements_path = None
            self.requirements_content = requirements_path
        else:
            self.requirements_path = Path(requirements_path)
            self.requirements_content = None
        self.requirements = {}
        self.parse_requirements()
    
    def parse_requirements(self) -> None:
        """Parse requirements.txt file or content, extracting package names and versions."""
        lines = []
        
        if self.is_content:
            # Parse from content string
            if not self.requirements_content:
                return
            lines = self.requirements_content.split('\n')
        else:
            # Parse from file
            if not self.requirements_path.exists():
                print(f"Warning: {self.requirements_path} not found.", file=sys.stderr)
                return
            
            with open(self.requirements_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
        
        for line in lines:
            line = line.strip()
            
            if not line or line.startswith('#'):
                continue
            
            match = re.match(r'^([a-zA-Z0-9_.-]+)(.*?)$', line)
            if match:
                package_name = match.group(1).lower().replace('_', '-')
                version_spec = match.group(2).strip()
                self.requirements[package_name] = version_spec or ''
    
    def normalize_package_name(self, name: str) -> str:
        """Normalize package name (lowercase, replace _ with -)."""
        return name.lower().replace('_', '-')
    
    def find_matching_requirement(self, import_name: str, package_name: str) -> Optional[Tuple[str, str]]:
        """Find matching requirement for an import using dynamic pattern matching."""
        normalized_package = self.normalize_package_name(package_name)
        normalized_import = self.normalize_package_name(import_name)
        
        if normalized_package in self.requirements:
            return (normalized_package, self.requirements[normalized_package])
        if normalized_import in self.requirements:
            return (normalized_import, self.requirements[normalized_import])
        
        if '.' in import_name:
            hyphenated_import = import_name.replace('.', '-').lower()
            if hyphenated_import in self.requirements:
                return (hyphenated_import, self.requirements[hyphenated_import])
            
            top_level = import_name.split('.')[0].lower()
            if top_level in self.requirements:
                return (top_level, self.requirements[top_level])
        
        if '.' in package_name:
            hyphenated_package = package_name.replace('.', '-').lower()
            if hyphenated_package in self.requirements:
                return (hyphenated_package, self.requirements[hyphenated_package])
            
            top_level = package_name.split('.')[0].lower()
            if top_level in self.requirements:
                return (top_level, self.requirements[top_level])
        
        import_lower = normalized_import
        package_lower = normalized_package
        
        for req_name in self.requirements:
            req_lower = req_name.lower()
            
            if (req_name.startswith(package_lower) or 
                req_name.startswith(import_lower) or
                package_lower.startswith(req_lower) or
                import_lower.startswith(req_lower) or
                req_name.endswith('-' + package_lower) or
                req_name.endswith('-' + import_lower)):
                return (req_name, self.requirements[req_name])
            
            if req_lower == f'py{import_lower}' or req_lower == f'py{package_lower}':
                return (req_name, self.requirements[req_name])
            
            if req_lower.startswith('py') and len(req_lower) > 2:
                req_without_py = req_lower[2:]
                if req_without_py == import_lower or req_without_py == package_lower:
                    return (req_name, self.requirements[req_name])
            
            if (req_lower == f'python-{import_lower}' or 
                req_lower == f'{import_lower}-python' or
                req_lower == f'python-{package_lower}' or 
                req_lower == f'{package_lower}-python'):
                return (req_name, self.requirements[req_name])
        
        return None
    
    def generate_optimized_requirements(
        self, 
        used_imports: Set[str],
        import_to_package_map: Dict[str, str]
    ) -> List[str]:
        """Generate optimized requirements list with only used dependencies."""
        optimized = []
        matched_packages = set()
        unmatched_imports = []
        seen_requirements = set()
        
        for import_name in sorted(used_imports):
            package_name = import_to_package_map.get(import_name, import_name)
            match = self.find_matching_requirement(import_name, package_name)
            
            if match:
                pkg_name, version_spec = match
                matched_packages.add(pkg_name)
                requirement_line = f"{pkg_name}{version_spec}"
                
                if requirement_line not in seen_requirements:
                    seen_requirements.add(requirement_line)
                    optimized.append(requirement_line)
            else:
                is_nested_match = False
                if '.' in import_name:
                    top_level = import_name.split('.')[0]
                    if any(pkg.startswith(top_level) for pkg in matched_packages):
                        is_nested_match = True
                if not is_nested_match and '.' in package_name:
                    top_level = package_name.split('.')[0]
                    if any(pkg.startswith(top_level) for pkg in matched_packages):
                        is_nested_match = True
                
                if not is_nested_match:
                    unmatched_imports.append((import_name, package_name))
        
        if unmatched_imports:
            unique_unmatched = {}
            for import_name, package_name in unmatched_imports:
                top_level = import_name.split('.')[0]
                if top_level not in unique_unmatched:
                    unique_unmatched[top_level] = (import_name, package_name)
        
        return optimized

