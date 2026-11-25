# Shiprocket, now one parcel per vendor: what it says unconnected, what it
# refuses to book, that each vendor is quoted from its own pincode, and that a
# booking carries the courier chosen for that vendor and no other.
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}
READY = {"order_id": "O1", "order_number": "ZRV-1001", "order_status": "Processing",
         "total": 23500, "currency": "INR", "payment_method": "Prepaid", "weight_kg": 1.2,
         "ship_name": "Asha Verma", "ship_phone": "9811111111", "ship_line1": "12 Rose Lane",
         "ship_city": "Delhi", "ship_state": "Delhi", "ship_pincode": "110001",
         "ship_country": "India", "order_items": [{"order_item_id": "I1"}, {"order_item_id": "I2"}],
         "contacts": {"full_name": "Asha Verma"}}
SHORT = {"order_id": "O2", "order_number": "ZRV-1002", "order_status": "Draft",
         "total": 9000, "currency": "INR", "payment_method": "COD",
         "ship_name": "Ravi K", "ship_city": "Pune", "order_items": [],
         "contacts": {"full_name": "Ravi K"}}

# Two vendors in one order: one ready to ship, one whose address Shiprocket has
# never been told about.
VENDORS = {"ok": True, "order_gaps": [], "vendors": [
    {"brand_id": "b1", "brand_name": "Rehman Looms", "pickup": "Rehman Varanasi",
     "pickup_pincode": "221001", "registered": True, "lines": 1, "units": 1,
     "value": 13500, "gaps": []},
    {"brand_id": "b2", "brand_name": "Kala Weaves", "pickup": "Kala Surat",
     "pickup_pincode": "395003", "registered": False, "lines": 1, "units": 1,
     "value": 10000,
     "gaps": ["Kala Weaves's pickup address is not registered with Shiprocket yet"]}]}

def vendors_after_register():
    out = json.loads(json.dumps(VENDORS))
    out["vendors"][1].update(registered=True, gaps=[])
    return out

RATE_ROWS = {
    "b1": [{"courier_id": 51, "name": "Delhivery Surface", "rate": 78, "etd": "25 Nov",
            "days": 3, "rating": 4.6, "cod": 1},
           {"courier_id": 14, "name": "Bluedart Air", "rate": 142, "etd": "23 Nov",
            "days": 1, "rating": 4.8, "cod": 0}],
    "b2": [{"courier_id": 77, "name": "Ekart Surface", "rate": 64, "etd": "26 Nov",
            "days": 4, "rating": 4.2, "cod": 1},
           {"courier_id": 14, "name": "Bluedart Air", "rate": 188, "etd": "24 Nov",
            "days": 2, "rating": 4.8, "cod": 0}],
}


def step(bad, what, fn):
    """Run an interaction; a failure is recorded, not raised, so the remaining
    checks still run and the report lists every problem at once."""
    try:
        fn()
        return True
    except Exception as e:
        bad.append(f"{what}: {type(e).__name__} {str(e).splitlines()[0][:90]}")
        return False

def run(configured=True):
    bad, calls = [], []
    registered = {"done": False}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1400, "height": 980})
        ctx.set_default_timeout(4000)
        def handler(route):
            u, req = route.request.url, route.request
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/shiprocket" in u:
                body = json.loads(req.post_data or "{}")
                calls.append(body)
                a = body.get("action")
                J = lambda o: route.fulfill(status=200, content_type="application/json",
                                            body=json.dumps(o))
                if a == "health":
                    return J({"configured": True, "connected": True,
                              "pickups": {"vendors": 2, "registered": 1,
                                          "waiting": ["Kala Weaves"], "fallback": "Primary"}}
                             if configured else
                             {"configured": False, "connected": False,
                              "pickups": {"vendors": 2, "registered": 0, "waiting": []},
                              "note": "Add SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD."})
                if a == "vendors":
                    return J(vendors_after_register() if registered["done"] else VENDORS)
                if a == "add_pickup":
                    registered["done"] = True
                    return J({"ok": True, "nickname": "Kala Surat"})
                if a == "rates":
                    bid = body.get("brand_id")
                    rows = RATE_ROWS.get(bid, [])
                    return J({"ok": True, "vendors": [
                        {"brand_id": bid,
                         "brand_name": "Rehman Looms" if bid == "b1" else "Kala Weaves",
                         "from": "221001" if bid == "b1" else "395003",
                         "weight": 0.6, "couriers": rows}], "couriers": rows})
                if a == "book":
                    want = body.get("brand_id")
                    pick = (body.get("couriers") or {})
                    made = []
                    for v in VENDORS["vendors"]:
                        if want and v["brand_id"] != want:
                            continue
                        made.append({"brand_name": v["brand_name"], "shipment_id": "S" + v["brand_id"],
                                     "awb": "AWB" + v["brand_id"].upper(),
                                     "courier": "Chosen " + str(pick.get(v["brand_id"], "none")),
                                     "pickup": True, "label_url": "https://x.test/l.pdf",
                                     "from": v["pickup"]})
                    return J({"ok": True, "parcels": made, "booked": len(made), "failed": 0})
                if a == "sync":
                    return J({"ok": True, "checked": 3})
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            rows = {"orders": [READY, SHORT], "shipments": [],
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
        pg.goto(BASE + "/shipments/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(1000)
        txt = pg.inner_text("body")

        if not configured:
            if "not connected" not in txt.lower():
                bad.append("an unconnected Shiprocket does not say so")
            if "API User" not in txt:
                bad.append("it does not say how to connect")
            if "own door" not in txt and "that brand" not in txt:
                bad.append("it does not say vendor addresses go on the brand")
            b.close(); return bad + [e[:140] for e in errs if "favicon" not in e.lower()]

        # 1. the destination gaps still stop an order before any vendor is asked
        if "Still needs" not in txt:
            bad.append("an order missing details is not flagged")
        for needed in ("a phone", "an address", "a pincode", "line items", "a weight"):
            if needed not in txt:
                bad.append(f"the gap list does not mention {needed!r}")

        # 2. how many vendors still owe an address is said up front
        if "1 of 2 vendors" not in txt:
            bad.append("it does not say how many vendors have a registered pickup")
        if "Kala Weaves" not in txt:
            bad.append("it does not name the vendor still waiting")

        # 3. opening an order shows one block per vendor
        step(bad, "could not open the order's parcels",
             lambda: pg.get_by_role("button", name="Parcels").first.click())
        pg.wait_for_timeout(900)
        heads = pg.eval_on_selector_all(".card .card .card-head h3",
                                        "e => e.map(x => x.textContent.trim())")
        if heads != ["Rehman Looms", "Kala Weaves"]:
            bad.append(f"one block per vendor was not drawn: {heads}")
        body2 = pg.inner_text("body")
        if "2 parcels" not in body2:
            bad.append("it does not say the order is two parcels")
        if "221001" not in body2 or "Rehman Varanasi" not in body2:
            bad.append("a vendor's own pickup point is not shown")
        badges = pg.eval_on_selector_all(".card .card .card-head .badge",
                                          "e => e.map(x => x.textContent.trim())")
        if badges != ["Pickup ready", "No pickup yet"]:
            bad.append(f"each vendor does not show its pickup state: {badges}")

        # 4. the unregistered vendor is blocked, with a way to fix it
        warns = pg.eval_on_selector_all(".card .card .note.warn",
                                         "e => e.map(x => x.textContent.trim())")
        if not any("not registered" in w for w in warns):
            bad.append(f"the unregistered vendor is not warned about: {warns}")
        if pg.get_by_role("button", name="Register pickup").count() != 1:
            bad.append("there is no register-pickup button for the vendor that needs one")
        # only the ready vendor may be quoted
        if pg.get_by_role("button", name="Rates").count() != 1:
            bad.append("a blocked vendor was offered rates")

        # 5. each vendor is quoted on its own, by brand
        step(bad, "could not ask for the first vendor's rates",
             lambda: pg.get_by_role("button", name="Rates").first.click())
        pg.wait_for_timeout(900)
        rated = [c for c in calls if c.get("action") == "rates"]
        if len(rated) != 1 or rated[0].get("brand_id") != "b1":
            bad.append(f"rates were not asked per vendor: {rated}")
        names = pg.eval_on_selector_all(".card .card table tbody tr td:first-child",
                                         "e => e.map(x => x.textContent.trim())")
        if names[:2] != ["Delhivery Surface", "Bluedart Air"]:
            bad.append(f"that vendor's couriers not listed cheapest first: {names}")
        if "Ekart Surface" in names:
            bad.append("one vendor's quote leaked into the other's block")

        # 6. registering the second vendor unblocks it
        step(bad, "could not register the second vendor's pickup",
             lambda: pg.get_by_role("button", name="Register pickup").click())
        pg.wait_for_timeout(900)
        if not [c for c in calls if c.get("action") == "add_pickup"]:
            bad.append("Register pickup did not call add_pickup")
        if pg.get_by_role("button", name="Rates").count() != 2:
            bad.append("the registered vendor still cannot be quoted")

        # 7. a booking carries the courier chosen for that vendor
        picked = step(bad, "no courier could be chosen for a vendor",
             lambda: pg.get_by_role("button", name="Choose").first.click())
        pg.wait_for_timeout(300)
        if picked and pg.eval_on_selector_all(".card .card .btn.on", "e => e.length") != 1:
            bad.append("the chosen courier is not marked as chosen")
        if pg.eval_on_selector_all(".card .card .btn-primary", "e => e.length") > 1:
            bad.append("more than one primary button inside a vendor card")
        pg.wait_for_timeout(300)
        if picked:
            step(bad, "could not book the chosen parcel",
                 lambda: pg.get_by_role("button", name="Book this parcel").first.click())
        pg.wait_for_timeout(1200)
        booked = [c for c in calls if c.get("action") == "book"]
        if len(booked) != 1:
            bad.append(f"{len(booked)} booking calls, expected 1")
        else:
            if booked[0].get("brand_id") != "b1":
                bad.append(f"booked for {booked[0].get('brand_id')}, expected b1")
            if (booked[0].get("couriers") or {}).get("b1") != 51:
                bad.append(f"booked with {booked[0].get('couriers')}, expected b1 -> 51")
            if "b2" in (booked[0].get("couriers") or {}):
                bad.append("a vendor with no choice was booked anyway")
        after = pg.inner_text("body")
        if "AWBB1" not in after:
            bad.append("the AWB is not shown after booking")
        if "Rehman Varanasi" not in after:
            bad.append("it does not say which address the parcel leaves from")

        # 7b. no hand-written colour where the project has a class for it
        inline = pg.eval_on_selector_all(
            ".card [style*='--neg'], .card [style*='color: rgb']",
            "e => e.map(x => x.getAttribute('style'))")
        if inline:
            bad.append(f"a colour is written by hand: {inline[:2]}")

        # 8. tracking can be pulled on demand
        step(bad, "could not press Update tracking",
             lambda: pg.get_by_role("button", name="Update tracking").click())
        pg.wait_for_timeout(900)
        if not [c for c in calls if c.get("action") == "sync"]:
            bad.append("Update tracking did not ask the courier")
        if "Tracking —" in pg.inner_text("body"):
            bad.append("the tracking message is shown as if it were a parcel")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run(configured=True) + [f"(not configured) {x}" for x in run(configured=False)]
print(f"=== shiprocket: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
