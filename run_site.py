"""Runs inside GitHub Actions: clone the PRIVATE repo, start it behind the login gate,
open a Cloudflare tunnel and send the link to your phone via ntfy.sh (NOT to the public logs)."""
import os, re, sys, time, json, shutil, hashlib, subprocess, urllib.request

REPO = os.environ["PRIVATE_REPO"]            # e.g. italisa800-tech/v22
PAT = os.environ["GH_PAT"]                   # read-only token for that repo
SYMBOL = os.environ.get("SYMBOL", "NIFTY")
PASSWORD = os.environ["GATE_PASSWORD"]
LINK_KEY = os.environ["GATE_LINK_KEY"]
NTFY = os.environ.get("NTFY_TOPIC", "")
RUN_MIN = int(os.environ.get("RUN_MINUTES", "340"))   # stop a little before GitHub's 6 h hard limit
KEY = hashlib.sha256(("v22gate:" + PASSWORD).encode()).hexdigest()
HERE = os.getcwd()
APP_DIR = os.path.join(HERE, "v22")
T0 = time.time()


def sh(cmd, **kw):
    return subprocess.run(cmd, shell=isinstance(cmd, str), **kw)


def get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "X-Gate-Key": KEY})
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
        return r.status, r.read().decode("utf-8", "ignore")
    except Exception as e:
        return "ERR", str(e)


def notify(msg, click=None):
    if not NTFY:
        return
    h = {"Title": "Option chain", "Priority": "default"}
    if click:
        h["Click"] = click
    try:
        urllib.request.urlopen(urllib.request.Request("https://ntfy.sh/" + NTFY, data=msg.encode(), headers=h), timeout=15)
    except Exception:
        pass


# 1. clone the private repo (token never printed; GitHub also masks it automatically)
shutil.rmtree(APP_DIR, ignore_errors=True)
r = sh(["git", "clone", "--depth", "1", f"https://x-access-token:{PAT}@github.com/{REPO}.git", APP_DIR],
       capture_output=True, text=True)
if r.returncode != 0:
    print("Clone failed - check GH_PAT / PRIVATE_REPO")
    sys.exit(1)
sh(["git", "-C", APP_DIR, "remote", "set-url", "origin", f"https://github.com/{REPO}.git"])
print("1/5 repo cloned")

# 2. packages
sh([sys.executable, "-m", "pip", "install", "-q", "-r", os.path.join(APP_DIR, "requirements.txt"), "scipy"], check=True)
print("2/5 packages installed")

# 3. login gate + app
shutil.copy(os.path.join(HERE, "login_gate.py"), os.path.join(APP_DIR, "login_gate.py"))
with open(os.path.join(APP_DIR, "run_gate.py"), "w") as f:
    f.write(
        "import os, uvicorn\n"
        "import app as chartapp\n"
        "from login_gate import Gate\n"
        "chartapp.app.add_middleware(Gate)\n"
        "uvicorn.run(chartapp.app, host='0.0.0.0', port=int(os.environ.get('PORT', 7860)))\n")
env = dict(os.environ, PORT="7860", POLL_INTERVAL_SECONDS="2", PYTHONUNBUFFERED="1")
app_log = open(os.path.join(HERE, "app.log"), "w")
app_p = subprocess.Popen([sys.executable, "run_gate.py"], cwd=APP_DIR, env=env, stdout=app_log, stderr=subprocess.STDOUT)
for _ in range(120):
    if get("http://127.0.0.1:7860/api/status", 3)[0] == 200:
        break
    time.sleep(1)
else:
    print("App did not start")
    notify("App failed to start in GitHub Actions")
    sys.exit(1)
print("3/5 app running (login enabled)")

st = {}
for _ in range(60):
    code, body = get("http://127.0.0.1:7860/api/status", 5)
    try:
        st = json.loads(body)
    except Exception:
        st = {}
    if st.get("master_db", {}).get("ready"):
        break
    time.sleep(2)
print("   token_status:", st.get("token_status"))
if st.get("token_status") != "ACTIVE":
    notify("Upstox token is not ACTIVE - page will show 'Data Not Found'")

# 4. Cloudflare quick tunnel
tun_log_path = os.path.join(HERE, "tunnel.log")
tun_log = open(tun_log_path, "w")
tun_p = subprocess.Popen(["cloudflared", "tunnel", "--url", "http://127.0.0.1:7860", "--no-autoupdate"],
                         stdout=tun_log, stderr=subprocess.STDOUT)
url = None
for _ in range(90):
    m = re.search(r"https://[-a-z0-9]+\.trycloudflare\.com", open(tun_log_path).read())
    if m:
        url = m.group(0)
        break
    time.sleep(1)
if not url:
    print("Tunnel did not start")
    notify("Tunnel failed to start")
    sys.exit(1)
print("::add-mask::" + url)              # hides the URL if it ever appears in the public log
print("4/5 tunnel created, waiting until reachable ...")
for _ in range(60):
    if get(url + "/api/status", 8)[0] == 200:
        break
    time.sleep(2)
print("5/5 site is up (link sent to ntfy, not shown in the public log)")

table = f"{url}/?symbol={SYMBOL}&key={LINK_KEY}"
chart = f"{url}/chart?symbol={SYMBOL}&key={LINK_KEY}"
notify("TABLE: " + table + "\nCHART: " + chart + f"\nLive for about {RUN_MIN // 60}h {RUN_MIN % 60}m", click=chart)

# 5. keep alive until the deadline; restart nothing, just exit cleanly if a process dies
while time.time() - T0 < RUN_MIN * 60:
    if app_p.poll() is not None or tun_p.poll() is not None:
        notify("Site stopped (process exited). A new scheduled run will bring it back.")
        sys.exit(1)
    time.sleep(30)
notify("Session ended (time limit). Next scheduled run will send a new link.")
app_p.terminate()
tun_p.terminate()
