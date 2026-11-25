# The look library: numbered, described in a line, and honest about which looks
# have already dressed a piece.
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}
LOOKS = [
  {"look_id": "L1", "look_no": 1, "name": "Smoking on the steps",
   "summary": "Teal silk saree, seated on sandstone steps with a cigarette, carved doorway behind.",
   "status": "Ready", "source": "Found", "use_for": "Both", "reference_url": "about:blank",
   "times_used": 2, "tags": "", "notes": "", "subject": "A woman", "pose": "Seated",
   "setting": "Steps", "light": "Soft", "palette": "Teal", "mood": "Bold", "avoid": "", "framing": "Full"},
  {"look_id": "L2", "look_no": 2, "name": "Ghat in late afternoon",
   "summary": "Purple and peach saree, standing on the riverbank, moored boats behind.",
   "status": "Ready", "source": "Found", "use_for": "Both", "reference_url": "about:blank",
   "times_used": 0, "tags": "", "notes": ""},
  {"look_id": "L3", "look_no": 3, "name": "IMG_4821", "summary": None,
   "status": "Unread", "source": "Found", "use_for": "Both", "reference_url": "about:blank",
   "times_used": 0, "tags": "", "notes": ""},
]
USAGE = [
  {"look_id": "L1", "look_no": 1, "products_used_on": 2, "images_made": 3,
   "last_image_at": "2026-11-18T00:00:00Z",
   "products": [{"product_id": "p1", "name": "Cool Blue Zigzag"},
                {"product_id": "p2", "name": "Rose Tissue"}]},
  {"look_id": "L2", "look_no": 2, "products_used_on": 0, "images_made": 0,
   "last_image_at": None, "products": []},
]

def run():
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1340, "height": 950})
        def handler(route):
            u = route.request.url
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json",
                    body=json.dumps({"gemini": True, "brand_set": True, "sets": []}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            rows = {"looks": LOOKS, "look_usage": USAGE,
                    "profiles": [{"id": USER["id"], "email": USER["email"],
                                  "full_name": "Mohammad Arsh", "role": "owner"}],
                    "settings": [{"setting_key": "brand_name", "setting_value": "Zarivia"}]}.get(t, [])
            return route.fulfill(status=200, content_type="application/json",
                headers={"content-range": "0-0/0"}, body=json.dumps(rows))
        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))
        pg.goto(BASE + "/looks/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(800)

        # 1. a numbered row per look, in order
        nos = pg.eval_on_selector_all(".look-no", "e => e.map(x => x.textContent.trim())")
        if nos != ["1", "2", "3"]:
            bad.append(f"the numbers read {nos}, expected 1, 2, 3")

        # 2. the one-line description is shown, not the file name
        sums = pg.eval_on_selector_all(".look-sum", "e => e.map(x => x.textContent.trim())")
        if not sums or "cigarette" not in sums[0]:
            bad.append(f"the first look does not show its one-line description: {sums[:1]}")
        if sums and "Not read yet" not in sums[2]:
            bad.append(f"an unread look does not say so: {sums[2:3]}")

        # 3. names do not overlap: each row's text stays inside its row
        clipped = pg.evaluate("""() => [...document.querySelectorAll('.look-row')].map(r => {
            const t = r.querySelector('.look-text');
            return t.getBoundingClientRect().bottom - r.getBoundingClientRect().bottom; })""")
        if any(d > 1 for d in clipped):
            bad.append(f"text spills past its row: {clipped}")

        # 4. used vs unused is stated, with the pieces named
        txt = pg.inner_text("body")
        if "Used on 2 pieces" not in txt:
            bad.append("a used look does not say how many pieces it is on")
        if "Unused" not in txt:
            bad.append("an unused look is not marked unused")
        if "Cool Blue Zigzag" not in txt:
            bad.append("the pieces a look was used on are not named")

        # 5. opening one shows its number and lets the line be edited
        pg.query_selector_all(".look-row")[0].click()
        pg.wait_for_timeout(500)
        panel = pg.inner_text("body")
        if "#1 · Smoking on the steps" not in panel:
            bad.append("the open look does not show its number and name")
        if "In one line" not in panel:
            bad.append("the one-line description cannot be edited")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run()
print(f"=== look library: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
