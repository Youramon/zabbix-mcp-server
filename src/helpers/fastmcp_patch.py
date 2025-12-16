"""
Runtime patch to make FastMCP tolerant to unknown tool arguments (e.g., toolCallId from some clients).

This patches fastmcp.tools.tool.FunctionTool.run to drop any keys not present in the
underlying function's signature before FastMCP/Pydantic validation runs. This prevents
ValidationError: unexpected keyword argument <name> while keeping strict typing for known args.

Safe to import multiple times; the patch will simply overwrite the method once.
"""
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict

try:
    from fastmcp.tools.tool import FunctionTool  # type: ignore
except Exception as e:  # pragma: no cover - defensive: FastMCP not installed/changed API
    raise RuntimeError("Failed to import FunctionTool from fastmcp; API may have changed.") from e

log = logging.getLogger("zammad_mcp.arg_sanitizer")

# Keep a reference to the original implementation
_original_run = getattr(FunctionTool, "run", None)

if _original_run is None:
    raise RuntimeError("fastmcp.tools.tool.FunctionTool.run was not found; incompatible FastMCP version?")


async def _run_with_arg_sanitizer(self: FunctionTool, arguments: Dict[str, Any]) -> Any:  # type: ignore[override]
    """Sanitize tool arguments before invoking FastMCP's validator.

    - Only strips keys not in the wrapped function's signature.
    - Leaves non-dict payloads untouched (delegate to original).
    - Caches allowed parameter names per instance for performance.
    """
    # If the payload isn't a mapping, delegate unchanged
    if not isinstance(arguments, dict):
        return await _original_run(self, arguments)  # type: ignore[misc]

    # Build and cache the whitelist of valid parameter names
    if not hasattr(self, "_allowed_parameter_names"):
        signature = inspect.signature(self.fn)
        self._allowed_parameter_names = tuple(signature.parameters.keys())  # type: ignore[attr-defined]

    allowed = getattr(self, "_allowed_parameter_names")  # type: ignore[attr-defined]
    sanitized = {k: v for k, v in arguments.items() if k in allowed}

    if len(sanitized) != len(arguments):
        removed = sorted(set(arguments.keys()) - set(allowed))
        tool_name = getattr(self, "name", getattr(self.fn, "__name__", "<unknown>"))
        log.debug("Dropped unsupported fields for tool '%s': %s", tool_name, removed)

    return await _original_run(self, sanitized)  # type: ignore[misc]


# Apply the monkey patch
FunctionTool.run = _run_with_arg_sanitizer  # type: ignore[assignment]
