# Contributing to IAF-Agent-Studio

Thank you for your interest in contributing! This document provides guidelines for contributing to the IAF-Agent-Studio project.

## Getting Started

1. **Fork the repository** on GitHub
2. **Clone your fork** locally:
   ```bash
   git clone https://github.com/YOUR_USERNAME/IAF-Agent-Studio.git
   cd IAF-Agent-Studio
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

## Development Setup

### Environment Variables

```bash
cp config.env.example config.env
# Edit config.env with your settings
```

### Running the Server

```bash
# Development (auto-reload)
python server.py

# Production
uvicorn server:app --host 0.0.0.0 --port 8080 --workers 4
```

### Dependencies

Ensure sibling directories exist:
- `../agent_os` - SafeKernel
- `../IAF-Agent-Skills` - SkillAgent, SkillRouter

## How to Contribute

### Adding an API Endpoint

1. Add the route in `server.py`:
   ```python
   @app.get("/api/new-endpoint")
   async def new_endpoint(param: str):
       """Endpoint description."""
       return {"result": param}
   ```

2. Add Pydantic model if needed:
   ```python
   class NewRequest(BaseModel):
       field1: str
       field2: int = 10
   ```

3. Document in README.md

### Modifying the UI

The UI is a single file: `static/index.html`

Key sections:
- **Alpine.js data** (~line 400): Application state
- **Methods** (~line 600): Event handlers
- **Template** (~line 100): HTML structure

Tips:
- Use TailwindCSS utility classes
- Keep JavaScript inline (no build step)
- Test on mobile viewport

### Fixing a Bug

1. Create an issue describing the bug
2. Create a branch: `git checkout -b fix/issue-123-description`
3. Fix the bug
4. Test manually in browser
5. Submit a pull request

## Code Style

### Python (server.py)

- **Python 3.10+** required
- **Type hints** on all function signatures
- **async/await** for all endpoint handlers
- **Pydantic models** for request validation
- Max line length: 100 characters

### HTML/JavaScript (static/index.html)

- **Alpine.js** for reactivity
- **TailwindCSS** for styling
- Keep methods short and focused
- Comment complex logic

### Example API Endpoint

```python
class WidgetRequest(BaseModel):
    """Request model for widget creation."""
    name: str
    config: dict = {}

@app.post("/api/widgets")
async def create_widget(request: WidgetRequest) -> dict:
    """
    Create a new widget.
    
    Args:
        request: Widget creation parameters
        
    Returns:
        Created widget with ID
    """
    widget_id = str(uuid.uuid4())
    return {
        "id": widget_id,
        "name": request.name,
        "config": request.config
    }
```

## Pull Request Guidelines

### Before Submitting

- [ ] Server starts without errors
- [ ] UI loads correctly
- [ ] WebSocket connection works
- [ ] No console errors in browser
- [ ] Documentation updated

### PR Title Format

```
[component] Brief description

Examples:
[api] Add file upload endpoint
[ui] Fix mobile layout issues
[ws] Improve streaming performance
[docs] Update API documentation
```

## Testing

### Manual Testing Checklist

- [ ] Page loads at http://localhost:8080
- [ ] WebSocket connects (green indicator)
- [ ] Can send chat message
- [ ] Tool calls display correctly
- [ ] Skill routing works
- [ ] File browser navigates correctly
- [ ] Works on mobile viewport

### API Testing

```bash
# Health check (liveness / readiness)
curl http://localhost:8080/health/live
curl http://localhost:8080/health/ready

# List skills
curl http://localhost:8080/api/skills

# List files
curl "http://localhost:8080/api/files?path=/&user_id=demo"
```

## Reporting Issues

### Bug Reports

Include:
- Browser and version
- OS and version
- Steps to reproduce
- Expected vs actual behavior
- Console errors (if any)
- Network tab errors (if any)

### Feature Requests

Include:
- Use case description
- Mockup or description of UI changes
- API changes needed

## License

By contributing, you agree that your contributions will be licensed under the Apache License 2.0.
