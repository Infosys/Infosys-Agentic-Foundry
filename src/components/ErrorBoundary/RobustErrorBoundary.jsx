import React from "react";

class RobustErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = {
      hasError: false,
      error: null,
      errorInfo: null,
      errorCount: 0,
      lastErrorTime: null,
    };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true };
  }

  componentDidCatch(error, errorInfo) {
    const now = Date.now();
    const timeSinceLastError = this.state.lastErrorTime ? now - this.state.lastErrorTime : Infinity;

    this.setState((prevState) => ({
      error,
      errorInfo,
      errorCount: timeSinceLastError < 5000 ? prevState.errorCount + 1 : 1,
      lastErrorTime: now,
    }));

    this.logErrorDetails(error, errorInfo);

    if (this.props.onError) {
      this.props.onError(error, errorInfo);
    }
  }

  logErrorDetails = (error, errorInfo) => {
    const errorData = {
      message: error.toString(),
      stack: error.stack,
      componentStack: errorInfo.componentStack,
      timestamp: new Date().toISOString(),
      userAgent: navigator.userAgent,
      location: window.location.href,
    };

    console.error("🔴 Error Boundary Caught:", errorData);
  };

  resetError = () => {
    this.setState({
      hasError: false,
      error: null,
      errorInfo: null,
    });

    if (this.props.onReset) {
      this.props.onReset();
    }
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.resetError);
      }

      return (
        <div
          style={{
            padding: "40px",
            textAlign: "center",
            backgroundColor: "#fff3cd",
            border: "2px solid #ffc107",
            borderRadius: "8px",
            margin: "20px",
            minHeight: "300px",
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
          }}>
          <h2 style={{ color: "#856404", marginBottom: "20px" }}>⚠️ Something went wrong</h2>
          <p style={{ color: "#856404", marginBottom: "20px" }}>We apologize for the inconvenience. An unexpected error has occurred.</p>
          <details
            style={{
              whiteSpace: "pre-wrap",
              textAlign: "left",
              marginTop: "20px",
              padding: "15px",
              backgroundColor: "#fff",
              borderRadius: "4px",
              maxWidth: "600px",
              width: "100%",
            }}>
            <summary style={{ cursor: "pointer", fontWeight: "bold", marginBottom: "10px" }}>Error Details (for developers)</summary>
            <p style={{ color: "#721c24", marginTop: "10px", fontSize: "14px", fontFamily: "monospace" }}>{this.state.error && this.state.error.toString()}</p>
            {this.state.errorInfo && (
              <pre
                style={{
                  color: "#721c24",
                  marginTop: "10px",
                  fontSize: "12px",
                  overflow: "auto",
                  maxHeight: "200px",
                }}>
                {this.state.errorInfo.componentStack}
              </pre>
            )}
          </details>
          <button
            onClick={this.resetError}
            style={{
              marginTop: "20px",
              padding: "10px 30px",
              backgroundColor: "#007ac0",
              color: "#fff",
              border: "none",
              borderRadius: "4px",
              cursor: "pointer",
              fontSize: "16px",
              fontWeight: "bold",
            }}
            onMouseOver={(e) => (e.target.style.backgroundColor = "#005a8f")}
            onMouseOut={(e) => (e.target.style.backgroundColor = "#007ac0")}>
            Try Again
          </button>
          {this.state.errorCount > 3 && (
            <p style={{ marginTop: "20px", color: "#721c24", fontWeight: "bold" }}>⚠️ Multiple errors detected. Please refresh the page or contact support.</p>
          )}
        </div>
      );
    }

    return this.props.children;
  }
}

export default RobustErrorBoundary;
