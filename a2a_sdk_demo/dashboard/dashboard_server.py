"""Dashboard Server — run this first to see the empty landscape.

Starts the SSE dashboard on port 8080 and opens the browser.
Then run `python -m a2a_sdk_demo.chat` in another terminal
to start sending events.

Usage:
    python -m a2a_sdk_demo.dashboard.dashboard_server
"""

from __future__ import annotations

import webbrowser
import threading

import uvicorn

from a2a_sdk_demo.dashboard.event_bus import app


def main() -> None:
    port = 8080
    print(f"🍕 A2A Flow Visualizer — http://127.0.0.1:{port}")
    print(f"   Open the browser and then run 'python -m a2a_sdk_demo.chat' in another terminal.\n")

    # Open browser after a short delay
    def open_browser():
        import time
        time.sleep(1)
        webbrowser.open(f"http://127.0.0.1:{port}")

    threading.Thread(target=open_browser, daemon=True).start()

    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
