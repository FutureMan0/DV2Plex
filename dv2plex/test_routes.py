"""The interface talks to exactly these routes; splitting the server into modules must keep them."""

from dv2plex import web_app

EXPECTED_ROUTES = {
    ("/", "GET"),
    ("/api/browse", "GET"),
    ("/api/capture/pause", "POST"),
    ("/api/capture/play", "POST"),
    ("/api/capture/rewind", "POST"),
    ("/api/capture/start", "POST"),
    ("/api/capture/stop", "POST"),
    ("/api/chown", "POST"),
    ("/api/cover/extract", "POST"),
    ("/api/cover/generate", "POST"),
    ("/api/cover/videos", "GET"),
    ("/api/fix-config-permissions", "POST"),
    ("/api/info", "GET"),
    ("/api/logs", "GET"),
    ("/api/logs/clear", "POST"),
    ("/api/merge/queue", "GET"),
    ("/api/movie/export", "POST"),
    ("/api/movie/export-all", "POST"),
    ("/api/movie/list", "GET"),
    ("/api/movie/merge", "POST"),
    ("/api/player/poster", "GET"),
    ("/api/player/projects", "GET"),
    ("/api/player/rename", "POST"),
    ("/api/player/stream", "GET"),
    ("/api/poster/generate", "POST"),
    ("/api/poster/generate-batch", "POST"),
    ("/api/postprocess/list", "GET"),
    ("/api/postprocess/process", "POST"),
    ("/api/project/delete", "POST"),
    ("/api/settings", "GET"),
    ("/api/settings", "POST"),
    ("/api/status", "GET"),
    ("/api/update/run", "POST"),
    ("/api/update/status", "GET"),
    ("/api/upscaling/profiles", "GET"),
    ("/ws", "WS"),
}


def _routes():
    found = set()
    for route in web_app.app.routes:
        if not (route.path.startswith("/api") or route.path in ("/", "/ws")):
            continue
        methods = getattr(route, "methods", None) or {"WS"}
        for method in methods:
            if method != "HEAD":
                found.add((route.path, method))
    return found


def test_every_route_the_interface_uses_exists():
    missing = EXPECTED_ROUTES - _routes()
    assert not missing, f"routes lost: {sorted(missing)}"
