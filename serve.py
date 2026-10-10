"""Usage: python serve.py [port] [--no-browser]
Starts the AgentFactory web page on this computer only (127.0.0.1)."""
import sys
import threading
import webbrowser

import uvicorn

from factory.server import app


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    try:
        port = int(args[0]) if args else 8010
    except ValueError:
        print(__doc__)
        return 1
    url = f"http://127.0.0.1:{port}"
    if "--no-browser" not in sys.argv:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    print(f"AgentFactory is running at {url}  (press Ctrl+C to stop)")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
