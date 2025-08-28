import threading
import time
import webbrowser
import socket

import uvicorn


def _is_port_open(host: str, port: int, timeout: float = 0.25) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect((host, port))
            return True
        except Exception:
            return False


def _run_server(config: uvicorn.Config, server_ready: threading.Event):
    server = uvicorn.Server(config)

    # Expose server to config so we can signal shutdown later if needed
    config.loaded_app = None  # placeholder attribute for clarity

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
        # Restore in case
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

    # Start server in a background thread
    server_ready = threading.Event()
    server_thread = threading.Thread(target=_run_server, args=(config, server_ready), daemon=True)
    server_thread.start()

    # Wait for server to come up
    url_scheme = "https" if ("ssl_certfile" in uvicorn_kwargs) else "http"
    base_url = f"{url_scheme}://{args.host}:{args.port}"
    for _ in range(200):  # wait up to ~10s
        if server_ready.is_set() or _is_port_open(args.host, args.port):
            break
        time.sleep(0.05)

    # Try to open an embedded window via pywebview; fall back to browser
    try:
        import webview  # type: ignore

        # Create and run the window; blocks until closed
        webview.create_window("WhisperLiveKit", base_url, width=980, height=740)
        webview.start()
    except Exception:
        # Fallback: open default browser
        webbrowser.open(base_url)
        try:
            # Keep process alive while server runs; Ctrl+C to exit
            while server_thread.is_alive():
                time.sleep(0.2)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()

