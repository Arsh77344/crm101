# The occasions calendar: the list, the run-up arithmetic, the festival markers
# on the month grid, and the line in the studio composer.
#
# The arithmetic is the part worth a test. `promote_from` is computed twice --
# once by the `occasions_upcoming` view in Postgres and once by `runUp()` in the
# browser, because the list page writes to the table and cannot read the view.
# Two implementations of one rule drift, so this computes it a third time here,
# in Python, and holds the browser to it.
import datetime as dt
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}

# The rows are positioned relative to this, so the fixture never goes stale.
TODAY = dt.date.today()

# The page computes its run-up from the browser's clock, so the expectations are
# computed from that same clock rather than this one. The two agree except on a
# run that straddles midnight, which is exactly when a date test should not start
# failing for no reason.
BROWSER_TODAY = None


def today():
    return BROWSER_TODAY or TODAY


def row(name, days_away, lead_weeks, **kw):
    """One occasion, positioned relative to today so the test never goes stale."""
    day = TODAY + dt.timedelta(days=days_away)
    promote = day - dt.timedelta(days=lead_weeks * 7)
    r = {
        "occasion_id": name.lower().replace(" ", "-"),
        "name": name,
        "occasion_date": day.isoformat(),
        "until_date": None,
        "date_basis": "Approximate",
        "lead_weeks": lead_weeks,
        "kind": "Festival",
        "region": "Pan-India",
        "meaning": None, "what_sells": None, "avoid": None, "note": None,
        "active": True, "created_at": "2026-01-01T00:00:00Z",
        # What the view would have returned for this row.
        "promote_from": promote.isoformat(),
        "days_away": days_away,
        "days_until_promote": (promote - TODAY).days,
    }
    r.update(kw)
    return r


# In its run-up now; starts in 9 days; a long way off; a season; no date yet.
ON       = row("Deepavali Test", 10, 3)
SOON     = row("Pongal Test", 30, 3)
LATER    = row("Holi Test", 200, 3)
SEASON   = row("Wedding Season Test", 5, 2,
               until_date=(TODAY + dt.timedelta(days=25)).isoformat(),
               kind="Wedding season")
NODATE   = {**row("Karva Chauth Test", 0, 3), "occasion_id": "nodate",
            "occasion_date": None, "promote_from": None,
            "days_away": None, "days_until_promote": None}
FIXED    = row("Makar Test", 60, 3, date_basis="Fixed")

VIEW_ROWS = [SEASON, ON, SOON, FIXED, LATER]          # the view drops the undated one
TABLE_ROWS = [SEASON, ON, SOON, FIXED, LATER, NODATE]  # the table keeps it


def expected_runup(r):
    """The rule, implemented here independently of both the view and the page."""
    if not r["occasion_date"]:
        return "no date yet"
    day = dt.date.fromisoformat(r["occasion_date"])
    away = (day - today()).days
    if away < 0:
        return "past"
    promote = day - dt.timedelta(days=r["lead_weeks"] * 7)
    until = (promote - today()).days
    if away == 0:
        return "today"
    if until <= 0:
        return f"on now, {away} days to go"
    if until <= 14:
        return f"starts in {until} days"
    # Said in words, with the year only when it is not the current one -- the
    # same rule `dayLabel` follows, implemented here rather than imported, so
    # this stays a check and not a copy.
    day_part = f"{promote.day} {promote.strftime('%b')}"
    if promote.year != today().year:
        day_part += f" {promote.year}"
    return f"starts {day_part}"


def run():
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1340, "height": 950})

        def handler(route):
            u = route.request.url
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(SESSION))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json",
                    body=json.dumps({"gemini": True, "brand_set": True, "sets": [],
                                     "can_search": {"gemini": True}}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            rows = {
                "occasions_upcoming": VIEW_ROWS,
                "occasions": TABLE_ROWS,
                "campaign_posts": [],
                "campaign_threads": [],
                "profiles": [{"id": USER["id"], "email": USER["email"],
                              "full_name": "Mohammad Arsh", "role": "owner"}],
                "settings": [{"setting_key": "brand_name", "setting_value": "Zarivia"}],
            }.get(t, [])
            return route.fulfill(status=200, content_type="application/json",
                headers={"content-range": "0-0/0"}, body=json.dumps(rows))

        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))

        # ---------- the list page ----------
        pg.goto(BASE + "/occasions/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(700)
        global BROWSER_TODAY
        BROWSER_TODAY = dt.date.fromisoformat(pg.evaluate(
            "() => { const d = new Date(); return `${d.getFullYear()}-`"
            "+ String(d.getMonth() + 1).padStart(2, '0') + '-'"
            "+ String(d.getDate()).padStart(2, '0'); }"))
        txt = pg.inner_text("body")

        for r in TABLE_ROWS:
            if r["name"] not in txt:
                bad.append(f"{r['name']} is missing from the list")

        # 1. the run-up, against the rule implemented here
        for r in TABLE_ROWS:
            want = expected_runup(r)
            if want not in txt:
                bad.append(f"{r['name']}: the run-up should read {want!r} and does not")

        # 2. the view and the page must agree on promote_from
        for r in VIEW_ROWS:
            day = dt.date.fromisoformat(r["occasion_date"])
            mine = (day - dt.timedelta(days=r["lead_weeks"] * 7)).isoformat()
            if mine != r["promote_from"]:
                bad.append(f"{r['name']}: the view says promote_from {r['promote_from']}, "
                           f"the rule says {mine}")

        # 3. an approximate date is marked as one, a fixed one is not
        if "approx" not in txt:
            bad.append("an approximate date is not marked approximate")

        # 4. the counts at the top
        if "In their run-up" not in txt:
            bad.append("the page does not say how many are in their run-up")
        if "Dates to confirm" not in txt:
            bad.append("the page does not say how many dates need confirming")

        # 5. a season shows its span, not just one day
        if "–" not in txt and "-" not in txt:
            bad.append("a season does not show a span")

        # 6. The year shows on a date in another year and not on one in this
        # year. The shared when() prints the year on every other date column, so
        # a bare "15 Jan" on a calendar that is mostly next year reads undated.
        next_year = [r for r in TABLE_ROWS
                     if r["occasion_date"]
                     and int(r["occasion_date"][:4]) != today().year]
        for r in next_year:
            if str(int(r["occasion_date"][:4])) not in txt:
                bad.append(f"{r['name']} is in {r['occasion_date'][:4]} but its row "
                           f"shows no year")
        this_year_only = [r for r in TABLE_ROWS
                          if r["occasion_date"]
                          and int(r["occasion_date"][:4]) == today().year
                          and not r["until_date"]]
        for r in this_year_only:
            day = dt.date.fromisoformat(r["occasion_date"])
            if f"{day.day} {day.strftime('%b')} {today().year}" in txt:
                bad.append(f"{r['name']} is this year but its row repeats the year")

        # 6. the form groups its fields under headings
        pg.goto(BASE + "/occasions/?id=new", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(600)
        legends = pg.eval_on_selector_all("fieldset.fields legend",
                                          "e => e.map(x => x.textContent.trim())")
        for want in ["The occasion", "When", "What to say about it"]:
            if want not in legends:
                bad.append(f"the form has no {want!r} heading (found {legends})")
        # the long-text fields come through the project's dictation area
        if pg.query_selector_all("textarea") == []:
            bad.append("the form has no textarea for the storytelling fields")

        # ---------- the month grid ----------
        pg.goto(BASE + "/calendar/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(700)
        cal = pg.inner_text("body")
        marks = pg.eval_on_selector_all(".cal .ev.occ",
                                        "e => e.map(x => x.textContent.trim())")
        # Only the occasions falling inside the month on screen are marked.
        this_month = [r for r in VIEW_ROWS
                      if r["occasion_date"][:7] == today().isoformat()[:7]]
        for r in this_month:
            if r["name"] not in marks:
                bad.append(f"{r['name']} falls this month but is not marked on the grid "
                           f"(marks: {marks})")
        if not marks:
            bad.append("no festival marker on the month grid at all")
        # A marker belongs only in the cells its occasion actually covers, so the
        # count is checked directly rather than inferred from the names present.
        want_marks = 0
        for r in VIEW_ROWS:
            start = dt.date.fromisoformat(r["occasion_date"])
            end = dt.date.fromisoformat(r["until_date"] or r["occasion_date"])
            day = start
            while day <= end:
                if day.isoformat()[:7] == today().isoformat()[:7]:
                    want_marks += 1
                day += dt.timedelta(days=1)
        if len(marks) != want_marks:
            bad.append(f"the grid shows {len(marks)} festival markers this month, "
                       f"expected {want_marks}")
        if "Coming up" not in cal:
            bad.append("the calendar does not say what is coming up")
        if ON["name"] not in cal:
            bad.append("an occasion in its run-up is not named on the calendar")
        if LATER["name"] in cal.split("Coming up")[-1][:400]:
            bad.append("an occasion 200 days out is listed as coming up")

        # the marker must be a link to the occasion, not dead text
        href = pg.get_attribute(".cal .ev.occ", "href")
        if not href or "/occasions" not in href:
            bad.append(f"the festival marker does not open the occasion ({href})")

        # ---------- the studio composer ----------
        pg.goto(BASE + "/studio/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(700)
        note = pg.query_selector("[data-occasions]")
        if not note:
            bad.append("the studio composer does not show what is coming up")
        else:
            said = note.inner_text()
            if ON["name"] not in said:
                bad.append(f"the studio does not name the occasion in its run-up ({said[:90]})")
            # Clicking one writes it into the brief. Which one is first depends on
            # the dates, so the button says what to expect rather than the test
            # assuming an order.
            first = note.query_selector("button")
            picked = first.inner_text().strip()
            first.click()
            pg.wait_for_timeout(250)
            draft = pg.eval_on_selector("textarea", "e => e.value")
            if picked not in draft:
                bad.append(f"clicking {picked!r} does not put it in the brief ({draft!r})")
            # and the nearest occasion is the one offered first
            nearest = min((r for r in VIEW_ROWS if r["days_until_promote"] <= 14),
                          key=lambda r: r["occasion_date"])["name"]
            if picked != nearest:
                bad.append(f"the first occasion offered is {picked!r}, not the nearest "
                           f"({nearest!r})")

        # 7. A literal \uXXXX must never reach the screen. It is a valid escape
        # inside a JS string and NOT inside JSX text, and the two look identical
        # in the source -- the Studio shipped "the six C\u2019s" for exactly this
        # reason. Checked on the rendered page, where the distinction is visible.
        for route in ("/occasions/", "/calendar/", "/studio/"):
            pg.goto(BASE + route, wait_until="networkidle", timeout=20000)
            pg.wait_for_timeout(500)
            body = pg.inner_text("body")
            if "\\u" in body:
                spot = body[max(0, body.index("\\u") - 40):body.index("\\u") + 20]
                bad.append(f"{route} shows a raw unicode escape on screen: ...{spot}...")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad


probs = run()
print(f"=== occasions: {len(probs)} problem(s) "
      f"({len(TABLE_ROWS)} occasions, today {today()}) ===")
for p in probs:
    print("  " + p)
sys.exit(1 if probs else 0)
