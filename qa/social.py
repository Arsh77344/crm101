# The always-on social planner: a week drafted, reviewed, and only then written
# to the content calendar.
#
# The assertion this file exists for is the hashtag one. A tag written from
# memory is worse than no tag -- it puts the brand in a feed nobody reads -- so
# the function strips tags when it could not search, and the page has to say so
# rather than showing an empty field and letting the owner assume it found none.
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}

OCC = [{
    "occasion_id": "margazhi", "name": "Margazhi Test", "occasion_date": None,
    "until_date": None, "date_basis": "Fixed", "lead_weeks": 3, "kind": "Retail moment",
    "region": "Tamil Nadu", "meaning": None, "what_sells": None, "avoid": None, "note": None,
    "active": True, "created_at": "2026-01-01T00:00:00Z",
    "promote_from": None, "days_away": None, "days_until_promote": None,
}]

PLAN = {
  "say": "Four posts, built on the weave rather than the festival.",
  "title": "Reading a border",
  "occasion_id": "margazhi",
  "research": [
    {"kind": "hashtag", "what": "#kanjivaram", "found": "about 1.2M posts, mostly resellers",
     "where": "checked on Instagram search"},
    {"kind": "format", "what": "slow loom close-ups",
     "found": "weaving videos holding attention past 15s", "where": "a craft account's recent reels"},
  ],
  "posts": [
    {"day_offset": 0, "channel": "Instagram", "placement": "Feed",
     "title": "What a shikargah actually depicts", "body": "A hunting forest, woven in silk.",
     "hashtags": "#banarasi #shikargah #handloom", "hashtag_note": "Mid-sized, craft audience.",
     "cta": "Ask us about this one", "product_id": "P1",
     "art_direction": "Macro of the border.", "teaches": "What the motif depicts."},
    {"day_offset": 3, "channel": "Instagram", "placement": "Reel",
     "title": "Drawn on graph paper first", "body": "The naqsha comes before a single thread.",
     "hashtags": "#naqsha #banarasiweave", "hashtag_note": "Small, almost no competition.",
     "cta": "Watch the full process", "product_id": None,
     "art_direction": "Hands on the graph.", "teaches": "That a saree is designed before woven."},
  ],
  "replies": [
    {"question": "Is the zari real?", "answer": "Yes, and here is how you can tell."},
    {"question": "Can it reach Chennai by Friday?", "answer": "Tell us the pincode and we will check."},
  ],
  "needs_shooting": [{"product_id": "P2", "why": "Rose Tissue has no photographs yet."}],
  "carries_campaign": {"campaign_id": "C1", "name": "Winter Wedding Test",
                       "how": "Each post takes a different part of its spine."},
  "days": 7, "market": "Tamil Nadu",
}

PRODUCTS = [
  {"product_id": "P1", "public_product_name": "Cool Blue Zigzag", "status": "Published"},
  {"product_id": "P2", "public_product_name": "Rose Tissue", "status": "Published"},
]


def run(searched=True):
    bad = []
    state = {"sent": [], "plans": [], "posts": []}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1340, "height": 950})

        def handler(route):
            req = route.request
            u = req.url
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(SESSION))
            if "/functions/v1/social-agent" in u:
                try: body = json.loads(req.post_data or "{}")
                except Exception: body = {}
                if body.get("action") == "health":
                    return route.fulfill(status=200, content_type="application/json",
                        body=json.dumps({"openai": True, "gemini": True, "anthropic": True,
                                         "groq": True, "brand_set": True,
                                         "can_search": {"openai": True, "gemini": True,
                                                        "anthropic": True, "groq": False}}))
                state["sent"].append(body)
                plan = dict(PLAN)
                if not searched:
                    # What the function really does when it could not search.
                    plan = dict(PLAN)
                    plan["research"] = []
                    plan["posts"] = [dict(p, hashtags="",
                                          hashtag_note="No tags: the model could not search "
                                                       "this turn, so none were verified.")
                                     for p in PLAN["posts"]]
                return route.fulfill(status=200, content_type="application/json",
                    body=json.dumps({"ok": True, "provider": "openai", "model": "m",
                                     "searched": searched, "plan": plan}))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"ok": True}))

            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            if req.method == "POST":
                try: sent = json.loads(req.post_data or "[]")
                except Exception: sent = []
                rows = sent if isinstance(sent, list) else [sent]
                if t == "social_plans":
                    state["plans"].extend(rows)
                    return route.fulfill(status=201, content_type="application/json",
                        body=json.dumps([{**rows[0], "plan_id": "PLAN1"}]))
                if t == "campaign_posts":
                    state["posts"].extend(rows)
                    return route.fulfill(status=201, content_type="application/json",
                                         body=json.dumps(rows))
                return route.fulfill(status=201, content_type="application/json",
                                     body=json.dumps(rows))
            data = {
                "occasions_upcoming": OCC, "products": PRODUCTS, "social_plans": [],
                "profiles": [{"id": USER["id"], "email": USER["email"],
                              "full_name": "Mohammad Arsh", "role": "owner"}],
                "settings": [{"setting_key": "brand_name", "setting_value": "Zarivia"}],
            }.get(t, [])
            return route.fulfill(status=200, content_type="application/json",
                headers={"content-range": "0-0/0"}, body=json.dumps(data))

        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))
        pg.goto(BASE + "/social/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(700)

        # 1. nothing is written before anything is asked for
        if state["plans"] or state["posts"]:
            bad.append("the page wrote to the database on load")

        # 2. the brief, the market and the week go to the agent
        pg.fill("textarea", "Push the two blue pieces.")
        pg.fill("input[placeholder*='South India']", "Tamil Nadu")
        pg.click("button.btn-primary")
        pg.wait_for_timeout(1800)
        if not state["sent"]:
            bad.append("pressing Plan sent nothing to the agent")
        else:
            s = state["sent"][0]
            if s.get("action") != "plan":
                bad.append(f"the agent was asked for {s.get('action')!r}")
            if "blue pieces" not in str(s.get("brief") or ""):
                bad.append("the brief did not reach the agent")
            if s.get("market") != "Tamil Nadu":
                bad.append(f"the market did not reach the agent: {s.get('market')!r}")
            if s.get("days") != 7:
                bad.append(f"the week length did not reach the agent: {s.get('days')!r}")
            if s.get("search") is not True:
                bad.append("the agent was not asked to look up what is trending")

        after = pg.inner_text("body")

        # 3. the week is readable: captions, what each teaches, the shot
        for p in PLAN["posts"]:
            if p["title"] not in after:
                bad.append(f"the post {p['title']!r} is not shown")
            if p["body"] not in after:
                bad.append(f"the caption for {p['title']!r} is not shown")
            if p["teaches"] not in after:
                bad.append(f"what {p['title']!r} teaches is not shown")
        if PLAN["say"] not in after:
            bad.append("the agent's own summary is not shown")
        if "Rose Tissue has no photographs" not in after:
            bad.append("a piece it wanted but could not shoot is not called out")

        # The campaign the week is carrying has to be named and reachable, or
        # the owner cannot tell a coordinated week from an invented one.
        carries = pg.query_selector("[data-carries]")
        if not carries:
            bad.append("the week does not say which campaign it is carrying")
        else:
            said = carries.inner_text()
            if PLAN["carries_campaign"]["name"] not in said:
                bad.append(f"the carried campaign is not named: {said[:80]}")
            if PLAN["carries_campaign"]["how"] not in said:
                bad.append("the week does not say how it serves the campaign")
            href = carries.query_selector("a").get_attribute("href")
            if not href or PLAN["carries_campaign"]["campaign_id"] not in href:
                bad.append(f"the carried campaign does not open ({href})")
        for r in PLAN["replies"]:
            if r["question"] not in after:
                bad.append(f"the drafted reply to {r['question']!r} is missing")

        # 4. the research is shown with where it came from, not just the tags
        res = pg.query_selector("[data-research]")
        if searched and not res:
            bad.append("what it looked up is not shown")
        elif searched:
            said = res.inner_text()
            for r in PLAN["research"]:
                if r["what"] not in said:
                    bad.append(f"the research is missing {r['what']!r}")
                if r["where"] not in said:
                    bad.append(f"{r['what']!r} is shown without where it was found")

        # 5. THE ONE THAT MATTERS. A week that could not search carries no tags,
        # and the page says so rather than leaving a silent blank.
        warn = pg.query_selector("[data-unverified]")
        tags_on_page = PLAN["posts"][0]["hashtags"] in after
        if searched:
            if warn:
                bad.append("a searched week is wrongly warned as unverified")
            if not tags_on_page:
                bad.append("a searched week shows no hashtags")
        else:
            if not warn:
                bad.append("a week planned without search does not say its tags are missing")
            if tags_on_page:
                bad.append("a week planned without search is showing hashtags anyway")

        # 6. approval writes the plan and its posts, and nothing else does
        pg.click("[data-posts] ~ *, .card .btn-primary")
        pg.wait_for_timeout(100)
        buttons = pg.query_selector_all("button.btn-primary")
        for btn in buttons:
            if "calendar" in (btn.inner_text() or "").lower():
                btn.click()
                break
        pg.wait_for_timeout(1500)

        if len(state["plans"]) != 1:
            bad.append(f"approval wrote {len(state['plans'])} plans, expected 1")
        if len(state["posts"]) != len(PLAN["posts"]):
            bad.append(f"approval wrote {len(state['posts'])} posts, "
                       f"expected {len(PLAN['posts'])}")
        else:
            for row in state["posts"]:
                if row.get("plan_id") != "PLAN1":
                    bad.append("a post was written without its plan")
                if row.get("campaign_id") is not None:
                    bad.append("an always-on post was written against a campaign")
                if row.get("status") != "Idea":
                    bad.append(f"a post was saved as {row.get('status')!r}, expected Idea")
            days = sorted({row["scheduled_for"][:10] for row in state["posts"]})
            if len(days) != 2:
                bad.append(f"the posts landed on {days}, expected two different days")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad


probs = run(searched=True) + [f"(no search) {p}" for p in run(searched=False)]
print(f"=== social: {len(probs)} problem(s) across both a searched and an unsearched week ===")
for p in probs:
    print("  " + p)
sys.exit(1 if probs else 0)
