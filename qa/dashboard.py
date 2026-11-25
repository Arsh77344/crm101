# The dashboard's charts and the map: that they draw from the real rows, that
# they say so plainly when there is nothing to draw, and that an order whose
# city we cannot place is counted rather than quietly dropped.
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
         "settings": [{"setting_key": "brand_name", "setting_value": "Zarivia"}]}

def run(rows, empty=False):
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 1100})
        def handler(route):
            u = route.request.url
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json",
                    body=json.dumps({"gemini": True, "brand_set": True}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            data = EXTRA.get(t, ([] if empty else rows.get(t, [])))
            return route.fulfill(status=200, content_type="application/json",
                headers={"content-range": "0-0/0"}, body=json.dumps(data))
        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))
        pg.goto(BASE + "/", wait_until="networkidle", timeout=25000)
        pg.wait_for_timeout(1200)
        txt = pg.inner_text("body")

        if empty:
            # with nothing to draw it must say so, not render a lying chart
            if "no orders yet" not in txt.lower():
                bad.append("an empty workspace does not say the map has nothing to show")
            if pg.query_selector_all(".map-dot"):
                bad.append("dots were drawn with no orders")
            b.close()
            return bad + [e[:140] for e in errs if "favicon" not in e.lower()]

        # 1. every chart drew something
        for sel, what in [(".chart-donut svg path", "the donut slices"),
                          (".chart-svg path", "the revenue line"),
                          (".bar span", "the ranked bars"),
                          (".map-dot", "the map dots")]:
            if not pg.query_selector_all(sel):
                bad.append(f"{what} did not draw")

        # 2. the map put the three fixture cities where they belong
        names = pg.eval_on_selector_all(".map-name", "e => e.map(x => x.textContent.trim())")
        titles = pg.eval_on_selector_all(".map-dot ~ title, g > title",
                                         "e => e.map(x => x.textContent)")
        placed = " ".join(names) + " " + " ".join(titles)
        for city in ("Delhi", "Mumbai", "Varanasi"):
            if city not in placed:
                bad.append(f"{city} is not on the map")

        # Delhi is west of Varanasi, which is west of nothing — check the
        # projection put them in the right order left to right.
        pos = pg.evaluate("""() => {
          const out = {};
          document.querySelectorAll('g').forEach(g => {
            const t = g.querySelector('title'); const c = g.querySelector('circle');
            if (t && c) out[t.textContent.split(':')[0]] = parseFloat(c.getAttribute('cx'));
          });
          return out; }""")
        if pos.get("Delhi") and pos.get("Varanasi") and pos["Delhi"] >= pos["Varanasi"]:
            bad.append("Delhi is drawn east of Varanasi; the projection is wrong")
        if pos.get("Mumbai") and pos.get("Delhi"):
            ys = pg.evaluate("""() => {
              const out = {};
              document.querySelectorAll('g').forEach(g => {
                const t = g.querySelector('title'); const c = g.querySelector('circle');
                if (t && c) out[t.textContent.split(':')[0]] = parseFloat(c.getAttribute('cy'));
              });
              return out; }""")
            if ys.get("Mumbai") and ys.get("Delhi") and ys["Mumbai"] <= ys["Delhi"]:
                bad.append("Mumbai is drawn north of Delhi; the projection is wrong")

        # 3. money and counts are stated, not implied
        if "Where the money comes from" not in txt:
            bad.append("the states ranking is missing")
        if "On the road right now" not in txt:
            bad.append("nothing shows what is in transit")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run(FIX) + [f"(empty) {x}" for x in run(FIX, empty=True)]
print(f"=== dashboard: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
