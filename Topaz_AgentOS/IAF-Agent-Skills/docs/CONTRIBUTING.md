# Contributing to IAF-Agent-Skills

Thank you for your interest in contributing! This document provides guidelines for contributing to the IAF-Agent-Skills project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/IAF-Agent-Skills.git
   cd IAF-Agent-Skills
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt  # includes pytest and test deps
   ```

## Development Setup

### Environment Variables

Copy and configure:
```bash
cp config.env.example config.env
# Edit config.env with your Azure OpenAI credentials
```

### Running Tests

```bash
# All tests
pytest tests/ -v

# Specific test file
pytest tests/test_router.py -v

# With coverage
pytest tests/ --cov=iaf_agent_skills --cov-report=html
```

## How to Contribute

### Adding a New Skill

See the canonical [docs/AUTHORING_GUIDE.md](../../docs/AUTHORING_GUIDE.md) and the starter templates under [docs/skill_templates/](../../docs/skill_templates/) for detailed instructions.

Quick checklist:
- [ ] Create `skills/your_skill/SKILL.md`
- [ ] Add entry to `skills/_index.yaml`
- [ ] Add keyword shortcuts to `router.py` (optional)
- [ ] Test routing with your skill
- [ ] Update documentation if needed

### Fixing a Bug

1. Create an issue describing the bug
2. Create a branch: `git checkout -b fix/issue-123-description`
3. Write a test that reproduces the bug
4. Fix the bug
5. Ensure all tests pass
6. Submit a pull request

### Adding a Feature

1. Open an issue to discuss the feature
2. Create a branch: `git checkout -b feature/description`
3. Implement with tests
4. Update documentation
5. Submit a pull request

## Code Style

- **Python 3.10+** required
- **Type hints** on all function signatures
- **Docstrings** for public methods (Google style)
- **Max line length**: 100 characters
- Use `Path` from pathlib for file operations

### Example

```python
def process_query(query: str, max_length: int = 1000) -> tuple[str, bool]:
    """
    Process and validate a user query.
    
    Args:
        query: The raw user input
        max_length: Maximum allowed query length
        
    Returns:
        Tuple of (processed_query, is_valid)
        
    Raises:
        ValueError: If query is empty
    """
    if not query:
        raise ValueError("Query cannot be empty")
    
    processed = query.strip()[:max_length]
    is_valid = len(processed) > 0
    
    return processed, is_valid
```

## Pull Request Guidelines

### Before Submitting

- [ ] Tests pass locally: `pytest tests/ -v`
- [ ] Code is formatted properly
- [ ] Documentation is updated
- [ ] Commit messages are clear

### PR Title Format

```
[component] Brief description

Examples:
[router] Add keyword shortcuts for finance skill
[agent] Fix conversation history filtering
[loader] Support YAML arrays in frontmatter
[docs] Add skill development guide
```

### PR Description Template

```markdown
## What
Brief description of changes

## Why
Motivation for the change

## How
Implementation approach

## Testing
How you tested the changes

## Checklist
- [ ] Tests added/updated
- [ ] Documentation updated
- [ ] No breaking changes (or documented)
```

## Reporting Issues

### Bug Reports

Include:
- Python version
- OS and version
- Steps to reproduce
- Expected vs actual behavior
- Error messages/stack traces

### Feature Requests

Include:
- Use case description
- Proposed solution
- Alternative approaches considered

## Questions?

- Open a GitHub issue for questions
- Tag with `question` label

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
