from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class MessageRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class Message:
    role: MessageRole | str
    content: str
    tool_calls: Sequence[ToolCall] = ()
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        try:
            role = self.role if isinstance(self.role, MessageRole) else MessageRole(self.role)
        except ValueError as exc:
            raise ValueError(f"Unsupported message role: {self.role!r}") from exc
        if not isinstance(self.content, str):
            raise ValueError("Message content must be a string")
        # Un turno assistant puede NO traer texto: cuando el modelo responde
        # solo con `tool_calls`, el contrato OpenAI deja `content` a null y el
        # contenido vive en `LLMResponse.tool_calls`. Rechazar el texto vacio
        # ahi convertia un tool call legitimo en un error de proveedor falso.
        # Los roles de entrada (system/user) siguen exigiendo texto: un prompt
        # con un mensaje vacio no aporta nada al modelo.
        if role is not MessageRole.ASSISTANT and not self.content.strip():
            raise ValueError("Message content must be a non-empty string")
        object.__setattr__(self, "role", role)
        calls = tuple(self.tool_calls)
        if any(not isinstance(call, ToolCall) for call in calls):
            raise TypeError("Message.tool_calls must contain ToolCall instances")
        if calls and role is not MessageRole.ASSISTANT:
            raise ValueError("Only assistant messages may declare tool calls")
        if role is MessageRole.TOOL:
            if not isinstance(self.tool_call_id, str) or not self.tool_call_id.strip():
                raise ValueError("Tool results require tool_call_id")
        elif self.tool_call_id is not None:
            raise ValueError("Only tool messages may carry tool_call_id")
        object.__setattr__(self, "tool_calls", calls)

    def to_openai(self) -> dict[str, Any]:
        result: dict[str, Any] = {"role": MessageRole(self.role).value, "content": self.content}
        if self.tool_calls:
            result["content"] = self.content or None
            result["tool_calls"] = [call.to_openai() for call in self.tool_calls]
        if self.tool_call_id is not None:
            result["tool_call_id"] = self.tool_call_id
        return result


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Una funcion que el modelo puede pedir.

    Solo describe el contrato (nombre, descripcion y JSON Schema de
    parametros): el adaptador la traduce al sobre OpenAI. GerarAI no registra
    ninguna tool con efectos laterales; este dataclass es el mecanismo
    generico para que un caller registre una lectura acotada cuando lo necesite.
    """

    name: str
    description: str = ""
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("Tool name must be a non-empty string")
        if not isinstance(self.description, str):
            raise ValueError("Tool description must be a string")
        if not isinstance(self.parameters, Mapping):
            raise TypeError("Tool parameters must be a mapping (JSON Schema object)")
        object.__setattr__(self, "name", self.name.strip())

    def to_openai(self) -> dict[str, Any]:
        """Envelope OpenAI `tools: [{"type": "function", "function": {...}}]`."""
        parameters: Mapping[str, Any] = self.parameters or {"type": "object", "properties": {}}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": dict(parameters),
            },
        }


@dataclass(frozen=True, slots=True)
class ToolCall:
    """Un tool call ya validado por el adaptador.

    ``arguments`` SIEMPRE es un mapping, nunca el string crudo del proveedor:
    la garantia de que el JSON de argumentos parsea se aplica en la
    construccion, no como promesa del docs. Un tool call que no se puede
    interpretar es un error de contrato del proveedor, no algo que se pueda
    descartar en silencio (el caller creeria que el modelo respondio con texto).
    """

    id: str
    name: str
    arguments: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("ToolCall.name must be a non-empty string")
        if not isinstance(self.arguments, Mapping):
            raise TypeError("ToolCall.arguments must be a JSON object, not raw text")
        object.__setattr__(self, "name", self.name.strip())
        object.__setattr__(self, "id", str(self.id or f"call_{self.name.strip()}"))

    def to_openai(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(dict(self.arguments), ensure_ascii=False, allow_nan=False),
            },
        }


@dataclass(frozen=True, slots=True)
class ResponseFormat:
    type: str = "json_object"
    schema: Mapping[str, Any] | None = None
    name: str = "response"
    strict: bool = True

    def __post_init__(self) -> None:
        if self.type not in {"json_object", "json_schema"}:
            raise ValueError("Response format type must be 'json_object' or 'json_schema'")
        if self.type == "json_schema" and self.schema is None:
            raise ValueError("A schema is required for json_schema responses")

    @classmethod
    def json_object(cls) -> ResponseFormat:
        return cls(type="json_object")

    @classmethod
    def json_schema(
        cls,
        schema: Mapping[str, Any],
        *,
        name: str = "response",
        strict: bool = True,
    ) -> ResponseFormat:
        return cls(type="json_schema", schema=schema, name=name, strict=strict)


#: Valores de `tool_choice` de primer nivel que acepta el contrato OpenAI.
TOOL_CHOICE_VALUES = frozenset({"auto", "none", "required"})


@dataclass(frozen=True, slots=True)
class LLMRequest:
    messages: Sequence[Message]
    task: str | None = None
    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    response_format: ResponseFormat | None = None
    materiality_score: int = 0
    portfolio_weight: float = 0.0
    metadata: Mapping[str, str] = field(default_factory=dict)
    #: Tools que el modelo puede pedir. Vacio = sin tool calling.
    tools: Sequence[ToolDefinition] = ()
    #: `auto` | `none` | `required` o `{"type": "function", "function": {...}}`.
    tool_choice: str | Mapping[str, Any] | None = None
    #: `False` marca la respuesta como NO cacheable (dato efimero).
    #: `None` =politica por defecto de la cache de respuestas.
    cache: bool | None = None
    #: Override de effort por request (p. ej. "none" para rutas estructuradas
    #: largas donde el razonamiento oculto consume el presupuesto de salida).
    #: None = el default del proveedor. Solo lo reenvian los adaptadores con
    #: capacidad `reasoning` y solo a los modelos de reasoning_effort_models.
    reasoning_effort: str | None = None

    def __post_init__(self) -> None:
        messages = tuple(self.messages)
        if not messages:
            raise ValueError("At least one message is required")
        if any(not isinstance(message, Message) for message in messages):
            raise TypeError("All messages must be Message instances")
        if self.temperature is not None and not 0 <= self.temperature <= 2:
            raise ValueError("temperature must be between 0 and 2")
        if self.max_tokens is not None and self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.reasoning_effort is not None:
            if not isinstance(self.reasoning_effort, str):
                raise TypeError("reasoning_effort must be a string")
            if not self.reasoning_effort.strip():
                raise ValueError("reasoning_effort must be non-empty")
        if not 0 <= self.materiality_score <= 10:
            raise ValueError("materiality_score must be between 0 and 10")
        if not 0 <= self.portfolio_weight <= 1:
            raise ValueError("portfolio_weight must be between 0 and 1")
        tools = tuple(self.tools)
        if any(not isinstance(tool, ToolDefinition) for tool in tools):
            raise TypeError("All tools must be ToolDefinition instances")
        names = {tool.name for tool in tools}
        if len(names) != len(tools):
            raise ValueError("Tool names must be unique within a request")
        self._validate_tool_choice(tools, names)
        pending: set[str] = set()
        seen: set[str] = set()
        for message in messages:
            if message.role is MessageRole.TOOL:
                call_id = message.tool_call_id
                if call_id is None or call_id not in pending:
                    raise ValueError("Orphan or repeated tool result")
                pending.remove(call_id)
            else:
                if pending:
                    raise ValueError("Missing tool results before next message")
                for call in message.tool_calls:
                    if call.id in seen:
                        raise ValueError("Repeated tool call ID")
                    seen.add(call.id)
                    pending.add(call.id)
        if pending:
            raise ValueError("Missing tool results")
        object.__setattr__(self, "messages", messages)
        object.__setattr__(self, "tools", tools)

    def _validate_tool_choice(self, tools: tuple[ToolDefinition, ...], names: set[str]) -> None:
        choice = self.tool_choice
        if choice is None:
            return
        if not tools:
            raise ValueError("tool_choice requires at least one tool")
        if isinstance(choice, str):
            if choice not in TOOL_CHOICE_VALUES:
                raise ValueError("tool_choice must be 'auto', 'none', 'required' or a named function")
            return
        if not isinstance(choice, Mapping):
            raise TypeError("tool_choice must be a string or a mapping")
        function = choice.get("function") if isinstance(choice.get("function"), Mapping) else choice
        named = function.get("name") if isinstance(function, Mapping) else None
        if not isinstance(named, str) or named not in names:
            raise ValueError("tool_choice names a function that is not in tools")


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    #: Tokens de razonamiento oculto (completion_tokens_details.reasoning_tokens).
    #: Diagnostico puro: OpenCode Go lo expone; 0 si el proveedor no lo informa.
    reasoning_tokens: int = 0

    def __post_init__(self) -> None:
        if (
            min(
                self.input_tokens,
                self.output_tokens,
                self.total_tokens,
                self.cache_read_tokens,
                self.cache_write_tokens,
                self.reasoning_tokens,
            )
            < 0
        ):
            raise ValueError("Token usage cannot be negative")


@dataclass(frozen=True, slots=True)
class LLMResponse:
    message: Message
    usage: Usage
    model: str
    provider: str
    finish_reason: str | None = None
    request_id: str | None = None
    #: Tool calls pedidos por el modelo, ya validados. Vacio = respuesta de texto.
    tool_calls: tuple[ToolCall, ...] = ()
    #: Respuesta marcada como degradada por el proveedor (warning, truncado,
    #: filtro de contenido). Una respuesta degradada NUNCA se cachea: servirla
    #: despues congelaria el defecto. Ver app/llm/response_cache.py.
    degraded: bool = False
    #: Avisos del proveedor, redactados. Cualquier aviso marca `degraded`.
    warnings: tuple[str, ...] = ()
    #: True si la respuesta se sirvio desde la cache de respuestas (no hubo
    #: llamada al proveedor y por tanto no se gasto presupuesto).
    from_cache: bool = False
    #: Clave de cache que produjo la respuesta (hash sha256, sin secretos).
    cache_key: str | None = None
    #: Miembros que se probaron y FALLARON antes de esta respuesta ("proveedor:modelo:
    #: ClaseDeError"), sin mensajes ni URLs. Vacio = respondio el primero. NO es un
    #: aviso del proveedor: no marca `degraded`.
    fallback_trail: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "tool_calls", tuple(self.tool_calls))
        object.__setattr__(self, "fallback_trail", tuple(str(t) for t in self.fallback_trail))
        object.__setattr__(self, "warnings", tuple(str(w) for w in self.warnings))
        if any(not isinstance(call, ToolCall) for call in self.tool_calls):
            raise TypeError("All tool_calls must be ToolCall instances")
        if self.warnings and not self.degraded:
            object.__setattr__(self, "degraded", True)

    @property
    def text(self) -> str:
        return self.message.content

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


LLMMessage = Message
LLMUsage = Usage
