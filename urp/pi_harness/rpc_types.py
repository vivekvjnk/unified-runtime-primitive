from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class PiRpcError(Exception):
    """Base exception for Pi RPC errors."""
    pass


class PiRpcConnectionError(PiRpcError):
    """Raised when connection to pi RPC subprocess fails or is lost."""
    pass


class PiRpcProcessTerminatedError(PiRpcConnectionError):
    """Raised when pi RPC subprocess terminates unexpectedly."""
    pass


class PiRpcCommandError(PiRpcError):
    """Raised when an RPC command returns success=False."""
    def __init__(self, command: str, error_message: str, response_data: Optional[Dict[str, Any]] = None):
        self.command = command
        self.error_message = error_message
        self.response_data = response_data or {}
        super().__init__(f"Command '{command}' failed: {error_message}")


class PiRpcTimeoutError(PiRpcError):
    """Raised when an RPC command times out waiting for response."""
    pass


@dataclass
class RpcCommand:
    type: str
    id: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {"type": self.type}
        if self.id is not None:
            payload["id"] = self.id
        payload.update(self.params)
        return payload


@dataclass
class RpcResponse:
    command: str
    success: bool
    id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RpcResponse":
        raw_data = data.get("data")
        if raw_data is None:
            parsed_data = {}
        elif isinstance(raw_data, dict):
            parsed_data = raw_data
        else:
            parsed_data = {"value": raw_data}

        return cls(
            command=data.get("command", ""),
            success=data.get("success", False),
            id=data.get("id"),
            data=parsed_data,
            error=data.get("error"),
            raw=data,
        )


@dataclass
class RpcEvent:
    type: str
    data: Dict[str, Any] = field(default_factory=dict)
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RpcEvent":
        event_type = data.get("type", "unknown")
        payload = {k: v for k, v in data.items() if k != "type"}
        return cls(type=event_type, data=payload, raw=data)


@dataclass
class ExtensionUiRequest:
    id: str
    method: str
    title: Optional[str] = None
    message: Optional[str] = None
    options: Optional[List[str]] = None
    placeholder: Optional[str] = None
    prefill: Optional[str] = None
    timeout: Optional[int] = None
    raw: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExtensionUiRequest":
        return cls(
            id=data.get("id", ""),
            method=data.get("method", ""),
            title=data.get("title"),
            message=data.get("message"),
            options=data.get("options"),
            placeholder=data.get("placeholder"),
            prefill=data.get("prefill"),
            timeout=data.get("timeout"),
            raw=data,
        )


@dataclass
class ExtensionUiResponse:
    id: str
    value: Optional[Any] = None
    confirmed: Optional[bool] = None
    cancelled: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "type": "extension_ui_response",
            "id": self.id,
        }
        if self.cancelled:
            payload["cancelled"] = True
        elif self.confirmed is not None:
            payload["confirmed"] = self.confirmed
        else:
            payload["value"] = self.value
        return payload
