import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

PORT = 5175
DIRECTORY = "/home/manager/energy-platform/frontend-src/dist"
os.chdir(DIRECTORY)

class SPAHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        full_path = os.path.join(DIRECTORY, path.lstrip("/"))
        if path == "/" or (not os.path.exists(full_path) and not path.startswith("/assets/")):
            self.path = "/index.html"
        return super().do_GET()

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), SPAHandler).serve_forever()
