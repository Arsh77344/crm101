# A phone-sized screen: nothing spills sideways, the rail still opens, and a
# finger-sized target is actually finger-sized.
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
PAGES = ["/", "/products/", "/orders/", "/launch/", "/studio/", "/shipments/", "/campaigns/"]

def run():
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        # an iPhone-ish viewport
        ctx = b.new_context(viewport={"width": 390, "height": 844},
                            device_scale_factor=3, is_mobile=True, has_touch=True)
        def handler(route):
            u = route.request.url
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                  {"gemini": True, "brand_set": True, "sets": [], "configured": False,
                   "can_search": {"gemini": True}, "counts": {}, "departments": ["sales"]}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            return route.fulfill(status=200, content_type="application/json",
                headers={"content-range": "0-0/0"}, body=json.dumps(EXTRA.get(t, FIX.get(t, []))))
        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))

        for path in PAGES:
            pg.goto(BASE + path, wait_until="networkidle", timeout=25000)
            pg.wait_for_timeout(700)

            # 1. nothing pushes the page wider than the phone
            over = pg.evaluate("""() => {
              const w = document.documentElement.clientWidth;
              return [...document.querySelectorAll('body *')]
                .filter(e => { const r = e.getBoundingClientRect();
                  return r.width > 0 && r.right > w + 2
                    && getComputedStyle(e).position !== 'fixed'
                    && !e.closest('.t-wrap') && !e.closest('.board'); })
                .slice(0, 3)
                .map(e => (e.className || e.tagName) + ' → ' + Math.round(e.getBoundingClientRect().right));
            }""")
            if over:
                bad.append(f"{path} spills past the screen: {over}")
            if pg.evaluate("document.documentElement.scrollWidth > document.documentElement.clientWidth + 2"):
                bad.append(f"{path} scrolls sideways")

            # 2. a field a finger taps is big enough and will not zoom iOS
            small = pg.evaluate("""() => [...document.querySelectorAll('input,select,textarea')]
              .filter(e => e.offsetParent !== null && !['checkbox','radio','hidden','file'].includes(e.type))
              .filter(e => parseFloat(getComputedStyle(e).fontSize) < 16)
              .slice(0, 3).map(e => e.name || e.placeholder || e.tagName)""")
            if small:
                bad.append(f"{path} has fields under 16px, which makes iOS zoom in: {small}")

        # 3. the rail collapses to a menu and still opens
        pg.goto(BASE + "/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(600)
        if pg.evaluate("getComputedStyle(document.querySelector('.nav')).display") != "none":
            bad.append("the rail is not collapsed on a phone")
        menu = pg.query_selector(".menu-btn")
        if not menu:
            bad.append("there is no menu button on a phone")
        else:
            menu.click(); pg.wait_for_timeout(400)
            if pg.evaluate("getComputedStyle(document.querySelector('.nav')).display") == "none":
                bad.append("the menu button does not open the rail")
            sec = pg.query_selector(".nav-sec-head")
            if sec:
                box = sec.bounding_box()
                if box and box["height"] < 36:
                    bad.append(f"a nav row is {round(box['height'])}px tall, too small for a finger")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run()
print(f"=== phone: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)
