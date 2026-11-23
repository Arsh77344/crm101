# The customer's tracking page. The function is stubbed, so this tests the page:
# what a real token shows, what every kind of wrong token shows, and that
# nothing internal reaches a page anyone holding the link can open.
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
GOOD = "2eb7d15d8d42194f2d5dfebc982bd36a"

SPLIT = {
  "ok": True, "brand": "Zarivia", "order_number": "ZRV-1044",
  "ordered_at": "2026-11-18T09:00:00Z", "name": "Alice", "to": "Delhi, Delhi",
  "split": True,
  "parcels": [
    {"parcel": 1, "pieces": [{"name": "Midnight Blue Katan", "quantity": 1}],
     "status": "On its way", "courier": "Delhivery Surface", "awb": "DL298447",
     "tracking_url": "https://shiprocket.co/tracking/DL298447",
     "shipped_at": "2026-11-19T06:00:00Z", "delivered_at": None,
     "updated_at": "2026-11-21T06:00:00Z",
     "steps": [{"at": "2026-11-20T11:00:00Z", "what": "In transit", "where": "Kanpur"},
               {"at": "2026-11-19T06:00:00Z", "what": "Picked up", "where": "Varanasi"}]},
    {"parcel": 2, "pieces": [{"name": "Rose Tissue", "quantity": 2}],
     "status": "Being prepared", "courier": None, "awb": None, "tracking_url": None,
     "shipped_at": None, "delivered_at": None, "updated_at": None, "steps": []}]}

def run():
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 760, "height": 1200})
        ctx.set_default_timeout(5000)
        def handler(route):
            tok = json.loads(route.request.post_data or "{}").get("token", "")
            if tok == GOOD:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(SPLIT))
            return route.fulfill(status=404, content_type="application/json",
                                 body=json.dumps({"error": "That tracking link is not valid."}))
        ctx.route("**/functions/v1/track", handler)
        pg = ctx.new_page()
        errs = []
        pg.on("pageerror", lambda e: errs.append(str(e)[:120]))

        # 1. a real token shows the order and both parcels, each tracked alone
        pg.goto(f"{BASE}/track/?t={GOOD}", wait_until="networkidle", timeout=25000)
        pg.wait_for_timeout(900)
        txt = pg.inner_text("body")
        for want in ("ZRV-1044", "Alice", "Parcel 1", "Parcel 2",
                     "Midnight Blue Katan", "Rose Tissue", "On its way",
                     "Being prepared", "DL298447", "2 parcels", "different days"):
            if want not in txt:
                bad.append(f"the page does not show {want!r}")
        if "Rose Tissue × 2" not in txt:
            bad.append("a quantity above one is not shown")
        links = pg.eval_on_selector_all("a[href*='shiprocket']",
                                        "e => e.map(x => [x.href, x.rel, x.target])")
        if len(links) != 1:
            bad.append(f"expected one courier link, got {len(links)}")
        elif "noopener" not in links[0][1]:
            bad.append("the courier link does not carry rel=noopener")
        if "not collected this one yet" not in txt:
            bad.append("the unbooked parcel does not explain itself")

        # 2. nothing internal on a page anyone with the link can open
        for secret in ("Rehman", "Kala Weaves", "brand_id", "cost", "margin",
                       "pickup", "Thatheri", "service_role", "₹"):
            if secret.lower() in txt.lower():
                bad.append(f"{secret!r} appears on the customer page")

        pg.screenshot(path="/home/claude/shots/track-ok.png", full_page=True)

        # 3. every wrong token says the same thing and shows no order
        for label, tok in [("a wrong token", "0" * 32), ("an order number", "ZRV-1044"),
                           ("no token", ""), ("a quoted token", "'%20or%201=1")]:
            pg.goto(f"{BASE}/track/?t={tok}", wait_until="networkidle", timeout=25000)
            pg.wait_for_timeout(700)
            t = pg.inner_text("body")
            if "Not available" not in t:
                bad.append(f"{label} did not refuse")
            if "ZRV-1044" in t and tok != GOOD:
                bad.append(f"{label} leaked an order")
            if "Failed to fetch" in t or "TypeError" in t:
                bad.append(f"{label} shows a raw browser error to the customer")

        bad.extend(errs)
        b.close()
    return bad

probs = run()
print(f"=== customer tracking: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)
