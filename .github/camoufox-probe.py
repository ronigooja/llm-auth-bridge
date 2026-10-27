import os
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright
from camoufox.sync_api import NewBrowser
from camoufox.utils import launch_options
from app.browser_device import _snapshot, _restore

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.send_header('Content-Type', 'text/html'); self.end_headers(); self.wfile.write(b'<title>Synthetic</title>')
    def log_message(self, *_): pass
server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{server.server_port}/'
with tempfile.TemporaryDirectory(dir=os.environ['HOME'] + '/environment') as d:
    root = Path(d)
    options = launch_options(os='linux', headless=True, locale='en-US', config={'timezone':'America/Los_Angeles'}, user_data_dir=str(root/'a'), i_know_what_im_doing=True)
    with sync_playwright() as p:
        def read(context):
            page = context.new_page(); page.goto(url)
            result = page.evaluate('''async () => { const w = new Worker(URL.createObjectURL(new Blob(["onmessage=()=>postMessage({ua:navigator.userAgent, platform:navigator.platform, cores:navigator.hardwareConcurrency})"], {type:'text/javascript'}))); const worker=await new Promise(r=>{w.onmessage=e=>r(e.data);w.postMessage(0)}); return {ua:navigator.userAgent,platform:navigator.platform,cores:navigator.hardwareConcurrency,locale:navigator.language,timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,worker}; }''')
            return page, result
        c = NewBrowser(p, persistent_context=True, from_options=options)
        page, first = read(c)
        page.evaluate("localStorage.setItem('synthetic','persisted')")
        c.add_cookies([{'name':'synthetic','value':'value','url':url,'expires':2000000000}])
        try:
            c.new_cdp_session(page)
        except Exception as e:
            print('Firefox CDP unavailable:', type(e).__name__)
        else:
            raise AssertionError('CDP unexpectedly accepted on Firefox')
        c.close()
        data = _snapshot(root/'a'); (root/'restored').mkdir(); _restore(data, root/'restored')
        options2 = dict(options); options2['user_data_dir'] = str(root/'restored')
        c = NewBrowser(p, persistent_context=True, from_options=options2)
        page, second = read(c)
        assert first == second, (first,second)
        assert first['timezone'] == 'America/Los_Angeles', first
        assert first['worker']['ua'] == first['ua'] and first['worker']['platform'] == first['platform'], first
        assert page.evaluate("localStorage.getItem('synthetic')") == 'persisted'
        assert any(x['name']=='synthetic' for x in c.cookies())
        print('synthetic persistent profile archive, cookie, storage, stable launch options, timezone and worker: PASS')
        print('identity:', first)
        c.close()
server.shutdown()
