import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

# Served under a base path, exactly as GitHub Pages serves it: a build without
# the base path hides any URL built from window.location.
BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
ROUTES = ["/agents", "/brands", "/payables","/", "/products", "/collections", "/launch", "/orders", "/shipments", "/payments",
          "/returns", "/showrooms", "/contacts", "/companies", "/pipeline", "/journey",
          "/activities", "/campaigns", "/generate", "/calendar", "/performance", "/links",
          "/looks", "/studio", "/outreach", "/templates", "/broadcasts", "/analytics", "/consent", "/suppliers", "/expenses",
          "/finance", "/tasks", "/automations", "/integrations", "/team", "/settings"]

USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}

ROWS = {
  "profiles": [{"id": USER["id"], "email": USER["email"], "full_name": "Test Owner", "role": "owner",
                "created_at": "2026-01-01T00:00:00Z"}],
  "settings": [{"setting_key": k, "setting_value": v} for k, v in [
      ("brand_name", "Test Brand"), ("brand_sells", "things"), ("brand_voice", "plain"),
      ("brand_audience", "people"), ("brand_tagline", ""), ("storefront_url", ""),
      ("default_currency", "INR"), ("whatsapp_number", "919999999999"),
      ("ga4_property_id", ""), ("looker_embed_url", ""), ("guard_quiet_start", "21"),
      ("guard_quiet_end", "9"), ("guard_max_marketing_per_week", "2"),
      ("guard_min_hours_between", "20")]],
}

from fixtures import ROWS as FIX
def body_for(path, mode):
    m = re.search(r"/rest/v1/([a-z_]+)", path)
    table = m.group(1) if m else ""
    if mode == "empty":
        return ROWS[table] if table in ("profiles", "settings") else []
    if table in FIX:
        return FIX[table]
    if table in ROWS:
        return ROWS[table]
    return []

def run(mode):
    problems = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1340, "height": 900})

        def handler(route):
            url = route.request.url
            if "/auth/v1/user" in url:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in url:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/" in url:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"openai": False, "gemini": True, "anthropic": False,
                                                    "brand_set": True,
                                                    "departments": ["sales","marketing","operations","finance","customers"]}))
            return route.fulfill(status=200, content_type="application/json",
                                 headers={"content-range": "0-0/0"},
                                 body=json.dumps(body_for(url, mode)))

        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script(
            "localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));" % json.dumps(SESSION))

        for r in ROUTES:
            errs = []
            pg.on("pageerror", lambda e, errs=errs: errs.append(f"PAGEERROR {e}"))
            pg.on("console", lambda m, errs=errs: errs.append(f"CONSOLE {m.text[:160]}")
                  if m.type == "error" else None)
            try:
                pg.goto(BASE + r + ("" if r == "/" else "/"), wait_until="networkidle", timeout=20000)
                pg.wait_for_timeout(500)
                txt = pg.inner_text("body")[:400]
                if "Application error" in txt or "client-side exception" in txt:
                    problems.append((r, "page crashed"))
                elif len(txt.strip()) < 25:
                    problems.append((r, f"almost no content: {txt.strip()[:60]!r}"))
            except Exception as e:
                problems.append((r, f"navigation failed: {str(e)[:90]}"))
            real = [e for e in errs if "favicon" not in e.lower() and "404" not in e]
            if real:
                problems.append((r, real[0][:150]))
            pg.remove_listener("pageerror", lambda e: None) if False else None
        b.close()
    return problems

mode = sys.argv[1] if len(sys.argv) > 1 else "empty"
probs = run(mode)
print(f"=== {mode}: {len(probs)} problem(s) across {len(ROUTES)} routes ===")
for r, p in probs:
    print(f"  {r:<16} {p}")
