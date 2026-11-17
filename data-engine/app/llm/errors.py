class LLMError(RuntimeError):
    """Base error for provider-neutral LLM operations."""


class ProviderDisabledError(LLMError):
    pass


class ProviderRequestError(LLMError):
    pass


class ProviderHTTPError(LLMError):
    def __init__(self, provider: str, status_code: int) -> None:
        self.provider = provider
        self.status_code = status_code
        super().__init__(f"{provider} request failed with HTTP {status_code}")


class ProviderResponseError(LLMError):
    pass


class ProviderEmptyResponseError(ProviderResponseError):
    """El proveedor respondio 200 pero sin texto ni tool calls (cuerpo vacio)."""


class StructuredOutputError(LLMError):
    pass


class ProviderTransportError(LLMError):
    def __init__(self, provider: str, reason: str, attempts: int) -> None:
        allowed = {"read_timeout", "connect_timeout", "write_timeout", "pool_timeout", "timeout", "connect_error", "protocol_error", "transport_error"}
        self.reason = reason if reason in allowed else "transport_error"
        self.attempts = attempts
        super().__init__(f"{provider} transport failed: {self.reason} after {attempts} attempt(s)")
