import json, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test as H
from fixtures import ROWS as FIX
from playwright.sync_api import sync_playwright

# route -> (fixture table, primary key column)
PAGES = [
    ("/products", "products", "product_id"),
    ("/contacts", "contacts", "contact_id"),
    ("/companies", "companies", "company_id"),
    ("/orders", "orders", "order_id"),
    ("/campaigns", "campaigns", "campaign_id"),
    ("/collections", "collections", "collection_id"),
    ("/showrooms", "showrooms", "showroom_id"),
    ("/shipments", "shipments", "shipment_id"),
    ("/payments", "payments", "payment_id"),
    ("/returns", "returns", "return_id"),
    ("/pipeline", "opportunities", "opportunity_id"),
    ("/activities", "activities", "activity_id"),
    ("/suppliers", "suppliers", "supplier_id"),
    ("/brands", "brands", "brand_id"),
    ("/expenses", "expenses", "expense_id"),
    ("/tasks", "tasks", "task_id"),
    ("/automations", "automations", "automation_id"),
    ("/templates", "message_templates", "template_id"),
    ("/broadcasts", "broadcasts", "broadcast_id"),
    ("/links", "links", "link_id"),
    ("/payables", "payables", "payable_id"),
]

# a row shaped like the one the user actually created: thin, with null relations
THIN = {
    "product_id": "db690de2-20e4-4fe2-bb6d-96c9ffd2ac48",
    "internal_sku": "idk", "public_product_name": "Some Saree",
    "source_product_name": None, "colour": "white maybe", "weave_or_motif": None,
    "fabric": None, "category": "Banarasi Saree", "description": "good stuff",
    "tags": "casual", "cost_price": "1000", "retail_price": "4000",
    "wholesale_price": "3000", "currency": "INR", "stock_qty": 1, "moq": 1,
    "status": "Review", "published_at": None,
    "created_at": "2026-11-11T12:38:53.709833+00:00",
    "brand_id": None, "availability": "In stock",
    "product_images": [{"public_url": "https://example.invalid/a.jpg", "is_primary": True}],
    "brands": None,
}

probs = []
with sync_playwright() as pw:
    b = pw.chromium.launch()
    ctx = b.new_context(viewport={"width": 1340, "height": 900})

    def handler(route):
        url = route.request.url
        if "/auth/v1/user" in url:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(H.USER))
        if "/auth/v1/token" in url:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(H.SESSION))
        if "/functions/v1/" in url:
            return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                {"openai": False, "gemini": True, "anthropic": False, "brand_set": True,
                 "departments": ["sales","marketing","operations","finance","customers"]}))
        body = H.body_for(url, "full")
        if "/rest/v1/products" in url:
            body = [THIN] + list(body)
        return route.fulfill(status=200, content_type="application/json",
                             headers={"content-range": "0-0/0"}, body=json.dumps(body))

    ctx.route("**stub.supabase.co/**", handler)
    pg = ctx.new_page()
    pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));" % json.dumps(H.SESSION))

    seen = []
    pg.on("pageerror", lambda e: seen.append(("PAGEERROR", str(e))))
    pg.on("console", lambda m: seen.append(("CONSOLE", m.text)) if m.type == "error" else None)

    def visit(label, url):
        del seen[:]
        try:
            pg.goto(url, wait_until="networkidle", timeout=25000)
            pg.wait_for_timeout(1500)
        except Exception as e:
            probs.append((label, "NAV", str(e)[:140])); return
        blank = pg.evaluate("document.body.innerText.trim().length < 40")
        for kind, msg in seen:
            if "ERR_TUNNEL" in msg or "example.invalid" in msg or "ERR_NAME" in msg:
                continue
            probs.append((label, kind, msg[:200]))
        if blank:
            probs.append((label, "BLANK", "page rendered almost no text"))

    # the exact row the user created
    visit("/products?id=<thin row>", "%s/products/?id=%s" % (H.BASE, THIN["product_id"]))

    # Clicking a row, not visiting its URL. The detail URL is built in JS, so a
    # path that double-prefixes the base path only shows up on a real click.
    for route in ("/products", "/contacts", "/orders", "/campaigns", "/brands"):
        del seen[:]
        try:
            pg.goto("%s%s/" % (H.BASE, route), wait_until="networkidle", timeout=25000)
            pg.wait_for_timeout(1200)
            row = pg.query_selector("table.table tbody tr button")
            if row is None:
                probs.append((route + " (click)", "NOROW", "no Open button to click")); continue
            row.click()
            pg.wait_for_timeout(1500)
        except Exception as e:
            probs.append((route + " (click)", "CLICK", str(e)[:140])); continue
        url = pg.url
        label = route + " (click)"
        if "crm101/crm101" in url:
            probs.append((label, "DOUBLE-BASE", url[:160]))
        elif "?id=" not in url:
            probs.append((label, "NO-ID", "clicking a row did not open a detail: " + url[:120]))
        if pg.evaluate("document.body.innerText.trim().length < 40"):
            probs.append((label, "BLANK", "detail left the page empty: " + url[:120]))
        for kind, msg in seen:
            if "ERR_TUNNEL" in msg or "example.invalid" in msg or "ERR_NAME" in msg:
                continue
            probs.append((label, kind, msg[:200]))

    # ids that match no row: what a stale or malformed link produces
    for bogus in ("undefined", "null", "00000000-0000-4000-8000-000000000999"):
        visit("/products?id=%s" % bogus, "%s/products/?id=%s" % (H.BASE, bogus))
        visit("/contacts?id=%s" % bogus, "%s/contacts/?id=%s" % (H.BASE, bogus))
        visit("/orders?id=%s" % bogus, "%s/orders/?id=%s" % (H.BASE, bogus))

    for route, table, pk in PAGES:
        rows = FIX.get(table) or []
        if rows and pk in rows[0]:
            visit("%s?id=existing" % route, "%s%s/?id=%s" % (H.BASE, route, rows[0][pk]))
        visit("%s?id=new" % route, "%s%s/?id=new" % (H.BASE, route))

    # The image viewer: click a product thumbnail, step through, close.
    del seen[:]
    try:
        pg.goto("%s/products/" % H.BASE, wait_until="networkidle", timeout=25000)
        pg.wait_for_timeout(1200)
        thumb = pg.query_selector(".thumb.clickable")
        if thumb is None:
            probs.append(("lightbox", "NOTHUMB", "no clickable product thumbnail"))
        else:
            thumb.click()
            pg.wait_for_timeout(600)
            if pg.query_selector(".lb") is None:
                probs.append(("lightbox", "NOOPEN", "clicking the thumbnail opened nothing"))
            else:
                pg.keyboard.press("ArrowRight")
                pg.wait_for_timeout(300)
                if pg.query_selector(".lb") is None:
                    probs.append(("lightbox", "ARROW", "arrow key closed the viewer"))
                pg.keyboard.press("Escape")
                pg.wait_for_timeout(400)
                if pg.query_selector(".lb") is not None:
                    probs.append(("lightbox", "NOCLOSE", "Escape did not close the viewer"))
                if pg.evaluate("document.body.style.overflow") == "hidden":
                    probs.append(("lightbox", "SCROLL", "page scroll left locked after closing"))
        for kind, msg in seen:
            if "ERR_TUNNEL" in msg or "example.invalid" in msg or "ERR_NAME" in msg:
                continue
            probs.append(("lightbox", kind, msg[:200]))
    except Exception as e:
        probs.append(("lightbox", "ERR", str(e)[:140]))

    b.close()

print("=== detail panels: %d problem(s) ===" % len(probs))
for label, kind, msg in probs:
    print("  %-26s %-10s %s" % (label, kind, msg))
sys.exit(1 if probs else 0)
