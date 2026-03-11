// ThemeContext.js
import React, { createContext, useContext, useEffect, useMemo, useState } from "react";

const ThemeContext = createContext(null);

export function ThemeProvider({ children }) {
  // Safe guards for SSR (Next.js, etc.) where window/localStorage may be undefined.
  const isClient = typeof window !== "undefined";

  const getSystemTheme = () => {
    if (!isClient || !window.matchMedia) return "light";
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  };

  const getInitialTheme = () => {
    return "dark";
  };

  const [theme, setTheme] = useState(getInitialTheme);

  // Reflect theme to <html data-theme="...">
  useEffect(() => {
    if (!isClient) return;
    document.documentElement.setAttribute("data-theme", theme);
  }, [theme, isClient]);

  // Optional: respond to OS scheme changes when user hasn't explicitly set a theme
  useEffect(() => {
    if (!isClient || !window.matchMedia) return;

    const mq = window.matchMedia("(prefers-color-scheme: dark)");

    const handler = (e) => {
      const userSet = localStorage.getItem("theme");
      if (!userSet) {
        setTheme(e.matches ? "dark" : "light");
      }
    };

    // Modern browsers: addEventListener; older need addListener
    if (typeof mq.addEventListener === "function") {
      mq.addEventListener("change", handler);
      return () => mq.removeEventListener("change", handler);
    } else if (typeof mq.addListener === "function") {
      mq.addListener(handler);
      return () => mq.removeListener(handler);
    }
  }, [isClient]);

  const toggleTheme = () =>
    setTheme((t) => {
      if (t === "light") return "dark";
      return "light";
    });

  const value = useMemo(() => ({ theme, toggleTheme, setTheme }), [theme]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = useContext(ThemeContext);
  if (!ctx) {
    throw new Error("useTheme must be used within <ThemeProvider>");
  }
  return ctx;
}
