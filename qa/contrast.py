# Every control a person types into must be readable in both themes. This is the
# bug the owner hit: a select outside .field kept the browser's white box while
# everything round it was dark.
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

def lum(rgb):
    def ch(v):
        v = v / 255
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = [ch(x) for x in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b

def ratio(a, b):
    la, lb = lum(a), lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)

def parse(css):
    nums = [float(x) for x in re.findall(r"[\d.]+", css or "")]
    return tuple(int(n) for n in nums[:3]) if len(nums) >= 3 else None

def transparent(css):
    nums = [float(x) for x in re.findall(r"[\d.]+", css or "")]
    return len(nums) >= 4 and nums[3] == 0

def run(theme):
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 980})
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
        pg.add_init_script(
            "localStorage.setItem('cos-theme','%s');"
            "document.addEventListener('DOMContentLoaded',()=>"
            "document.documentElement.setAttribute('data-theme','%s'));" % (theme, theme))

        for path in ("/launch/", "/studio/", "/settings/", "/shipments/", "/orders/"):
            pg.goto(BASE + path, wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(700)
            found = pg.evaluate("""() => [...document.querySelectorAll('input,select,textarea')]
              .filter(e => e.offsetParent !== null && e.type !== 'checkbox' && e.type !== 'radio'
                        && e.type !== 'file' && e.type !== 'hidden')
              .map(e => { const s = getComputedStyle(e);
                if (window.__dump) console.log(e.tagName, s.backgroundColor, s.color);
                return { tag: e.tagName.toLowerCase(), bg: s.backgroundColor, fg: s.color,
                         id: (e.name || e.placeholder || e.className || '').slice(0, 30) }; })""")
            if not found:
                bad.append(f"{path} has no visible controls to check")
            for f in found:
                if transparent(f["bg"]):
                    bad.append(f"{path} {f['tag']} ({f['id']}) has no background of its own, "
                               f"so the browser paints it — this is the white-box bug")
                    continue
                bg, fg = parse(f["bg"]), parse(f["fg"])
                if not bg or not fg:
                    continue
                if theme == "dark" and lum(bg) > 0.6:
                    bad.append(f"{path} {f['tag']} ({f['id']}) is still white in dark mode")
                elif ratio(bg, fg) < 4.5:
                    bad.append(f"{path} {f['tag']} ({f['id']}) text/background contrast "
                               f"{ratio(bg, fg):.1f}:1")
        b.close()
    return bad

probs = [f"[dark] {x}" for x in run("dark")] + [f"[light] {x}" for x in run("light")]
print(f"=== field contrast: {len(probs)} problem(s) ===")
for p in sorted(set(probs)): print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
