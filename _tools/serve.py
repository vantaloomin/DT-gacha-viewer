"""Local web server for the gallery. Same as `python -m http.server`, but tells the browser to
revalidate every file (Cache-Control: no-cache), so updated pages, scripts and data always load
instead of stale cached copies. Unchanged files still come back as fast 304 responses.

It also stops by itself once no gallery page is open: each open page pings /__ping every 20 s
(js/keepalive.js), and the server exits after IDLE_EXIT seconds without any request. The limit is
generous because Chrome slows timers in background tabs to about once a minute.

It answers byte-range requests (HTTP 206), which browsers use to seek in videos and audio without
downloading the whole file first; plain `http.server` ignores them, so scrubbing could stall or jump back.

Usage: python serve.py [port] [--stay]   (serves the folder above this one, on 127.0.0.1;
                                          --stay keeps it running until you close the window)
"""
import functools, http.server, os, re, sys, threading, time

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
        self.send_header('Accept-Ranges', 'bytes')
        super().end_headers()

    # ---- byte ranges ("Range: bytes=start-end"), for seeking in media ----
    def send_head(self):
        self._range_left = None
        rng = self.headers.get('Range')
        path = self.translate_path(self.path)
        m = re.fullmatch(r'bytes=(\d*)-(\d*)', (rng or '').strip())
        if not m or not (m[1] or m[2]) or not os.path.isfile(path):
            return super().send_head()
        size = os.path.getsize(path)
        if m[1]:
            start, end = int(m[1]), min(int(m[2]) if m[2] else size - 1, size - 1)
        else:   # "bytes=-N": the last N bytes
            start, end = max(0, size - int(m[2])), size - 1
        if start >= size or start > end:
            self.send_response(416)
            self.send_header('Content-Range', f'bytes */{size}')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        f = open(path, 'rb')
        f.seek(start)
        self.send_response(206)
        self.send_header('Content-Type', self.guess_type(path))
        self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Last-Modified', self.date_time_string(os.path.getmtime(path)))
        self.end_headers()
        self._range_left = end - start + 1
        return f

    def copyfile(self, source, outputfile):
        try:
            left = getattr(self, '_range_left', None)
            if left is None:
                return super().copyfile(source, outputfile)
            while left > 0:
                chunk = source.read(min(1 << 16, left))
                if not chunk:
                    break
                outputfile.write(chunk)
                left -= len(chunk)
        except (ConnectionError, OSError):
            pass   # the browser cancelled the request (normal while seeking)

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
