# 📗 UI Prompt for IAF - File-Specific Instructions

This document provides React 19 + JSX specific rules and best practices for building the UI application.

## ⚛️ React Best Practices

- Use React.lazy, Suspense, React.memo, useMemo.
- Apply Zustand for state management.
- Use React Query for server state.
- Prefer playbooks for component visibility.
- Try to have common usage of variables and values using hooks, interceptor, zustand, context so the code is clean and data is easily accessible and modifyiable.

## 🧩 Component Design

- Design modular, reusable, headless components.
- Use compound components for complex UI.
- Apply HOCs and custom hooks for logic reuse.

## 🎨 Styling Guidelines

- Use CSS-in-JS (Styled Components or Emotion).
- Apply design tokens and CSS variables.
- Maintain sleek, minimal, futuristic UI.

## 🔌 API Integration

- Use Axios or fetch based on context.
- Abstract API calls into service layer.
- Implement retry, debounce/throttle logic.

## 🧪 Testing

- Write unit tests for all components.
- Use error boundaries and fallback UIs.

## 🌍 Internationalization

- Support English, Tamil, Hindi, Telugu, German, French, Russian.
- Use react-i18next or react-intl.

## 🛠 Maintainability

- Keep code under 900 lines per file.
- Centralize error handling and state management.
- Use clear folder structure and naming conventions.

## 🧭 Migration Readiness

- Ensure compatibility with micro-frontend architecture planned for future.
- Prepare for AGUI protocol and Vite integration.

## 🤖 Agentic Features

- Support file upload, voice-to-text, canvas, richtext, table viewer, etc...
- Implement dynamic widgeting and componentization.

## 🧑‍🎨 UI/UX Enhancements

- Use skeleton UIs, smooth transitions, compact layout.
- Avoid clutter, reduce clicks, improve accessibility.

## 🔐 Security

- Implement login/logout, session timeout.
- Apply secure coding practices and input validation.

## 🧠 Developer Experience

- Structure code for AI IDE understanding.
- Use descriptive names and maintain DRY principles.
