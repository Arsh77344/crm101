# The launch wizard, clicked the way the owner uses it: drop in photos named the
# way a supplier names them, check the part each one was read as, then ask for a
# number of every style in one go.
import json, os, re, sys, base64
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}
SETTINGS = [{"setting_key": k, "setting_value": v} for k, v in
            [("brand_name", "Test Brand"), ("brand_sells", "sarees")]]
PROFILES = [{"id": USER["id"], "email": USER["email"], "full_name": "Test Owner", "role": "owner"}]

# A 2x2 JPEG, so the browser-side downscale has something real to decode.
JPEG = base64.b64decode(
  "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0a"
  "HBwcJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPDI0NP/bAEMBCQkJDAsMGA0NGDIhHCEyMjIyMjIy"
  "MjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEB"
  "AxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9"
  "AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6"
  "Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ip"
  "qrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/9oADAMBAAIR"
  "AxEAPwD3+iiigD//2Q==")

NAMES = [
  "Usaya-Cool Blue Open Zigzag Border With Mina Leaf Buti-pallu.jpg",
  "Usaya-Cool Blue Open Zigzag Border With Mina Leaf Buti-border body.jpg",
  "Usaya-Cool Blue Open Zigzag Border With Mina Leaf Buti-closeup.jpg",
]

LOOKS = [{"look_id": "aaaaaaaa-1111-2222-3333-444444444444", "look_no": 7,
          "name": "Ghat at dawn", "source": "Found", "use_for": "Editorial", "status": "Ready",
          "reference_url": "https://x.test/ref.jpg",
          "summary": "Teal silk saree on sandstone steps at first light, boats behind."}]
LOOK_USAGE = [{"look_id": "aaaaaaaa-1111-2222-3333-444444444444", "products_used_on": 0,
               "images_made": 0, "products": []}]

def run():
    bad = []
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1340, "height": 1000})
        sent = {"image_calls": []}

        def handler(route):
            url, req = route.request.url, route.request
            if "/auth/v1/user" in url:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(USER))
            if "/auth/v1/token" in url:
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(SESSION))
            if "/storage/v1/object/" in url:
                m = re.search(r"/object/(?:public/)?product-images/(.+)$", url)
                key = m.group(1) if m else "x.jpg"
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"Key": f"product-images/{key}", "path": key}))
            if "/functions/v1/launch-assist" in url:
                try: body = json.loads(req.post_data or "{}")
                except Exception: body = {}
                if body.get("action") == "images":
                    sent["image_calls"].append(body)
                    n = int(body.get("count") or 1)
                    return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                      {"ok": True, "images": [
                        {"url": "data:image/gif;base64,R0lGODlhAQABAAAAACw=",
                         "path": f"generated/{body.get('mode')}-{i}.png", "bytes": 10,
                         "mode": body.get("mode"), "shot_angle": f"angle {i}",
                         "set_id": body.get("set_id"), "look_id": body.get("look_id"),
                         # The Model frame's first image is the one the stub
                         # rejects, so it stands for a frame that was re-shot.
                         "attempts": 2 if (body.get("mode") == "Model" and i == 1) else 1,
                         "look_name": "Ghat at dusk" if body.get("mode") == "Editorial" else None,
                         "check": {"match": body.get("mode") != "Model" or i != 0,
                                   "confidence": "high",
                                   "differences": [] if (body.get("mode") != "Model" or i != 0)
                                                  else ["The border is wider than the photographs show."]}}
                        for i in range(n)],
                       "failed": [],
                       "anchor_url": f"https://x.test/anchor-{body.get('mode')}.png"}))
                if body.get("action") in ("copy", "price"):
                    sent.setdefault(body["action"], []).append(body)
                    return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                      {"ok": True, "result": {"title": "T", "description": "D" * 40,
                       "highlights": ["a"], "tags": ["b"], "observed": {}, "uncertain": [],
                       "suggested": 3000, "low": 2000, "high": 4000, "comparables": []}}))
                return route.fulfill(status=200, content_type="application/json", body=json.dumps(
                  {"openai": False, "gemini": True, "anthropic": False, "groq": False,
                   "nvidia": False, "brand_set": True, "images_ready": True,
                   "sets": [{"id": "stone", "name": "Warm stone", "line": "a wall"},
                            {"id": "linen", "name": "Oat linen", "line": "a backdrop"}]}))
            table = (re.search(r"/rest/v1/([a-z_]+)", url) or [None, ""])[1]
            rows = {"profiles": PROFILES, "settings": SETTINGS,
                    "looks": LOOKS, "look_usage": LOOK_USAGE}.get(table, [])
            return route.fulfill(status=200, content_type="application/json",
                                 headers={"content-range": "0-0/0"}, body=json.dumps(rows))

        ctx.route("**stub.supabase.co/**", handler)
        pg = ctx.new_page()
        pg.add_init_script("localStorage.setItem('sb-stub-auth-token', JSON.stringify(%s));"
                           % json.dumps(SESSION))
        errs = []
        pg.on("pageerror", lambda e: errs.append(f"PAGEERROR {e}"))
        pg.goto(BASE + "/launch/", wait_until="networkidle", timeout=20000)

        files = [{"name": n, "mimeType": "image/jpeg", "buffer": JPEG} for n in NAMES]
        pg.set_input_files("input[type=file]", files)
        try:
            pg.wait_for_selector("select", timeout=15000)
        except Exception:
            bad.append("no part dropdown appeared after uploading three photos")
        pg.wait_for_timeout(1200)

        # 1. each photo read as a part, from its file name
        # Only the part dropdowns: the page also carries a provider picker, so pick
        # the selects whose options are the part list.
        got = pg.eval_on_selector_all("select", """els => els
            .filter(e => [...e.options].some(o => o.value === 'Pallu'))
            .map(e => e.value)""")
        want = ["Pallu", "Border + Body", "Close-up"]
        if got != want:
            bad.append(f"parts read as {got}, expected {want}")

        # 2. the warning that no photo shows the whole piece
        page_text = pg.inner_text("body")
        if "overall" not in page_text.lower():
            bad.append("no warning that the set has no overall shot")

        # continue to the piece, then to imagery
        pg.get_by_role("button", name="Continue").click()
        pg.wait_for_timeout(400)
        pg.fill("input[name=public_product_name]", "Cool Blue Zigzag Border Saree") \
            if pg.query_selector("input[name=public_product_name]") \
            else pg.fill("input", "Cool Blue Zigzag Border Saree")
        pg.get_by_role("button", name="Continue").click()
        pg.wait_for_timeout(500)

        # the brief and the shot tweak can both be spoken
        if not pg.query_selector(".dictate"):
            bad.append("no microphone on the imagery step")

        txt = pg.inner_text("body")
        for style in ("AI model", "Editorial", "Studio still", "mannequin", "Fabric laid out"):
            if style.lower() not in txt.lower():
                bad.append(f"imagery step does not offer {style!r}")

        # 3. a count per style, and one Generate for the lot
        # Keyed by the shot each dropdown belongs to, not by where it sits, so
        # adding a style does not silently shift what this test is setting.
        SHOTS = ["Clean", "Fabric", "Mannequin", "Model", "Detail", "Editorial"]
        counts = {}
        for k in SHOTS:
            el = pg.query_selector(f'select[data-shot="{k}"]')
            if el is None:
                bad.append(f"no count dropdown for the {k!r} shot")
            else:
                counts[k] = el
        stray = len(pg.query_selector_all("select[data-shot]")) - len(SHOTS)
        if stray > 0:
            bad.append(f"{stray} shot dropdown(s) on the step that this test does not know about")
        if len(counts) != len(SHOTS):
            pass
        else:
            # the close-up starts at one without being asked for
            if counts["Detail"].input_value() != "1":
                bad.append(f"the close-up starts at {counts['Detail'].input_value()}, expected 1")
            counts["Clean"].select_option("1")
            counts["Model"].select_option("2")
            counts["Detail"].select_option("0")   # switched off on purpose
            pg.wait_for_timeout(300)
            label = pg.inner_text("body")
            if "Generate all 3 images" not in label:
                bad.append("the Generate button does not offer all 3 at once")
            if "No close-up" not in label:
                bad.append("switching the close-up off is not called out")
            pg.get_by_role("button", name=re.compile("Generate all")).click()
            pg.wait_for_timeout(3000)
            modes = [c.get("mode") for c in sent["image_calls"]]
            # a close-up is added back even though it was set to zero
            if sorted(modes) != ["Clean", "Detail", "Model"]:
                bad.append(f"one Generate press sent {modes}, expected Clean, Detail and Model")
            sets = {c.get("set_id") for c in sent["image_calls"]}
            if len(sets) != 1 or not list(sets)[0]:
                bad.append(f"the run did not share one set: {sets}")
            if not all(c.get("check") for c in sent["image_calls"]):
                bad.append("the images were not sent for checking")
            # the stills are styled on the set by default, not cut out on white
            if any(c.get("cutout_on_white") for c in sent["image_calls"]):
                bad.append("the studio stills defaulted to a white cut-out")
            props = {c.get("prop_from") for c in sent["image_calls"]}
            if len(props) != 1 or list(props)[0] is None:
                bad.append(f"the run did not share one prop rotation: {props}")
            for c in sent["image_calls"]:
                if c.get("parts") != want:
                    bad.append(f"{c.get('mode')} call sent parts {c.get('parts')}, expected {want}")
                if len(c.get("images") or []) != 3:
                    bad.append(f"{c.get('mode')} call sent {len(c.get('images') or [])} photos, expected 3")
            if [c.get("count") for c in sent["image_calls"] if c.get("mode") == "Model"] != [2]:
                bad.append("the model-shot call did not ask for 2")
            if [c.get("count") for c in sent["image_calls"] if c.get("mode") == "Detail"] != [1]:
                bad.append("the close-up call did not ask for exactly 1")

        # 3b. the whole run can borrow the editorial look's background, so the
        #     studio frames and the editorial ones come out of one place.
        if len(counts) == len(SHOTS):
            sent["image_calls"].clear()
            # the look picker only appears once an editorial frame is asked for
            counts["Editorial"].select_option("1")
            pg.wait_for_timeout(400)
            picker = pg.query_selector_all('select[data-pick="look"]')
            if not picker:
                bad.append("no look picker appeared once an editorial frame was asked for")
            else:
                vals = [o.get_attribute("value") for o in picker[0].query_selector_all("option")
                        if (o.get_attribute("value") or "")]
                picker[0].select_option(vals[0])
                pg.wait_for_timeout(300)
                setsel = pg.query_selector_all('select[data-pick="set"]')
                if not setsel:
                    bad.append("the set picker offers no way to match the look")
                else:
                    opt = [o for o in setsel[0].query_selector_all("option")
                           if o.get_attribute("value") == "look"][0]
                    if opt.get_attribute("disabled") is not None:
                        bad.append("matching the look is still disabled after a look was chosen")
                    setsel[0].select_option("look")
                    pg.wait_for_timeout(300)
                    counts["Fabric"].select_option("1")
                    pg.wait_for_timeout(300)
                    pg.get_by_role("button", name=re.compile("Generate all")).click()
                    pg.wait_for_timeout(3000)
                    calls = sent["image_calls"]
                    fab = [c for c in calls if c.get("mode") == "Fabric"]
                    if not fab:
                        bad.append("no fabric frame was asked for")
                    else:
                        if fab[0].get("set_id") != "look":
                            bad.append(f"the fabric frame did not borrow the look: "
                                       f"set_id={fab[0].get('set_id')}")
                        if not fab[0].get("look_id"):
                            bad.append("the fabric frame was sent no look to take its set from")
                    if calls and calls[0].get("mode") != "Editorial":
                        bad.append(f"the run did not start with the editorial frame: "
                                   f"{[c.get('mode') for c in calls]}")
                    if calls and calls[0].get("anchor_url"):
                        bad.append("the first frame was given an anchor, but nothing existed yet")
                    later = calls[1:]
                    unanchored = [c.get("mode") for c in later if not c.get("anchor_url")]
                    if unanchored:
                        bad.append(f"these frames were not anchored to the scene: {unanchored}")
                    anchors = {c.get("anchor_url") for c in later}
                    if len(anchors) > 1:
                        bad.append(f"the run hung off more than one frame: {anchors}")
                    elif anchors and list(anchors)[0] != "https://x.test/anchor-Editorial.png":
                        bad.append(f"the run anchored to {list(anchors)[0]}, "
                                   f"expected the editorial frame")
                    ed = [c for c in calls if c.get("mode") == "Editorial"]
                    if ed and not ed[0].get("look_id"):
                        bad.append("the editorial frame lost its look")
                    ids = {c.get("look_id") for c in calls if c.get("mode") != "Editorial"}
                    if len(ids) > 1:
                        bad.append(f"the run's frames did not share one look: {ids}")

        # 4. an image that does not match the photos is called out
        flagged = pg.query_selector_all(".shot-flag")
        if not flagged:
            bad.append("an image the check rejected is not marked on the thumbnail")
        body_now = pg.inner_text("body")
        if "do not match your photographs" not in body_now:
            bad.append("no warning that some images do not match the photographs")
        elif "border is wider" not in body_now:
            bad.append("the warning does not say what differed")

        # 4a. a frame that had to be re-shot says so, and the run says how many.
        # This is what the owner is paying for when a frame is rejected, so it is
        # not allowed to happen silently.
        body_before = pg.inner_text("body")
        tries = pg.query_selector_all(".shot .badge.b-amber")
        if not tries:
            bad.append("a frame that took more than one attempt does not say so")
        elif "2 tries" not in " ".join(t.inner_text() for t in tries):
            bad.append(f"the attempt count is not shown: "
                       f"{[t.inner_text() for t in tries]}")
        if "needed re-shooting" not in body_before:
            bad.append("the run does not say how many frames had to be re-shot")
        if "never stored" not in body_before:
            bad.append("the run does not say the rejected attempts were not kept")

        # 4b. one frame redone with a short note. Everything that made the frame
        # what it is has to come back unchanged -- the style, the camera, the set,
        # the look and the scene -- or the "redo" is really a different shot.
        sent["image_calls"].clear()
        redo_btns = pg.query_selector_all('.shot button[title*="Redo"]')
        kept_before = len(pg.query_selector_all(".shot"))
        if len(redo_btns) != kept_before:
            bad.append(f"{len(redo_btns)} redo buttons across {kept_before} frames; "
                       f"every generated frame should offer one")
        if not redo_btns:
            bad.append("no way to redo a single frame")
        else:
            # Which frame we are redoing, read off the page before pressing.
            first = pg.query_selector(".shot")
            redo_btns[0].click()
            pg.wait_for_timeout(300)
            panel = pg.query_selector("[data-redo]")
            if not panel:
                bad.append("pressing redo opens nothing")
            else:
                said = panel.inner_text()
                if "What should change" not in said:
                    bad.append(f"the redo panel does not ask what to change: {said[:80]}")
                if "angle" not in said:
                    bad.append("the redo panel does not say which frame it is redoing")
                # Nothing to send until something is typed.
                go = panel.query_selector("button.btn-primary")
                if not go.is_disabled():
                    bad.append("the redo button is live with an empty prompt")
                pg.fill("[data-redo] textarea", "Warmer light, and lose the flowers.")
                pg.wait_for_timeout(150)
                if go.is_disabled():
                    bad.append("the redo button stays dead after a prompt is typed")
                go.click()
                pg.wait_for_timeout(1800)

                calls = sent["image_calls"]
                if len(calls) != 1:
                    bad.append(f"redoing one frame made {len(calls)} calls, expected 1")
                else:
                    c = calls[0]
                    if c.get("count") != 1:
                        bad.append(f"the redo asked for {c.get('count')} images, expected 1")
                    if c.get("angles") != ["angle 0"]:
                        bad.append(f"the redo sent angles {c.get('angles')}, expected the "
                                   f"frame's own angle so the camera does not move")
                    if not c.get("anchor_url"):
                        bad.append("the redo sent no anchor, so the scene can change under him")
                    tweak = str(c.get("tweak") or "")
                    if "lose the flowers" not in tweak.lower():
                        bad.append(f"the redo did not carry what was typed: {tweak!r}")
                    if not c.get("mode"):
                        bad.append("the redo did not say which style of frame it is")
                    if len(c.get("images") or []) != 3:
                        bad.append("the redo did not send the owner's own photographs")

                # The frame redone is set aside, not deleted, and the new one kept.
                pg.wait_for_timeout(200)
                keeps = pg.eval_on_selector_all(
                    ".shot button[style*='left']", "e => e.map(x => x.textContent.trim())")
                if keeps.count("+") < 1:
                    bad.append("the frame that was redone is still marked kept; "
                               "it should be set aside so the two can be compared")
                if len(pg.query_selector_all(".shot")) <= kept_before:
                    bad.append("the redone frame replaced the old one instead of "
                               "arriving beside it")
                if pg.query_selector("[data-redo]"):
                    bad.append("the redo panel stayed open after it ran")

        # 5. the copy call is told the parts too
        for c in sent.get("copy", []):
            if c.get("parts") != want:
                bad.append(f"copy call sent parts {c.get('parts')}")
        if not sent.get("copy"):
            bad.append("no copy call was made when continuing past the photos")

        bad.extend(e[:140] for e in errs if "favicon" not in e.lower())
        b.close()
    return bad

probs = run()
print(f"=== launch wizard: {len(probs)} problem(s) ===")
for p in probs: print("  " + p)
