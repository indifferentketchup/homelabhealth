"""Lifecycle hook runner  -  PreToolUse, PostToolUse, Stop, UserPromptSubmit.

Mirrors boocode's hooks.ts pattern using Python's contextvars for ambient
context (equivalent to AsyncLocalStorage) and a simple callback registry.

Hook signatures:
  - pre_tool_execution(tool_name, input, ctx) -> HookResult
  - post_tool_execution(tool_name, input, output, ctx, duration_ms)
  - on_stop(reason, ctx)
  - on_user_prompt(prompt, ctx)

Zero external dependencies  -  pure Python stdlib + contextvars.
"""

import contextvars
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class HookContext:
    """Ambient per-request context carried by contextvars (cf. AsyncLocalStorage)."""
    chat_id: str | None = None
    message_id: str | None = None
    user_id: str | None = None
    workspace_id: str | None = None
    request_id: str | None = None


_hook_context: contextvars.ContextVar[HookContext] = contextvars.ContextVar(
    "hook_context", default=HookContext()
)


def get_hook_context() -> HookContext:
    """Retrieve the current request's HookContext (or an empty default)."""
    return _hook_context.get()


def set_hook_context(ctx: HookContext) -> contextvars.Token[HookContext]:
    """Set the ambient HookContext for this request. Returns a token for
    later reset."""
    return _hook_context.set(ctx)


def reset_hook_context(token: contextvars.Token[HookContext]) -> None:
    """Restore a previous HookContext (use at end of request scope)."""
    _hook_context.reset(token)


@dataclass
class HookResult:
    """Returned by pre_tool_execution hooks. When blocked=True the chain
    stops immediately  -  no further pre-tool callbacks run and the tool
    execution is skipped."""
    blocked: bool = False
    reason: str | None = None


HookName = str
"""One of 'pre_tool_execution', 'post_tool_execution', 'on_stop', 'on_user_prompt'."""

# Callback type aliases (informational  -  runtime duck-typing):
#   PreToolCallback:    Callable[[str, dict, HookContext], Awaitable[HookResult | None]]
#   PostToolCallback:   Callable[[str, dict, Any, HookContext, float], Awaitable[None]]
#   StopCallback:       Callable[[str, HookContext], Awaitable[None]]
#   UserPromptCallback: Callable[[str, HookContext], Awaitable[None]]

_registry: dict[HookName, list[Any]] = {
    "pre_tool_execution": [],
    "post_tool_execution": [],
    "on_stop": [],
    "on_user_prompt": [],
}


def register(name: HookName, callback: Any) -> None:
    """Register a callback for the given hook point. Append-only; callbacks
    run in registration order. Idempotent at the caller's discretion."""
    if name not in _registry:
        raise ValueError(f"Unknown hook point: {name!r}")
    _registry[name].append(callback)
    logger.debug("hook registered: %s (%d callbacks)", name, len(_registry[name]))


def deregister(name: HookName, callback: Any) -> None:
    """Remove a previously registered callback. Silent if not found."""
    if name not in _registry:
        raise ValueError(f"Unknown hook point: {name!r}")
    try:
        _registry[name].remove(callback)
    except ValueError:
        pass


def list_callbacks(name: HookName) -> list[Any]:
    """Return a snapshot of registered callbacks for the given hook point."""
    return list(_registry.get(name, []))


async def fire_pre_tool_execution(
    tool_name: str,
    tool_input: dict[str, Any],
    ctx: HookContext | None = None,
) -> HookResult:
    """Run all registered pre_tool_execution callbacks in order.

    If any callback returns a HookResult with blocked=True, the chain
    stops immediately and the blocking result is returned.
    Errors in individual callbacks are logged and do not crash the chain.
    When no callbacks are registered, returns HookResult() (pass) immediately.
    """
    ctx = ctx or get_hook_context()
    callbacks = _registry["pre_tool_execution"]
    if not callbacks:
        return HookResult()
    for cb in callbacks:
        try:
            result = await cb(tool_name, tool_input, ctx)
            if result is not None and result.blocked:
                return result
        except Exception:
            logger.exception("hook pre_tool_execution failed")
    return HookResult()


async def fire_post_tool_execution(
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output: Any,
    ctx: HookContext | None = None,
    duration_ms: float = 0.0,
) -> None:
    """Run all registered post_tool_execution callbacks in order.

    Errors in individual callbacks are logged and do not affect other
    callbacks or the caller. No-op when no callbacks are registered.
    """
    ctx = ctx or get_hook_context()
    callbacks = _registry["post_tool_execution"]
    if not callbacks:
        return
    for cb in callbacks:
        try:
            await cb(tool_name, tool_input, tool_output, ctx, duration_ms)
        except Exception:
            logger.exception("hook post_tool_execution failed")


async def fire_on_stop(
    reason: str,
    ctx: HookContext | None = None,
) -> None:
    """Run all registered on_stop callbacks. No-op when no callbacks."""
    ctx = ctx or get_hook_context()
    callbacks = _registry["on_stop"]
    if not callbacks:
        return
    for cb in callbacks:
        try:
            await cb(reason, ctx)
        except Exception:
            logger.exception("hook on_stop failed")


async def fire_on_user_prompt(
    prompt: str,
    ctx: HookContext | None = None,
) -> None:
    """Run all registered on_user_prompt callbacks. No-op when no callbacks."""
    ctx = ctx or get_hook_context()
    callbacks = _registry["on_user_prompt"]
    if not callbacks:
        return
    for cb in callbacks:
        try:
            await cb(prompt, ctx)
        except Exception:
            logger.exception("hook on_user_prompt failed")
