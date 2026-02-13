import { createContext, useContext, useEffect, useRef, useState } from "react";
import { useAuth } from "./AuthContext";

// Context for SSE
const SSEContext = createContext({
  sseMessages: [],
  connectionStatus: "closed",
});

export const SSEProvider = ({ children, sseUrl = `${env.REACT_APP_BASE_URL || process.env.REACT_APP_BASE_URL || ""}/sse/stream/` }) => {
  const { isAuthenticated, sessionId } = useAuth();
  const eventSourceRef = useRef(null);
  const [sseMessages, setSseMessages] = useState([]);
  const [connectionStatus, setConnectionStatus] = useState("closed");
  const [retryDelay, setRetryDelay] = useState(5000); // Start with 5s
  const retryTimeoutRef = useRef(null);
  const retryCountRef = useRef(0);

  // Helper to start SSE connection
  const startSSE = () => {
    if (!isAuthenticated) {
      console.log("[SSE] No authentication or token available");
      return;
    }
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      console.log("[SSE] Closed previous EventSource");
    }
    console.log(`[SSE] Attempting to connect to SSE at ${sseUrl}${sessionId}`);
    //     eventSourceRef.current = new window.EventSource(sseUrl, { withCredentials: true,});

    eventSourceRef.current = new window.EventSource(sseUrl + `${sessionId}`);
    setConnectionStatus("connecting");

    eventSourceRef.current.onopen = (event) => {
      setConnectionStatus("open");
      setRetryDelay(5000); // Reset delay on success
      retryCountRef.current = 0;
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = null;
      }
      console.log("[SSE] Connection opened!");
    };

    eventSourceRef.current.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        setSseMessages((prev) => [...prev, data]);
        console.log("[SSE] Message received:", data);
      } catch (e) {
        setSseMessages((prev) => [...prev, event.data]);
        console.log("[SSE] Raw message received:", event.data);
      }
    };

    eventSourceRef.current.onerror = (event) => {
      setConnectionStatus("error");
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        console.log("[SSE] Connection error, closed EventSource");
      }
      // Exponential backoff retry
      if (!retryTimeoutRef.current) {
        retryCountRef.current += 1;
        const nextDelay = Math.min(retryCountRef.current * 10000, 60000);
        console.log(`[SSE] Will retry connection in ${nextDelay / 1000}s (attempt ${retryCountRef.current})`);
        retryTimeoutRef.current = setTimeout(() => {
          setRetryDelay(nextDelay); // Update delay for next retry
          startSSE();
          retryTimeoutRef.current = null;
        }, nextDelay);
      }
    };
  };

  // Initial mount and refresh logic
  useEffect(() => {
    if (isAuthenticated) {
      startSSE();
    } else {
      // Logout / unauthenticated: cleanup
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        eventSourceRef.current = null;
        console.log("[SSE] Closed EventSource due to logout");
      }
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = null;
      }
      setConnectionStatus("closed");
      setSseMessages([]);
      retryCountRef.current = 0;
      setRetryDelay(5000);
    }
    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
        console.log("[SSE] Unmount: Closed EventSource");
      }
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        console.log("[SSE] Unmount: Cleared retry timeout");
      }
      setConnectionStatus("closed");
    };
    // eslint-disable-next-line
  }, [sseUrl, isAuthenticated]);

  // Listen for refresh (window reload)
  useEffect(() => {
    if (!isAuthenticated) return; // only when logged in
    const handleRefresh = () => {
      if (!isAuthenticated) return;
      if (retryTimeoutRef.current) {
        clearTimeout(retryTimeoutRef.current);
        retryTimeoutRef.current = null;
        console.log("[SSE] Refresh: Cleared retry timeout");
      }
      setRetryDelay(5000); // Reset delay
      retryCountRef.current = 0;
      console.log("[SSE] Refresh: Reconnecting immediately");
      startSSE();
    };
    window.addEventListener("beforeunload", handleRefresh);
    return () => {
      window.removeEventListener("beforeunload", handleRefresh);
    };
  }, [isAuthenticated]);

  return (
    <SSEContext.Provider
      value={{
        sseMessages,
        connectionStatus: isAuthenticated ? connectionStatus : "disabled",
      }}>
      {children}
    </SSEContext.Provider>
  );
};

export const useSSE = () => useContext(SSEContext);

// SSE connection retries with proper exponential backoff
