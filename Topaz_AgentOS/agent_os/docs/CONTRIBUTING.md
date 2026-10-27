# Contributing to AgentOS

Thank you for your interest in contributing! This document provides guidelines for contributing to the AgentOS project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/agent_os.git
   cd agent_os
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Development Setup

### Running Tests

```bash
# All tests (70+ tests)
pytest tests/test_agentos.py -v

# Specific test class
pytest tests/test_agentos.py::TestSecurity -v

# With coverage
pytest tests/test_agentos.py --cov=. --cov-report=html
```

### Test Categories

- `TestSecurity` - Path traversal, command injection, sandboxing
- `TestFileOperations` - File operations, permissions
- `TestWriteOperations` - Write/append file handling
- `TestSemanticSearch` - Semantic search functionality
- `TestRBAC` - Role-based access control

## How to Contribute

### Adding a New Command

1. Add implementation in `kernel.py`:
   ```python
   def _cmd_newcmd(self, args: list[str]) -> str:
       """Implement new command."""
       # Implementation
       return "result"
   ```

2. Register in command dispatch:
   ```python
   self._commands = {
       # ... existing commands
       "newcmd": self._cmd_newcmd,
   }
   ```

3. Add tests:
   ```python
   def test_newcmd_basic(self):
       result = self.kernel.run_shell_command("newcmd arg1 arg2")
       self.assertIn("expected", result)
   ```

4. Update documentation

### Fixing a Bug

1. Create an issue describing the bug
2. Create a branch: `git checkout -b fix/issue-123-description`
3. Write a test that reproduces the bug
4. Fix the bug
5. Ensure all tests pass
6. Submit a pull request

### Security Contributions

Security is critical for AgentOS. If you find a security issue:

1. **DO NOT** create a public issue
2. Email the maintainers directly
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

## Code Style

- **Python 3.10+** required
- **Type hints** on all function signatures
- **Docstrings** for all public methods (Google style)
- **No external dependencies** for core kernel
- Max line length: 100 characters
- Use `Path` from pathlib

### Example

```python
def resolve_path(self, virtual_path: str, check_exists: bool = True) -> Path:
    """
    Resolve a virtual path to a real filesystem path.
    
    Args:
        virtual_path: Path in the virtual filesystem (e.g., /me/file.txt)
        check_exists: Whether to verify the path exists
        
    Returns:
        Resolved Path object
        
    Raises:
        SecurityError: If path escapes sandbox
        FileNotFoundError: If check_exists=True and path doesn't exist
    """
    # Implementation
```

## Pull Request Guidelines

### Before Submitting

- [ ] All tests pass: `pytest tests/test_agentos.py -v`
- [ ] No security regressions
- [ ] Code is formatted properly
- [ ] Documentation updated
- [ ] Commit messages are clear

### PR Title Format

```
[component] Brief description

Examples:
[kernel] Add chmod command support
[security] Fix path traversal in symlink resolution
[vector] Improve embedding performance
[docs] Update API documentation
```

### Security Checklist

For changes affecting security:
- [ ] Path traversal tests pass
- [ ] Command injection tests pass
- [ ] Permission checks in place
- [ ] No new attack vectors introduced

## Testing Security

Always run security tests after changes:

```bash
pytest tests/test_agentos.py::TestSecurity -v
```

Key security tests:
- `test_path_traversal_blocked`
- `test_command_chaining_blocked`
- `test_absolute_system_paths_blocked`
- `test_write_to_shared_blocked`

## Reporting Issues

### Bug Reports

Include:
- Python version
- OS and version
- Steps to reproduce
- Expected vs actual behavior
- Error messages/stack traces

### Security Issues

**DO NOT** open public issues for security vulnerabilities.
Contact maintainers directly.

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
