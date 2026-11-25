# The campaign studio: a conversation that holds a brief, a draft beside it, and
# an approval that is the only thing that writes to the calendar.
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}
PROPOSAL = {
  "campaign_name": "Winter Wedding — Midnight Blue",
  "objective": "Sales", "audience_note": "Wedding guests, 25-40, metros",
  "channel": "Instagram", "start_date": "2026-11-25", "end_date": "2026-12-09",
  "budget": 15000, "offer": "Free blouse stitching",
  "brief": "Clear three pieces of blue stock before the December dates.",
  "art_direction": "Low evening light, warm stone.", "look_id": None,
  "spine": "The shikargah hunt scene has been woven in Banaras for four hundred years.",
  "occasion": {"occasion_id": "wedding-season-winter", "name": "Wedding season, winter",
               "why": "The December dates are when a trousseau is actually bought."},
  "channel_plan": [
    {"channel": "Instagram feed", "role": "First impression: the piece shot properly.",
     "cadence": "Twice a week", "first_move": "Shoot the border macro on Tuesday.",
     "hands_off_to": "Instagram stories"},
    {"channel": "WhatsApp", "role": "Where a raised hand is answered and the sale closes.",
     "cadence": "Only on reply", "first_move": "Answer every story reply within the hour.",
     "hands_off_to": "The showroom"},
    {"channel": "Parcel insert", "role": "The piece's own story, so the buyer tells someone.",
     "cadence": "Every parcel", "first_move": "Print the weave card.",
     "hands_off_to": "nothing, this is the last step"},
  ],
  "six_cs": [
    {"c": "Coherence", "verdict": "met", "note": "Long story by email, the ask in stories."},
    {"c": "Consistency", "verdict": "met", "note": "No discount anywhere in it."},
    {"c": "Continuity", "verdict": "weak",
     "note": "Nothing links it to the last campaign. Reuse the workshop thread."},
    {"c": "Complementary", "verdict": "met", "note": "Each channel feeds the next."},
    {"c": "Communications", "verdict": "met", "note": "Shikargah is explained on first use."},
    {"c": "Compelling", "verdict": "weak",
     "note": "The pull is thin. Name the family who weave it."},
  ],
  "posts": [
    {"channel": "Instagram", "placement": "Feed", "title": "The Shikargah weave",
     "body": "Gold zari across midnight blue.", "hashtags": "#banarasi",
     "cta": "View the piece", "day_offset": 0, "product_id": "P1",
     "art_direction": "Macro of the border."},
    {"channel": "Instagram", "placement": "Reel", "title": "Draping it",
     "body": "Three ways to wear it.", "hashtags": "#saree", "cta": "Shop",
     "day_offset": 3, "product_id": "P1", "art_direction": "Hands at work."},
  ],
  "ad_plan": {"daily_budget": 1000, "measurement": "Watch cost per add-to-cart under 400.",
    "ad_sets": [{"name": "Wedding shoppers — metros", "platforms": "Instagram, Facebook",
      "placements": "Feed, Reels", "audience": "Engaged women", "age": "25-40",
      "interests": "Bridal wear", "geography": "Delhi, Mumbai", "budget_share": "60%",
      "primary_text": "Handwoven in Banaras.", "headline": "Midnight Blue Shikargah",
      "description": "", "cta_button": "Shop now"}]},
}

def run():
    bad = []
    state = {"threads": [], "messages": [], "campaigns": [], "posts": [], "sent": [],
             "images": [], "collections": [], "links": [], "tasks": [],
             "assets": [], "product_collections": []}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1500, "height": 980})

        def handler(route):
            req = route.request
            u, method = req.url, req.method
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/functions/v1/launch-assist" in u:
                state["images"].append(json.loads(req.post_data or "{}"))
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                  {"ok": True, "images": [
                    {"url": "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
                     "path": f"generated/c{i}.png", "bytes": 10, "shot_angle": "front",
                     "check": {"match": True, "confidence": "high", "differences": []}}
                    for i in range(2)], "failed": []}))
            if "/functions/v1/campaign-agent" in u:
                body = json.loads(req.post_data or "{}")
                if body.get("action") == "health":
                    return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                      {"gemini": True, "openai": False, "anthropic": False, "groq": False,
                       "nvidia": True, "brand_set": True, "meta_connected": False,
                       "can_search": {"gemini": True, "nvidia": False},
                       "counts": {"products": 4, "looks": 5, "past": 5}}))
                state["sent"].append(body)
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                  {"ok": True, "model": "gemini", "say": "Three pieces, two weeks, tight targeting.",
                   "ask": None, "ready": True, "proposal": PROPOSAL,
                   "options": [
                     {"name": "The hunting forest", "spine": "Read the shikargah as a scene.",
                      "why": "Nobody explains what is woven into it.",
                      "trade_off": "Needs two new close-ups.", "recommended": True},
                     {"name": "Forty-one days", "spine": "One loom, one piece, start to finish.",
                      "why": "Proves the price.",
                      "trade_off": "Needs the weaver to agree to be filmed.",
                      "recommended": False},
                   ]}))
            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            if method == "POST":
                rows = json.loads(req.post_data or "[]")
                rows = rows if isinstance(rows, list) else [rows]
                out = []
                for i, r in enumerate(rows):
                    r = dict(r)
                    r.setdefault(f"{t[:-1]}_id", f"{t}-{len(state.get(t, []))+i}")
                    if t == "campaign_threads": r["thread_id"] = "T1"; state["threads"].append(r)
                    if t == "campaign_messages": r["message_id"] = f"M{len(state['messages'])}"; state["messages"].append(r)
                    if t == "campaigns": r["campaign_id"] = "C1"; state["campaigns"].append(r)
                    if t == "campaign_posts": r["post_id"] = f"PO{len(state['posts'])}"; state["posts"].append(r)
                    if t == "collections": r["collection_id"] = "CO1"; r["slug"] = r.get("slug"); state["collections"].append(r)
                    if t == "product_collections": state["product_collections"].append(r)
                    if t == "links": state["links"].append(r)
                    if t == "tasks": state["tasks"].append(r)
                    if t == "campaign_assets": state["assets"].append(r)
                    out.append(r)
                return route.fulfill(status=201, content_type="application/json", body=json.dumps(out))
            if method == "PATCH":
                patch = json.loads(req.post_data or "{}")
                for r in state["threads"]: r.update(patch)
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(state["threads"]))
            if t == "product_images":
                return route.fulfill(status=200, content_type="application/json",
                  headers={"content-range": "0-0/0"}, body=json.dumps(
                    [{"public_url": "https://x.test/a.jpg", "part": "Overall", "generated": False}]))
            rows = {"campaign_threads": state["threads"], "campaign_messages": state["messages"],
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
        pg.goto(BASE + "/studio/", wait_until="networkidle", timeout=25000)
        pg.wait_for_timeout(900)

        # 1. both modes are offered, and the quick one is on by default
        txt = pg.inner_text("body")
        for label in ("Quick draft", "Take the brief", "Check what is on"):
            if label not in txt:
                bad.append(f"the studio does not offer {label!r}")

        # 2. saying something starts a thread and gets a draft back
        if "Which market is this for" not in txt:
            bad.append("the studio does not ask which market the campaign is for")
        pg.fill("input[placeholder*='South India']", "South India")
        pg.fill("textarea", "Push the blue pieces before wedding season, 15000, two weeks.")
        pg.get_by_role("button", name="Send").click()
        pg.wait_for_timeout(2500)
        sent = state["sent"][0] if state["sent"] else {}
        if sent.get("mode") != "Quick":
            bad.append(f"the first turn went out in mode {sent.get('mode')}")
        if sent.get("search") is not True:
            bad.append("the first turn did not ask it to check what is on")
        if not sent.get("messages"):
            bad.append("the conversation was not sent to the agent")
        if sent.get("market") != "South India":
            bad.append(f"the market did not reach the agent: {sent.get('market')!r}")
        threads = [r for r in state.get("threads", []) if isinstance(r, dict)]
        if threads and not any(r.get("market") == "South India" for r in threads):
            bad.append("the market was not written onto the thread")

        after = pg.inner_text("body")
        if "Winter Wedding" not in after:
            bad.append("the draft campaign is not shown")
        if "Directions it considered" not in after:
            bad.append("the directions it considered are not shown")
        for want in ("The hunting forest", "Forty-one days", "Its pick", "Costs:"):
            if want not in after:
                bad.append(f"the options panel does not show {want!r}")
        switch = pg.get_by_role("button", name="Build this one instead")
        if switch.count() != 1:
            bad.append(f"{switch.count()} switch buttons, expected one (only the unpicked option)")
        else:
            state["sent"].clear()
            switch.click()
            pg.wait_for_timeout(1500)
            asked = " ".join(str(c.get("messages", "")) for c in state["sent"])
            if "Forty-one days" not in asked:
                bad.append("switching direction did not tell the agent which one")
            if "Keep everything else" not in asked:
                bad.append("switching direction did not ask it to keep the approved work")
        if "Wedding shoppers — metros" not in after:
            bad.append("the ad sets are not shown")

        # 2b. the spine, the occasion, the channel plan and the agent's own check.
        # These are the omni-channel half: a campaign is one idea carried across
        # places, each with a job, and held to the six C's.
        if PROPOSAL["spine"] not in after:
            bad.append("the campaign's spine is not shown")
        if PROPOSAL["occasion"]["name"] not in after:
            bad.append("the occasion the campaign is built on is not shown")

        plan = pg.query_selector("[data-channel-plan]")
        if not plan:
            bad.append("the per-channel plan is not shown at all")
        else:
            said = plan.inner_text()
            for ch in PROPOSAL["channel_plan"]:
                if ch["channel"] not in said:
                    bad.append(f"the channel plan does not name {ch['channel']!r}")
                if ch["role"] not in said:
                    bad.append(f"{ch['channel']} is shown with no job")
                if ch["first_move"] not in said:
                    bad.append(f"{ch['channel']} is shown with nothing to do first")
            if "Hands off to" not in said:
                bad.append("the channel plan does not say where someone goes next")

        # A literal \uXXXX must never reach the screen. It is a valid escape
        # inside a JS string and NOT inside JSX text, and the two are
        # indistinguishable in the source -- this page shipped "the six
        # C\u2019s" for exactly that reason. Checked here because most of this
        # text only renders once there is a proposal.
        if "\\u" in after:
            at = after.index("\\u")
            bad.append("a raw unicode escape is on screen: ..."
                       + after[max(0, at - 40):at + 20].replace("\n", " ") + "...")

        cs = pg.query_selector("[data-six-cs]")
        if not cs:
            bad.append("the six C's check is not shown")
        else:
            said = cs.inner_text()
            for x in PROPOSAL["six_cs"]:
                if x["c"] not in said:
                    bad.append(f"the six C's check is missing {x['c']!r}")
            # a weak one must show its reason, not just an amber chip
            for x in PROPOSAL["six_cs"]:
                if x["verdict"] == "weak" and x["note"] not in said:
                    bad.append(f"{x['c']} is marked weak but does not say why")
            # and the colours must follow the verdicts
            amber = pg.eval_on_selector_all("[data-six-cs] .badge.b-amber",
                                            "e => e.map(x => x.textContent.trim())")
            weak = sorted(x["c"] for x in PROPOSAL["six_cs"] if x["verdict"] == "weak")
            if sorted(amber) != weak:
                bad.append(f"amber chips are {sorted(amber)}, the weak ones are {weak}")

        # 3. the paid half says plainly that it is not live
        if "Nothing here is live" not in after:
            bad.append("the Meta plan does not say it is a draft")
        if "Draft only" not in after:
            bad.append("the Meta card is not marked draft only")

        # 4. nothing reached the calendar before approval
        if state["campaigns"] or state["posts"]:
            bad.append("a campaign was written before anyone approved it")

        # 5. approving writes the campaign and its posts, once
        pg.get_by_role("button", name=re.compile("Approve and build")).click()
        pg.wait_for_timeout(6000)
        if len(state["campaigns"]) != 1:
            bad.append(f"approval wrote {len(state['campaigns'])} campaigns, expected 1")
        if len(state["posts"]) != 2:
            bad.append(f"approval wrote {len(state['posts'])} posts, expected 2")
        else:
            days = sorted(p["scheduled_for"] for p in state["posts"])
            if days != ["2026-11-25", "2026-11-28"]:
                bad.append(f"posts landed on {days}, expected the start day and three days on")
        # the rest of the build: collection, links, tasks, creatives
        if len(state["collections"]) != 1:
            bad.append(f"{len(state['collections'])} collections made, expected 1")
        if len(state["product_collections"]) != 1:
            bad.append(f"{len(state['product_collections'])} pieces put in it, expected 1")
        if len(state["links"]) != 2:
            bad.append(f"{len(state['links'])} tracked links, expected one organic and one per ad set")
        if len(state["tasks"]) != 3:
            bad.append(f"{len(state['tasks'])} tasks raised, expected 3")
        if len(state["images"]) != 2:
            bad.append(f"{len(state['images'])} image runs, expected one per post naming a piece")
        else:
            counts = {c.get("count") for c in state["images"]}
            if counts != {2}:
                bad.append(f"image runs asked for {counts}, expected 2 each")
        if len(state["assets"]) != 4:
            bad.append(f"{len(state['assets'])} creatives stored, expected 4")
        after_run = pg.inner_text("body")
        if "Nothing was sent to Meta" not in after_run:
            bad.append("the build does not say it stopped at Meta")

        c = state["campaigns"][0] if state["campaigns"] else {}
        if c.get("status") != "Draft":
            bad.append(f"the campaign was saved as {c.get('status')}, expected Draft")
        if not c.get("ad_plan"):
            bad.append("the ad plan was not saved with the campaign")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run()
print(f"=== campaign studio: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)

# A check that reports a problem and exits 0 cannot fail anything: a runner, a
# hook or CI all read the exit code, not the words. Eleven of these suites were
# written that way and `qa/run.sh` said "all clear" over a red one.
sys.exit(1 if probs else 0)
