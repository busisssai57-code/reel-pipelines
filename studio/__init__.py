"""BTA Automation Studio: monitor and control the pipelines.

In-process, alongside a running stream — this is the intended use, because the
order and inventory stores live in memory and a separate process cannot see
them::

    from studio import launch

    studio = launch(pipeline.commerce, names=cfg.commerce.sku_names)
    log.info("Studio at %s", studio.url)
    ...
    studio.stop()

Standalone, to look at the interface before going live::

    python -m studio --demo
"""

from .api import ApiResponse, StudioAPI
from .server import DEFAULT_HOST, DEFAULT_PORT, StudioServer, is_loopback, serve
from .state import ActivityEntry, StudioState, describe_lines
from .ui import PAGE

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "PAGE",
    "ActivityEntry",
    "ApiResponse",
    "StudioAPI",
    "StudioServer",
    "StudioState",
    "describe_lines",
    "is_loopback",
    "launch",
    "serve",
]


def resolve_service(source):
    """Accept a ``FulfillmentService`` or anything exposing one as ``.service``.

    ``CommerceBridge`` holds its service as a public attribute precisely so the
    studio can reach through it, and taking either keeps this package free of
    any import from ``bta``.
    """
    service = getattr(source, "service", source)
    if not hasattr(service, "session_summary"):
        raise TypeError(
            "expected a FulfillmentService or an object exposing one as .service, "
            f"got {type(source).__name__}"
        )
    return service


def launch(
    source,
    *,
    session_id: str | None = None,
    names=None,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    read_only: bool = False,
    on_log=None,
    warn=None,
) -> StudioServer:
    """Attach a studio to a live service or bridge and start serving.

    Reads ``session_id`` from the bridge when one is not given, so the studio
    scopes to the broadcast already in progress.
    """
    service = resolve_service(source)
    if session_id is None:
        session_id = getattr(source, "session_id", None) or "live"
    state = StudioState(service, session_id=session_id, names=names)
    state.attach()
    return serve(
        state, host=host, port=port, read_only=read_only, on_log=on_log, warn=warn
    )
