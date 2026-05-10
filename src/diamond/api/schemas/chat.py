"""Schemas for the AI sidebar chat (D33).

The sidebar speaks Anthropic-shaped messages internally (the route's
tool loop emits and consumes them). We surface a simplified shape to
the frontend:

- Each ``ChatTurn`` is one user / assistant message with rich content
  blocks (text + tool_use + tool_result), so the UI can render tool
  calls inline as collapsible cards.
- Each ``ChatRequest`` carries a thread of turns + an optional
  ``page_context`` (URL path + per-page payload, used by Tier 1).
- ``ChatResponse`` returns the appended turns (one assistant turn,
  plus zero-or-more user-tool-result turns produced by the loop).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ChatContentBlock(BaseModel):
    """One content block within a message turn.

    Anthropic's content-block shape, surfaced to the frontend so the
    UI can render text and tool calls / results distinctly.
    """

    type: Literal["text", "tool_use", "tool_result"]
    text: str | None = None
    # tool_use fields
    id: str | None = None
    name: str | None = None
    input: dict[str, Any] | None = None
    # tool_result fields
    tool_use_id: str | None = None
    content: Any | None = None
    # cosmetic — true when a tool returned {"ok": False, ...}
    is_error: bool | None = None


class ChatTurn(BaseModel):
    """One full message in the conversation thread."""

    role: Literal["user", "assistant"]
    content: list[ChatContentBlock]


class PageContext(BaseModel):
    """Optional page-aware context for Tier 1."""

    pathname: str = Field(
        ...,
        description="Current Next.js pathname, e.g. '/player/123' or '/league'.",
    )
    payload: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional structured payload from the current page (player "
            "profile, team summary, etc.). Sent verbatim to the model "
            "as context. Not required — the model can call tools to "
            "look up data on its own."
        ),
    )


class ChatRequest(BaseModel):
    """User-side request: full thread + new user input."""

    messages: list[ChatTurn] = Field(
        default_factory=list,
        description="Existing conversation, oldest first.",
    )
    user_input: str = Field(
        ...,
        description="Latest user message text. Appended as a fresh user turn.",
    )
    page_context: PageContext | None = None
    mode: Literal["chat", "callup", "trade", "draft"] = Field(
        default="chat",
        description=(
            "Tier 3 GM copilot quick-actions. 'chat' is the open-ended "
            "default. The named modes pre-pend a structured prompt "
            "template + suggested tools."
        ),
    )


class ChatResponse(BaseModel):
    """Server appends one assistant turn (which may include tool_use
    blocks the route already executed) plus any user-side tool_result
    turns interleaved by the tool loop. The frontend stitches these
    onto its existing thread.
    """

    appended: list[ChatTurn]
    stop_reason: Literal["end_turn", "tool_use", "max_tokens"]
    iterations: int = Field(
        ...,
        description="Number of provider round-trips this request consumed.",
    )
