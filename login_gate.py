"""Login wrapper (ASGI middleware). Reads everything from environment variables - no secrets in this file."""
import os, time, hmac, hashlib
from urllib.parse import parse_qs, quote, urlencode

PASSWORD = os.environ["GATE_PASSWORD"]
LINK_KEY = os.environ["GATE_LINK_KEY"]
KEY = hashlib.sha256(("v22gate:" + PASSWORD).encode()).hexdigest()
COOKIE = "oc_auth"
MAXAGE = 365 * 24 * 3600

_fails = []


def locked():
    now = time.time()
    while _fails and now - _fails[0] > 600:
        _fails.pop(0)
    return len(_fails) >= 20


def fail():
    _fails.append(time.time())


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Login</title>
<style>
body{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;background:#f4f6f9;
font:14px -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1b2333}
form{background:#fff;border:1px solid #e3e7ee;border-radius:12px;box-shadow:0 8px 28px rgba(22,34,64,.12);
padding:28px 26px;width:310px;display:flex;flex-direction:column;gap:12px}
h2{margin:0 0 4px;font-size:18px}
input{padding:10px 12px;border:1px solid #d5dbe5;border-radius:8px;font:inherit}
input:focus{outline:none;border-color:#3b6df0}
button{padding:10px;border:0;border-radius:8px;background:#3b6df0;color:#fff;font:inherit;font-weight:600;cursor:pointer}
.err{color:#d6453d;font-size:13px}
</style></head><body>
<form method="POST" action="/login">
<h2>Option Chain</h2>
<input type="text" name="username" value="Ishan" autocomplete="username">
<input type="password" name="password" placeholder="Password" autocomplete="current-password" autofocus required>
<input type="hidden" name="next" value="__NEXT__">
__ERR__
<button type="submit">Log in</button>
</form></body></html>"""


def safe_next(n):
    return n if (n and n.startswith("/") and not n.startswith("//")) else "/"


def cookie_hdr():
    return (COOKIE + "=" + KEY + "; Max-Age=" + str(MAXAGE) + "; Path=/; HttpOnly; Secure; SameSite=Lax").encode()


def ok(a):
    return bool(a) and hmac.compare_digest(a.encode(), KEY.encode())


class Gate:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        hd = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
        jar = {}
        for part in hd.get("cookie", "").split(";"):
            if "=" in part:
                a, b = part.strip().split("=", 1)
                jar[a] = b
        if ok(jar.get(COOKIE)) or ok(hd.get("x-gate-key")):
            return await self.app(scope, receive, send)

        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return

        path = scope["path"]
        qs = parse_qs(scope.get("query_string", b"").decode())

        # auto-login link:  <url>/anything?key=<LINK_KEY>
        k = (qs.get("key") or [""])[0]
        if k:
            if locked():
                return await self.page(send, "/", '<div class="err">Too many attempts. Try again in 10 minutes.</div>', 429)
            if hmac.compare_digest(k.encode(), LINK_KEY.encode()):
                rest = {a: b for a, b in qs.items() if a != "key"}
                loc = path + (("?" + urlencode(rest, doseq=True)) if rest else "")
                return await self.redirect(send, loc, True)
            fail()

        if path == "/login" and scope["method"] == "POST":
            body = b""
            while True:
                m = await receive()
                body += m.get("body", b"")
                if not m.get("more_body"):
                    break
            f = parse_qs(body.decode("utf-8", "ignore"))
            nxt = safe_next((f.get("next") or ["/"])[0])
            if locked():
                return await self.page(send, nxt, '<div class="err">Too many attempts. Try again in 10 minutes.</div>', 429)
            pw = (f.get("password") or [""])[0]
            if hmac.compare_digest(pw.encode(), PASSWORD.encode()):
                return await self.redirect(send, nxt, True)
            fail()
            return await self.page(send, nxt, '<div class="err">Wrong password</div>', 401)

        if path == "/login":
            return await self.page(send, safe_next((qs.get("next") or ["/"])[0]), "", 200)

        q = scope.get("query_string", b"").decode()
        return await self.redirect(send, "/login?next=" + quote(path + ("?" + q if q else ""), safe=""), False)

    async def redirect(self, send, loc, setc):
        h = [(b"location", loc.encode()), (b"content-length", b"0"), (b"cache-control", b"no-store")]
        if setc:
            h.append((b"set-cookie", cookie_hdr()))
        await send({"type": "http.response.start", "status": 303, "headers": h})
        await send({"type": "http.response.body", "body": b""})

    async def page(self, send, nxt, err, status):
        html = PAGE.replace("__NEXT__", nxt.replace('"', "&quot;")).replace("__ERR__", err).encode()
        await send({"type": "http.response.start", "status": status, "headers": [
            (b"content-type", b"text/html; charset=utf-8"),
            (b"content-length", str(len(html)).encode()), (b"cache-control", b"no-store")]})
        await send({"type": "http.response.body", "body": html})
