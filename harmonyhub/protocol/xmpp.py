"""XMPP fallback transport (post-MVP stub).

The MVP uses the WebSocket transport exclusively. XMPP requires explicit
activation on the hub and a one-time cloud token, so it is deliberately out
of scope until someone needs it.
"""

from __future__ import annotations


class XmppNotImplementedError(NotImplementedError):
    """Raised when callers try to use the XMPP transport in the MVP."""


def connect(*_args: object, **_kwargs: object) -> None:
    raise XmppNotImplementedError("XMPP transport is not implemented in the MVP.")
