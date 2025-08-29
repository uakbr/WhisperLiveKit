import threading
import time
import webbrowser
import socket
import os

import uvicorn


def _is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except Exception:
            return False


def _run_server(server: uvicorn.Server, server_ready: threading.Event):
    # Run the server; when started, set the event
    def _startup_notify():
        server_ready.set()
    # Monkey-patch install_signal_handlers to avoid interfering with GUI loop
    original_install = server.install_signal_handlers
    server.install_signal_handlers = lambda: None
    # Wrap startup to notify readiness
    original_startup = server.startup
    async def startup_wrapper():
        await original_startup()
        _startup_notify()
    server.startup = startup_wrapper  # type: ignore
    try:
        server.run()
    finally:
        server.install_signal_handlers = original_install


def main():
    """
    Launch WhisperLiveKit server and open a desktop window for the web UI.

    If pywebview is available (via `pip install whisperlivekit[gui]`), a native window is opened.
    Otherwise, the default browser is opened.
    """
    # Defer heavy imports to keep CLI responsive
    from whisperlivekit.parse_args import parse_args

    args = parse_args()
    # For GUI, default to disabling VAC to avoid heavy torch.hub downloads
    # unless explicitly enabled by environment variable.
    if not os.environ.get("WLK_GUI_ENABLE_VAC"):
        setattr(args, "no_vac", True)

    # Configure uvicorn to serve the existing FastAPI app
    uvicorn_kwargs = {
        "app": "whisperlivekit.basic_server:app",
        "host": args.host,
        "port": args.port,
        "reload": False,
        "log_level": "info",
        "lifespan": "on",
    }

    if args.ssl_certfile or args.ssl_keyfile:
        if not (args.ssl_certfile and args.ssl_keyfile):
            raise ValueError("Both --ssl-certfile and --ssl-keyfile must be specified together.")
        uvicorn_kwargs.update({
            "ssl_certfile": args.ssl_certfile,
            "ssl_keyfile": args.ssl_keyfile,
        })

    config = uvicorn.Config(**uvicorn_kwargs)
    server = uvicorn.Server(config)

    # Start server in a background thread
    server_ready = threading.Event()
    server_thread = threading.Thread(target=_run_server, args=(server, server_ready), daemon=True)
    server_thread.start()

    # Wait for server to come up
    url_scheme = "https" if ("ssl_certfile" in uvicorn_kwargs) else "http"
    display_host = "localhost" if args.host in ("0.0.0.0", "::", "0:0:0:0:0:0:0:0") else args.host
    base_url = f"{url_scheme}://{display_host}:{args.port}"
    probe_host = "127.0.0.1" if args.host in ("0.0.0.0", "::", "0:0:0:0:0:0:0:0") else args.host
    for _ in range(200):  # wait up to ~10s
        if server_ready.is_set() or _is_port_open(probe_host, args.port):
            break
        time.sleep(0.05)

    # Try to open an embedded window via pywebview; fall back to browser
    try:
        import webview  # type: ignore

        # Create a small loading page first, then swap to the app when ready
        LOADER_HTML = """
        <!doctype html>
        <html>
        <head><meta charset='utf-8'><title>WhisperLiveKit</title>
        <style>body{font-family:-apple-system,system-ui,Segoe UI,Roboto,Ubuntu;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
        .wrap{color:#333;text-align:center}.spin{width:28px;height:28px;border:3px solid #ddd;border-top-color:#333;border-radius:50%;animation:spin 0.9s linear infinite;margin:0 auto 12px}
        @keyframes spin{to{transform:rotate(360deg)}}
        .sub{color:#666;font-size:13px}</style></head>
        <body><div class='wrap'><div class='spin'></div><div>Starting local server…</div>
        <div class='sub'>This may take a few seconds on first run.</div></div></body></html>
        """

        window = webview.create_window("WhisperLiveKit", html=LOADER_HTML, width=980, height=740)

        def _wait_and_load():
            # Wait until the port responds, then navigate
            # Allow generous startup time for first-run model/cache
            for _ in range(1200):  # up to ~120s
                if server_ready.is_set() or _is_port_open(probe_host, args.port):
                    break
                time.sleep(0.1)
            window.load_url(base_url)

        webview.start(_wait_and_load)
    except Exception:
        # Fallback: open default browser
        webbrowser.open(base_url)
        try:
            # Keep process alive while server runs; Ctrl+C to exit
            while server_thread.is_alive():
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass
    finally:
        # Signal server to exit and join thread
        try:
            server.should_exit = True
        except Exception:
            pass
        if server_thread.is_alive():
            server_thread.join(timeout=5)


if __name__ == "__main__":
    main()
