"""Local web server for the gallery. Same as `python -m http.server`, but tells the browser to
revalidate every file (Cache-Control: no-cache), so updated pages, scripts and data always load
instead of stale cached copies. Unchanged files still come back as fast 304 responses.

It also stops by itself once no gallery page is open: each open page pings /__ping every 20 s
(js/keepalive.js), and the server exits after IDLE_EXIT seconds without any request. The limit is
generous because Chrome slows timers in background tabs to about once a minute.

Usage: python serve.py [port] [--stay]   (serves the folder above this one, on 127.0.0.1;
                                          --stay keeps it running until you close the window)
"""
import functools, http.server, os, sys, threading, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARGS = [a for a in sys.argv[1:] if not a.startswith('--')]
PORT = int(ARGS[0]) if ARGS else 8765
STAY = '--stay' in sys.argv
IDLE_EXIT = 90        # seconds without any request once pages have stopped pinging
FIRST_PAGE = 120      # how long to wait for the first page after starting

last_activity = time.monotonic() + FIRST_PAGE - IDLE_EXIT
busy = 0              # requests in progress (a long video download counts as activity)
lock = threading.Lock()


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      '.js': 'text/javascript', '.mjs': 'text/javascript', '.glb': 'model/gltf-binary',
                      '.webm': 'video/webm', '.ogg': 'audio/ogg', '.webp': 'image/webp', '.woff2': 'font/woff2'}

    def tracked(fn):
        def run(self):
            global last_activity, busy
            with lock: busy += 1; last_activity = time.monotonic()
            try:
                fn(self)
            finally:
                with lock: busy -= 1; last_activity = time.monotonic()
        return run

    @tracked
    def do_GET(self):
        if self.path.split('?')[0] == '/__ping':   # keep-alive from an open page
            self.send_response(204)
            self.end_headers()
            return
        super().do_GET()

    do_HEAD = tracked(http.server.SimpleHTTPRequestHandler.do_HEAD)

    def end_headers(self):
        self.send_header('Cache-Control', 'no-cache')
        super().end_headers()

    def log_message(self, *args):   # keep the console quiet
        pass


def watch_idle(server):
    while True:
        time.sleep(5)
        with lock:
            idle = busy == 0 and time.monotonic() - last_activity > IDLE_EXIT
        if idle:
            print('No gallery page open - stopping. (Open Gallery.bat starts it again.)')
            server.shutdown()
            return


if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), functools.partial(Handler, directory=ROOT))
    server.daemon_threads = True
    if STAY:
        print(f'Serving {ROOT} at http://127.0.0.1:{PORT}/  (close this window to stop)')
    else:
        print(f'Serving {ROOT} at http://127.0.0.1:{PORT}/')
        print('This window closes by itself shortly after the last gallery tab is closed.')
        threading.Thread(target=watch_idle, args=(server,), daemon=True).start()
    server.serve_forever()
