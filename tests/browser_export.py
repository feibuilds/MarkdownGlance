"""Run a synthetic HTTP export check in a real browser, without file access.

From the checkout's parent directory:
    python3 -m MarkdownGlance.tests.browser_export --open-browser --output result.json

The server exposes only three in-memory fixture responses. It stops after the
browser reports its assertions, or after the timeout. This does not certify
file:// navigation, saved-file base paths, or unsaved-buffer image resolution.
"""

import argparse
import hashlib
import json
import platform
import struct
import threading
import webbrowser
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from MarkdownGlance.preview.renderer.export import standalone_html


SOURCE = """# Export check

![Relative image](pixel.png)

[First same](#same) · [Second same](#same-2)

| Item | Value |
| --- | ---: |
| Alpha | 42 |
| Beta | 99 |

- Parent one
    - Child one
    - Child two
- Parent two

1. Ordered one

    ```python
    print("nested fence")
    ```

2. Ordered two

## Same

First heading target.

## Same

Second heading target.
"""

HARNESS = """<!doctype html><meta charset="utf-8">
<title>MarkdownGlance HTTP export check</title>
<style>body{font:16px system-ui;margin:24px}iframe{width:100%;height:850px;
border:1px solid #888}#result{white-space:pre-wrap}</style>
<h1>MarkdownGlance HTTP export check</h1>
<p>Synthetic HTTP fixture. Local file navigation is outside this check.</p>
<pre id="result">RUNNING</pre>
<iframe title="Exported Markdown" src="/fixture%20space%20%23hash/preview.html"></iframe>
<script>
const frame = document.querySelector('iframe');
frame.addEventListener('load', async () => {
  const checks = [];
  const check = (name, passed) => checks.push({name, passed: Boolean(passed)});
  try {
    const doc = frame.contentDocument, win = frame.contentWindow;
    const img = doc.querySelector('img');
    await Promise.race([img.decode(), new Promise((_, reject) =>
      setTimeout(() => reject(new Error('Image decode timed out')), 10000))]);
    check('relative image decoded at 160 x 64', img.naturalWidth === 160 && img.naturalHeight === 64);
    check('image uses encoded space and hash directory',
      new URL(img.src).pathname === '/fixture%20space%20%23hash/pixel.png');
    check('no base element', !doc.querySelector('base'));
    check('table has header and two data rows', doc.querySelectorAll('table tr').length === 3);
    check('nested list has two children', doc.querySelectorAll('li > ul > li').length === 2);
    const nested = doc.querySelector('li > ul');
    check('nested list is visually indented', nested.firstElementChild.getBoundingClientRect().left >
      nested.parentElement.getBoundingClientRect().left);
    check('fenced Python block stays inside list item',
      doc.querySelector('li pre code.language-python')?.textContent === 'print("nested fence")');
    check('duplicate headings have distinct IDs',
      doc.querySelectorAll('#same').length === 1 && doc.querySelectorAll('#same-2').length === 1);
    const before = win.location.origin + win.location.pathname;
    for (const id of ['same', 'same-2']) {
      doc.querySelector('a[href="#' + id + '"]').click();
      await new Promise(resolve => setTimeout(resolve, 50));
      check('click #' + id + ' stays on page and selects heading',
        win.location.origin + win.location.pathname === before && win.location.hash === '#' + id &&
        doc.querySelector(':target') === doc.getElementById(id));
    }
  } catch (error) { checks.push({name: 'browser exception', passed: false, error: String(error)}); }
  const result = {status: checks.length === 10 && checks.every(c => c.passed) ? 'pass' : 'fail',
    checks, user_agent: navigator.userAgent, url: frame.src};
  document.querySelector('#result').textContent = result.status.toUpperCase() + '\\n' +
    checks.map(c => (c.passed ? 'PASS ' : 'FAIL ') + c.name).join('\\n');
  await fetch('/results', {method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(result)});
});
</script>
"""


def checkerboard():
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack(
            '!I', zlib.crc32(kind + data) & 0xFFFFFFFF
        )

    pixels = b''.join(
        b'\0' + b''.join(bytes((30, 150, 90) if (x // 16 + y // 16) % 2 else
                              (245, 195, 45)) for x in range(160))
        for y in range(64)
    )
    return (b'\x89PNG\r\n\x1a\n' +
            chunk(b'IHDR', struct.pack('!2I5B', 160, 64, 8, 2, 0, 0, 0)) +
            chunk(b'IDAT', zlib.compress(pixels)) + chunk(b'IEND', b''))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--open-browser', action='store_true')
    parser.add_argument('--timeout', type=float, default=120)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error('--timeout must be positive')

    page = standalone_html(SOURCE, 'HTTP export fixture', '').encode('utf-8')
    routes = {
        '/': ('text/html; charset=utf-8', HARNESS.encode('utf-8')),
        '/fixture space #hash/preview.html': ('text/html; charset=utf-8', page),
        '/fixture space #hash/pixel.png': ('image/png', checkerboard()),
    }
    finished = threading.Event()
    result = {}
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            path = unquote(urlsplit(self.path).path)
            if path not in routes:
                self.send_error(404)
                return
            kind, body = routes[path]
            requests.append(path)
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path != '/results' or self.headers.get('Origin') != origin:
                self.send_error(403)
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 65536:
                    raise ValueError('Invalid result length')
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict) or payload.get('status') not in ('pass', 'fail'):
                    raise ValueError('Invalid result')
            except (ValueError, UnicodeError):
                self.send_error(400)
                return
            result.update(payload)
            self.send_response(204)
            self.end_headers()
            finished.set()

        def log_message(self, *unused):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    origin = 'http://127.0.0.1:{}'.format(server.server_port)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(json.dumps({'url': origin + '/', 'timeout_seconds': args.timeout}), flush=True)
    try:
        if args.open_browser:
            webbrowser.open(origin + '/')
        if not finished.wait(args.timeout):
            result.update(status='fail', error='Browser result timed out')
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    result.update(transport='http', synthetic_fixture=True, file_navigation_tested=False,
                  python=platform.python_version(), requests=requests,
                  rendered_html_sha256=hashlib.sha256(page).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result), flush=True)
    return 0 if result['status'] == 'pass' else 1


if __name__ == '__main__':
    raise SystemExit(main())
