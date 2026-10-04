"""Local web server for the gallery. Same as `python -m http.server`, but tells the browser to
revalidate every file (Cache-Control: no-cache), so updated pages, scripts and data always load
instead of stale cached copies. Unchanged files still come back as fast 304 responses.

Usage: python serve.py [port]   (serves the folder above this one, on 127.0.0.1)
"""
import functools, http.server, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.js': 'text/javascript', '.mjs': 'text/javascript', '.glb': 'model/gltf-binary',
                      '.webm': 'video/webm', '.ogg': 'audio/ogg', '.webp': 'image/webp', '.woff2': 'font/woff2'}

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, *args):   # keep the console quiet
        pass


if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), functools.partial(Handler, directory=ROOT))
    print(f'Serving {ROOT} at http://127.0.0.1:{PORT}/  (close this window to stop)')
    server.serve_forever()
