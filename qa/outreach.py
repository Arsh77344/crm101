# Outreach: the right people in the right group, nobody messaged without
# consent, the message personalised per person, and a send recorded so the same
# person is not chased twice.
import json, os, re, sys, urllib.parse
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}
OLD = "2026-08-01T00:00:00Z"   # long enough ago to count as quiet
RECENT = "2026-11-20T00:00:00Z"

PEOPLE = [
  # cart, consented -> reachable
  {"contact_id": "c1", "full_name": "Asha Verma", "phone_number": "9811111111",
   "whatsapp_opt_in": True, "city": "Delhi"},
  # cart, no consent -> counted, not shown
  {"contact_id": "c2", "full_name": "Ravi Kumar", "phone_number": "9822222222",
   "whatsapp_opt_in": False, "city": "Pune"},
  # bought long ago -> repeat group
  {"contact_id": "c3", "full_name": "Meher Siddiqui", "phone_number": "9833333333",
   "whatsapp_opt_in": True, "city": "Mumbai"},
  # consented but nothing to say -> in no group
  {"contact_id": "c4", "full_name": "Quiet Person", "phone_number": "9844444444",
   "whatsapp_opt_in": True, "city": "Jaipur"},
]
CARTS = [
  {"cart_id": "k1", "contact_id": "c1", "product_id": "p1", "status": "Open", "value": 13500,
   "added_at": OLD, "reminded_at": None, "reminders_sent": 0,
   "products": {"public_product_name": "Midnight Blue Shikargah", "retail_price": 13500}},
  {"cart_id": "k2", "contact_id": "c2", "product_id": "p1", "status": "Open", "value": 9000,
   "added_at": OLD, "reminded_at": None, "reminders_sent": 0,
   "products": {"public_product_name": "Rose Tissue", "retail_price": 9000}},
]
EVENTS = []
ORDERS = [{"contact_id": "c3", "total": 12000, "order_status": "Fulfilled", "ordered_at": OLD}]

def run():
    bad = []
    written = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 1000})
        def handler(route):
            u, req = route.request.url, route.request
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json",
                    body=json.dumps({"gemini": True, "brand_set": True}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            if req.method in ("POST", "PATCH"):
                written.append({"table": t, "method": req.method,
                                "body": json.loads(req.post_data or "{}")})
                return route.fulfill(status=201, content_type="application/json", body="[]")
            rows = {"contacts": PEOPLE, "carts": CARTS, "journey_events": EVENTS, "orders": ORDERS,
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
        pg.goto(BASE + "/outreach/", wait_until="networkidle", timeout=25000)
        pg.wait_for_timeout(1000)
        txt = pg.inner_text("body")

        # 1. the cart group holds the one consented person, and says the other is blocked
        rows = pg.eval_on_selector_all("table tbody tr td:nth-child(2)",
                                       "e => e.map(x => x.textContent)")
        if not any("Asha" in r for r in rows):
            bad.append("the person with a cart and consent is not listed")
        if any("Ravi" in r for r in rows):
            bad.append("someone without WhatsApp consent was listed to message")
        if "1 person fits this reason but cannot be messaged" not in txt:
            bad.append("the blocked person is not counted and explained")

        # 2. the draft names the person and the piece
        ph = pg.get_attribute("textarea", "placeholder") or ""
        if "Asha" not in ph or "Midnight Blue" not in ph:
            bad.append(f"the draft is not written for the person: {ph[:70]!r}")

        # 3. the WhatsApp link carries that text to that number
        href = pg.get_attribute("table tbody tr a", "href") or ""
        if "wa.me/919811111111" not in href:
            bad.append(f"the link does not go to the person's number: {href[:60]}")
        body = urllib.parse.unquote(href.split("text=")[-1])
        if "Asha" not in body or "Midnight Blue" not in body:
            bad.append(f"the link does not carry the personalised message: {body[:70]!r}")

        # 4. a custom message replaces the draft and still substitutes the name
        pg.fill("textarea", "Hello {name}, the {piece} is still here.")
        pg.wait_for_timeout(400)
        href2 = pg.get_attribute("table tbody tr a", "href") or ""
        body2 = urllib.parse.unquote(href2.split("text=")[-1])
        if "Hello Asha" not in body2 or "Midnight Blue" not in body2:
            bad.append(f"placeholders are not filled in: {body2[:70]!r}")

        # 5. opening it records the send and the reminder
        pg.eval_on_selector("table tbody tr a", "e => e.removeAttribute('target')")
        pg.eval_on_selector("table tbody tr a", "e => e.addEventListener('click', ev => ev.preventDefault())")
        pg.click("table tbody tr a")
        pg.wait_for_timeout(900)
        kinds = [w for w in written if w["table"] == "journey_events"]
        if not kinds:
            bad.append("opening WhatsApp did not record anything against the person")
        elif kinds[0]["body"].get("kind") != "whatsapp_out":
            bad.append(f"recorded as {kinds[0]['body'].get('kind')}, expected whatsapp_out")
        if not [w for w in written if w["table"] == "carts" and w["method"] == "PATCH"]:
            bad.append("the cart was not marked as reminded")

        # 6. the quiet-customer group finds the one who bought long ago
        pg.click("text=Bought before, gone quiet")
        pg.wait_for_timeout(600)
        rows2 = pg.eval_on_selector_all("table tbody tr td:nth-child(2)",
                                        "e => e.map(x => x.textContent)")
        if not any("Meher" in r for r in rows2):
            bad.append("the customer who went quiet is not found")
        if any("Quiet Person" in r for r in rows2):
            bad.append("someone with no history was put in a group")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run()
print(f"=== outreach: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
