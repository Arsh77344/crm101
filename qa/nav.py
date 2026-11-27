# The rail: sections that open and close, the one you are in opening itself,
# what you opened surviving a move to another page, and Ctrl K jumping to a page.
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright
from fixtures import ROWS as FIX

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}
EXTRA = {"profiles": [{"id": USER["id"], "email": USER["email"], "full_name": "Mohammad Arsh",
                       "role": "owner", "created_at": "2026-01-01T00:00:00Z"}],
         "settings": [{"setting_key": "brand_name", "setting_value": "Zarivia"},
                      {"setting_key": "brand_sells", "setting_value": "sarees"}]}
SECTIONS = ["Catalogue", "Sales", "Fulfilment", "Marketing", "Messaging", "Money", "Workspace"]

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
                    body=json.dumps({"gemini": True, "brand_set": True, "departments": ["sales"]}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            return route.fulfill(status=200, content_type="application/json",
                headers={"content-range": "0-0/0"}, body=json.dumps(EXTRA.get(t, FIX.get(t, []))))
        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))

        links = lambda: pg.eval_on_selector_all(".nav a", "els => els.map(e => e.textContent.trim())")

        # 1. On the dashboard, nothing is expanded: one link, not thirty-five.
        pg.goto(BASE + "/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(600)
        shown = links()
        if len(shown) != 1:
            bad.append(f"dashboard shows {len(shown)} nav links, expected 1 with every section shut")
        heads = pg.eval_on_selector_all(".nav-sec-head .nav-sec-name", "e => e.map(x => x.textContent.trim())")
        if heads != SECTIONS:
            bad.append(f"section headers are {heads}, expected {SECTIONS}")

        # 2. Every shut section says how many pages it holds.
        #
        # Marketing holds 9, two over what the rest of the rail keeps to. That is
        # a decision, not a slip: the occasions calendar had to sit beside the
        # content calendar to be findable, and an unreachable page is worse than
        # a long section. Retiring '/generate', which the campaign studio
        # supersedes, would bring it back to 7. Recorded here so the next page
        # added to Marketing trips this check rather than sliding past it.
        counts = pg.eval_on_selector_all(".nav-sec-n", "e => e.map(x => x.textContent.trim())")
        # Messaging went from 4 to 5 when the inbox was added.
        if counts != ["4", "7", "3", "9", "5", "5", "6"]:
            bad.append(f"section counts are {counts}")
        if max(int(c) for c in counts) > 9:
            bad.append(f"a section now holds more than 9 pages: {counts}")

        # 3. A section opens on click, and says so to a screen reader.
        head = pg.get_by_role("button", name=re.compile("Marketing"))
        if head.get_attribute("aria-expanded") != "false":
            bad.append("a shut section does not report aria-expanded=false")
        head.click(); pg.wait_for_timeout(300)
        if head.get_attribute("aria-expanded") != "true":
            bad.append("an opened section does not report aria-expanded=true")
        if "Campaigns" not in " ".join(links()):
            bad.append("opening Marketing did not reveal its pages")

        # 4. What you opened survives a move to another page.
        pg.goto(BASE + "/tasks/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(600)
        after = " ".join(links())
        if "Campaigns" not in after:
            bad.append("the section opened by hand shut itself after navigating")
        # 5. ...and the section holding the page you are on opens itself.
        if "Tasks" not in after:
            bad.append("the section holding the current page did not open itself")
        # the label carries its icon, so compare on the label text alone
        on = pg.eval_on_selector_all(".nav a.on",
            "e => e.map(x => x.textContent.replace(/^\\s*\\S\\s*/, '').trim())")
        if on != ["Tasks"]:
            bad.append(f"marked as current: {on}, expected ['Tasks']")

        # 6. A section can be shut again — but not the one you are in.
        pg.get_by_role("button", name=re.compile("Marketing")).click(); pg.wait_for_timeout(300)
        if "Campaigns" in " ".join(links()):
            bad.append("clicking an open section did not shut it")
        pg.get_by_role("button", name=re.compile("Workspace")).click(); pg.wait_for_timeout(300)
        if "Tasks" not in " ".join(links()):
            bad.append("the section holding the current page can be shut, hiding where you are")

        # 7. Ctrl K jumps to a page by name.
        pg.keyboard.press("Control+k"); pg.wait_for_timeout(400)
        pg.keyboard.type("look"); pg.wait_for_timeout(400)
        first = pg.query_selector(".hit")
        if not first or "Look library" not in first.inner_text():
            bad.append(f"Ctrl K did not offer the Look library page first: {first and first.inner_text()[:60]!r}")
        else:
            pg.keyboard.press("Enter"); pg.wait_for_timeout(900)
            if "/looks" not in pg.url:
                bad.append(f"Enter on the page hit went to {pg.url}")

        # 8. One header row, and it stays put while the page scrolls.
        if len(pg.query_selector_all(".topbar")) != 1:
            bad.append("more than one header row")
        if pg.eval_on_selector(".topbar", "e => getComputedStyle(e).position") != "sticky":
            bad.append("the header row does not stay put when the page scrolls")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run()
print(f"=== rail and header: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
