"""Local preview with the same annotation API used by Vercel."""
import argparse
import functools
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from api.annotation import handler as APIHandler

ROOT = Path(__file__).resolve().parent


def load_local_env():
    path = ROOT / ".env.local"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if separator and key.strip().startswith("ANNOTATION_"):
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            os.environ.setdefault(key.strip(), value)


class PreviewHandler(SimpleHTTPRequestHandler, APIHandler):
    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path.rstrip("/") == "/api/annotation":
            return APIHandler.do_GET(self)
        if any(part.startswith(".") for part in path.split("/") if part) or path.startswith("/api/"):
            return self.send_error(404)
        return SimpleHTTPRequestHandler.do_GET(self)

    def do_POST(self):
        if urlparse(self.path).path.rstrip("/") != "/api/annotation":
            return self.send_error(404)
        return APIHandler.do_POST(self)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    load_local_env()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), functools.partial(PreviewHandler, directory=str(ROOT)))
    print(f"Annotation website: http://127.0.0.1:{args.port}/annotation/", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
