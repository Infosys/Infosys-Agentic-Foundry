

class LLMInfrastructureError(Exception):
    """Technical failure when talking to LLM provider"""

    def __init__(self, message: str, type: str):
        super().__init__(message)
        # Known types: "connection_error", "rate_limit", "context_length", "content_policy",
        # "invalid_credentials", "bad_request", "service_unavailable", "timeout",
        # "server_error", "api_error", "unknown"
        # For unknown providers the original error message is preserved as-is.
        self.type = type
