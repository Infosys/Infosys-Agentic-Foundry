# Agentic Pro UI - AI Coding Agent Instructions

Essential knowledge for AI agents working on this React 19 enterprise agentic frontend application.

## Architecture Overview

**Multi-Context Provider Stack**: The app uses nested context providers for state management - wrap new features in this order: `AuthProvider` → `VersionProvider` → `ApiUrlProvider` → `MessageProvider` → `GlobalComponentProvider`. Each manages specific concerns (auth, API versioning, toast messages, global components).

**Component-Service-Hook Pattern**: Business logic lives in custom services (`src/services/`) that use the `useFetch` hook. Components consume services, never make direct API calls. Example: `useToolsAgentsService()` → `useFetch()` → API endpoints.

**Route Protection**: Use `<ProtectedRoute requiredRole="ADMIN">` for admin-only routes. Guest users get limited functionality with userName="Guest" checks throughout the codebase.

## Critical Patterns

**File Upload System**: Standard drag-and-drop pattern across components uses:

```jsx
// Always use GroundTruth styles for consistency
import groundTruthStyles from "../GroundTruth/GroundTruth.module.css";

// File validation pattern
const validateFile = (file, type) => {
  const validExtensions = type === "code" ? [".py", ".txt"] : [".json"];
  return validExtensions.some((ext) => file.name.toLowerCase().endsWith(ext));
};

// Drag handlers with state management
const [isDragging, setIsDragging] = useState(false);
```

**CSS Modules Convention**: Every component uses CSS modules (`ComponentName.module.css`). Import as `styles` and use `styles.className`. File upload components reuse `groundTruthStyles` for consistency.

**API Configuration**: All endpoints defined in `src/constant.js` under `APIs` object. Base URL comes from `process.env.REACT_APP_BASE_URL`. Use `encodeURIComponent()` for all query parameters.

**Form Submission Pattern**: Always use FormData for file uploads, JSON for data-only requests:

```jsx
const formDataToSend = new FormData();
if (codeFile) {
  formDataToSend.append("tool_file", codeFile);
  formDataToSend.append("code_snippet", "");
} else {
  formDataToSend.append("code_snippet", formData.code);
}
```

## Development Workflows

**Auto-Logout System**: 6-hour absolute session timeout using `useAutoLogout()` hook. Login timestamp stored in localStorage with key `"login_timestamp"`.

**Error Handling**: Use `useMessage()` hook for user notifications: `addMessage(message, "success"|"error")`. Success messages auto-hide after 3 seconds.

**Code Execution**: Tool components support live Python code execution via `/utility/execute-code` endpoint with dynamic input handling for required parameters.

**Version Management**: Combined frontend/backend versioning via `VersionContext` - displays as `v1.4.8+backend_version` in UI.

## Integration Points

**Authentication Flow**: JWT tokens managed by `useAuth()` context + `useFetch()` hook. Cookies store: `userName`, `role`, `user_session`, `jwt-token`, `email`.

**SSE Integration**: Real-time updates via Server-Sent Events in `SSEContext` (currently commented out in `index.js` but infrastructure ready).

**File Management**: Upload/download system uses user-specific directories. Files organized by `user_uploads/{email}/{subdirectory}/` structure.

## Quick Start Commands

```bash
npm install          # Install dependencies
npm start           # Development server (localhost:3000)
npm run build       # Production build
npm test            # Run tests
```

**Environment Setup**: Configure `src/constant.js` with your backend URL:

```javascript
export const BASE_URL = process.env.REACT_APP_BASE_URL;
```

## AI Agent Guidelines

- Use double quotes for strings (project convention)
- Prefer async/await over Promise.then()
- Import CSS modules as named imports (`import styles from "./Component.module.css"`)
- Always validate file types before upload using existing patterns
- Check role-based permissions using `Cookies.get("role")` for conditional rendering
- Use semantic HTML with proper ARIA labels for accessibility
- Follow the drag-and-drop pattern from existing components for consistency
- Make your suggestions more readable , easy to understand for even a fresher to understand and scale the code
- The code updates should be concise and to the point
- UI generated should be modular, reusable, extendable, modern and sleek in aestheric, design and also in coding.
