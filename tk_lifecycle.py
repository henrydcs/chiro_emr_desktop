# tk_lifecycle.py
"""Bind Tk subscriptions to a widget's lifetime.

Use `trace_for_lifetime` whenever a widget wants to `trace_add` on a
`tk.Variable` whose lifetime exceeds the widget's own — typically an
app-level variable consumed by a transient page/section that the user
can add, rename, or delete at runtime.

Without lifetime-bound cleanup, a destroyed widget's callback keeps
firing on every subsequent write to the variable, raising
`_tkinter.TclError: invalid command name` against the now-dead Tk
widget — and the noise grows linearly with every add/rename/delete.

This module is intentionally tiny and Tk-only; it does not depend on
anything project-specific so any widget in this codebase can import it.
"""
from __future__ import annotations

import tkinter as tk
from typing import Callable


# Attribute name we attach to widgets to hold their registered traces.
# Underscored to discourage external code from touching it directly.
_BUCKET_ATTR = "_lifetime_traces"


def trace_for_lifetime(
    widget: tk.Misc,
    var: tk.Variable,
    mode: str,
    callback: Callable,
) -> str:
    """Register `callback` on `var` via `trace_add(mode, ...)` and
    automatically `trace_remove` it when `widget` is destroyed.

    Parameters
    ----------
    widget : tk.Misc
        The Tk widget whose destruction should release the trace.  The
        first call for a given widget also installs a single
        `<Destroy>` binding that drains every trace registered through
        this helper.
    var : tk.Variable
        The Tk variable to subscribe to (DoubleVar / StringVar / IntVar
        / BooleanVar — anything supporting `trace_add` / `trace_remove`).
    mode : str
        Standard `trace_add` mode: "read", "write", "unset", or "array".
    callback : Callable
        The trace callback.  Same signature contract as `trace_add`.

    Returns
    -------
    str
        The Tk trace token.  Rarely needed — only useful if the caller
        wants to remove the trace earlier than widget destruction.
    """
    token = var.trace_add(mode, callback)
    bucket = getattr(widget, _BUCKET_ATTR, None)
    if bucket is None:
        bucket = []
        setattr(widget, _BUCKET_ATTR, bucket)
        widget.bind(
            "<Destroy>",
            lambda _e, w=widget: _drain_traces(w),
            add="+",
        )
    bucket.append((var, mode, token))
    return token


def _drain_traces(widget: tk.Misc) -> None:
    """Remove every trace registered for `widget`.  Safe to call more
    than once — the bucket is cleared after the first drain so repeat
    invocations are no-ops.
    """
    bucket = getattr(widget, _BUCKET_ATTR, None)
    if not bucket:
        return
    for var, mode, token in bucket:
        try:
            var.trace_remove(mode, token)
        except Exception:
            # `var` may have been destroyed, or the trace was already
            # removed by something else — either way there is nothing
            # left to clean up here.
            pass
    bucket.clear()
