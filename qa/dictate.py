# Dictation: the microphone appears on every field that takes a brief, it adds
# to what is already typed instead of replacing it, and it says so plainly when
# the browser cannot listen.
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
from fixtures import ROWS as FIX

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}
EXTRA = {"profiles": [{"id": USER["id"], "email": USER["email"],
                       "full_name": "Mohammad Arsh", "role": "owner"}],
         "settings": [{"setting_key": "brand_name", "setting_value": "Zarivia"},
                      {"setting_key": "brand_sells", "setting_value": "sarees"}]}

# A stand-in for the browser's own speech engine, so the wiring can be tested
# without a microphone: whatever is pushed to window.__say is delivered as final.
FAKE = """
window.__said = [];
class FakeRec {
  constructor() { this.lang = ''; this.continuous = false; this.interimResults = false; }
  start() { window.__rec = this; window.__listening = true; }
  stop() { window.__listening = false; if (this.onend) this.onend(); }
  say(text, final = true) {
    this.onresult({ resultIndex: 0,
      results: Object.assign([[{ transcript: text }]], { 0: Object.assign([{ transcript: text }],
        { isFinal: final }) }) });
  }
}
window.SpeechRecognition = FakeRec;
"""

def run():
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 960})
        def handler(route):
            u = route.request.url
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                  {"gemini": True, "brand_set": True, "sets": [], "can_search": {"gemini": True},
                   "counts": {}, "departments": ["sales"]}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            return route.fulfill(status=200, content_type="application/json",
                headers={"content-range": "0-0/0"},
                body=json.dumps(EXTRA.get(t, FIX.get(t, []))))
        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        pg.add_init_script(FAKE)
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))

        # 1. the microphone is on the pages that take a brief
        for path, where in [("/studio/", "campaign studio"),
                            ("/generate/", "campaign builder"), ("/brands/", "a records form")]:
            pg.goto(BASE + path, wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(700)
            if path == "/brands/":
                add = pg.query_selector("button:has-text('New')")
                if add: add.click(); pg.wait_for_timeout(500)
            if not pg.query_selector(".dictate"):
                bad.append(f"no microphone on {where}")

        # 2. it adds to what is already typed, rather than replacing it
        pg.goto(BASE + "/studio/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(700)
        pg.fill("textarea", "Push the blue pieces")
        pg.query_selector(".dictate button").click()
        pg.wait_for_timeout(400)
        if not pg.evaluate("window.__listening"):
            bad.append("pressing the microphone did not start listening")
        pg.evaluate("window.__rec.say('before wedding season')")
        pg.wait_for_timeout(400)
        said = pg.input_value("textarea")
        if said != "Push the blue pieces before wedding season":
            bad.append(f"dictation produced {said!r}")

        # 3. the language it listens in is the one chosen, and it is remembered
        if pg.evaluate("window.__rec.lang") != "en-IN":
            bad.append(f"listening in {pg.evaluate('window.__rec.lang')}, expected en-IN")
        pg.query_selector(".dictate button").click()
        pg.wait_for_timeout(300)
        pg.select_option(".dictate-lang", "hi-IN")
        pg.wait_for_timeout(200)
        pg.reload(wait_until="networkidle"); pg.wait_for_timeout(800)
        if pg.input_value(".dictate-lang") != "hi-IN":
            bad.append("the dictation language is not remembered")

        # 4. a browser that cannot listen says so instead of failing quietly
        pg2 = ctx.new_page()
        pg2.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                            % json.dumps(SESSION))
        pg2.add_init_script("delete window.SpeechRecognition; delete window.webkitSpeechRecognition;")
        pg2.goto(BASE + "/studio/", wait_until="networkidle", timeout=20000)
        pg2.wait_for_timeout(700)
        pg2.query_selector(".dictate button").click()
        pg2.wait_for_timeout(300)
        note = pg2.query_selector(".dictate-note")
        if not note or "cannot listen" not in note.inner_text():
            bad.append("a browser without speech support is not told so")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run()
print(f"=== dictation: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
