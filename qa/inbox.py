# The customer inbox: what the agent answered on its own, and what it handed over.
#
# The assertion this file exists for is the honesty one. No number is attached
# yet, so nothing has actually been sent -- and a page that shows a drafted
# reply looking like a sent one would have the owner believe a customer was
# answered when nobody was. Everything else here is about whether he can see
# why a conversation reached him.
import json, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from playwright.sync_api import sync_playwright

BASE = os.environ.get("QA_BASE", "http://127.0.0.1:9804/crm101")
USER = {"id": "11111111-1111-1111-1111-111111111111", "email": "owner@test.local",
        "aud": "authenticated", "role": "authenticated", "app_metadata": {}, "user_metadata": {}}
SESSION = {"access_token": "fake", "token_type": "bearer", "expires_in": 3600,
           "expires_at": 9999999999, "refresh_token": "fake", "user": USER}

# One waiting on him, one the agent handled, one whose window has shut.
CONVOS = [
  {"conversation_id": "C-ESC", "channel": "WhatsApp", "wa_phone": "919812345678",
   "wa_name": "Meera R", "contact_id": None, "status": "Needs you",
   "topic": "Asking for a discount", "escalated": True,
   "escalation_rule": "Price negotiation or discount",
   "escalation_note": 'Matched "discount" in your Price negotiation or discount rule.',
   "escalated_at": "2026-11-27T10:00:00Z", "last_in_at": "2026-11-27T10:00:00Z",
   "last_out_at": None, "unanswered": 1, "is_test": False,
   "created_at": "2026-11-27T09:00:00Z", "updated_at": "2026-11-27T10:00:00Z",
   "window_until": "2026-11-28T10:00:00Z", "window_open": True,
   "window_minutes_left": 300, "message_count": 1,
   "last_message": "Can you give me a discount on the blue one?", "last_direction": "in"},
  {"conversation_id": "C-OK", "channel": "WhatsApp", "wa_phone": "919900000002",
   "wa_name": "Anand", "contact_id": None, "status": "Waiting on customer",
   "topic": "Asking what the motif means", "escalated": False,
   "escalation_rule": None, "escalation_note": None, "escalated_at": None,
   "last_in_at": "2026-11-27T08:00:00Z", "last_out_at": "2026-11-27T08:01:00Z",
   "unanswered": 0, "is_test": False, "created_at": "2026-11-27T08:00:00Z",
   "updated_at": "2026-11-27T08:01:00Z", "window_until": "2026-11-28T08:00:00Z",
   "window_open": True, "window_minutes_left": 45, "message_count": 2,
   "last_message": "A hunting forest, woven in silk.", "last_direction": "out"},
  {"conversation_id": "C-SHUT", "channel": "WhatsApp", "wa_phone": "919900000003",
   "wa_name": None, "contact_id": None, "status": "Needs you",
   "topic": None, "escalated": True, "escalation_rule": "Window closed",
   "escalation_note": "Their last message is more than 24 hours old, so a free reply is not "
                      "allowed. It needs an approved template.",
   "escalated_at": "2026-11-25T10:00:00Z", "last_in_at": "2026-11-25T09:00:00Z",
   "last_out_at": None, "unanswered": 1, "is_test": False,
   "created_at": "2026-11-25T09:00:00Z", "updated_at": "2026-11-25T10:00:00Z",
   "window_until": "2026-11-26T09:00:00Z", "window_open": False,
   "window_minutes_left": 0, "message_count": 1,
   "last_message": "Hello", "last_direction": "in"},
]

MESSAGES = {
  "C-ESC": [
    {"message_id": "M1", "conversation_id": "C-ESC", "direction": "in",
     "body": "Can you give me a discount on the blue one?", "wa_message_id": "w1",
     "status": "Received", "held_reason": None, "written_by": None, "grounded_on": {},
     "rule_hit": "Price negotiation or discount", "sent_at": None,
     "created_at": "2026-11-27T10:00:00Z"},
  ],
  "C-OK": [
    {"message_id": "M2", "conversation_id": "C-OK", "direction": "in",
     "body": "What does the motif on this one mean?", "wa_message_id": "w2",
     "status": "Received", "held_reason": None, "written_by": None, "grounded_on": {},
     "rule_hit": None, "sent_at": None, "created_at": "2026-11-27T08:00:00Z"},
    # Written by the agent, and NOT sent, because no number is attached.
    {"message_id": "M3", "conversation_id": "C-OK", "direction": "out",
     "body": "A hunting forest, woven in silk. The riders and deer are the shikargah.",
     "wa_message_id": None, "status": "Ready to send",
     "held_reason": "No WhatsApp number is connected yet, so this was written but not sent.",
     "written_by": "gpt-4o-mini", "grounded_on": {"product_ids": ["P1"]},
     "rule_hit": None, "sent_at": None, "created_at": "2026-11-27T08:01:00Z"},
    # A draft the rails stopped. It must never read as something a customer saw.
    {"message_id": "M4", "conversation_id": "C-OK", "direction": "out",
     "body": "It will reach you by Friday.", "wa_message_id": None, "status": "Held",
     "held_reason": 'It promised a time ("by Friday"). Only you can commit to a date.',
     "written_by": "gpt-4o-mini", "grounded_on": {}, "rule_hit": None, "sent_at": None,
     "created_at": "2026-11-27T08:02:00Z"},
  ],
  "C-SHUT": [
    {"message_id": "M5", "conversation_id": "C-SHUT", "direction": "in", "body": "Hello",
     "wa_message_id": "w5", "status": "Received", "held_reason": None, "written_by": None,
     "grounded_on": {}, "rule_hit": None, "sent_at": None,
     "created_at": "2026-11-25T09:00:00Z"},
  ],
}

RULES = [
  {"topic_id": "T1", "label": "Complaint or damage", "patterns": ["damag*", "torn"],
   "active": True, "note": "The first reply to an unhappy customer should be the owner's.",
   "sort_order": 10, "created_at": "2026-11-27T00:00:00Z"},
  {"topic_id": "T2", "label": "Price negotiation or discount",
   "patterns": ["discount*", "kitna"], "active": True,
   "note": "Bargaining is the owner's.", "sort_order": 50,
   "created_at": "2026-11-27T00:00:00Z"},
  {"topic_id": "T3", "label": "Press, collaboration or barter", "patterns": ["collaborat*"],
   "active": False, "note": "Brand decisions.", "sort_order": 80,
   "created_at": "2026-11-27T00:00:00Z"},
]


def run(transport="none", health_fails=False):
    bad = []
    state = {"sent": [], "writes": [], "patched": []}
    with sync_playwright() as pw:
        b = pw.chromium.launch()
        ctx = b.new_context(viewport={"width": 1340, "height": 1100})

        def handler(route):
            req = route.request
            u = req.url
            if "/auth/v1/user" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(USER))
            if "/auth/v1/token" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps(SESSION))
            if "/functions/v1/whatsapp-agent" in u:
                try: body = json.loads(req.post_data or "{}")
                except Exception: body = {}
                act = body.get("action")
                if act == "health":
                    if health_fails:
                        return route.fulfill(status=500, content_type="application/json",
                                             body=json.dumps({"error": "boom"}))
                    return route.fulfill(status=200, content_type="application/json",
                        body=json.dumps({"openai": True, "gemini": True, "anthropic": True,
                                         "groq": True, "transport": transport,
                                         "brand_set": True, "active_rules": 2}))
                state["sent"].append(body)
                if act == "test":
                    # What the function really returns for a message the rules catch.
                    return route.fulfill(status=200, content_type="application/json",
                        body=json.dumps({"ok": True, "conversation_id": "C-ESC",
                                         "is_test": True, "transport": transport,
                                         "escalated": True,
                                         "rule": "Price negotiation or discount",
                                         "matched": "discount*", "drafted": False}))
                return route.fulfill(status=200, content_type="application/json",
                    body=json.dumps({"ok": True, "status": "Ready to send",
                                     "transport": transport}))
            if "/functions/v1/" in u:
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps({"ok": True}))

            t = (re.search(r"/rest/v1/([a-z_]+)", u) or [None, ""])[1]
            if req.method == "POST":
                try: sent = json.loads(req.post_data or "[]")
                except Exception: sent = []
                state["writes"].append({"table": t, "rows": sent})
                return route.fulfill(status=201, content_type="application/json",
                                     body=json.dumps(sent if isinstance(sent, list) else [sent]))
            if req.method == "PATCH":
                try: sent = json.loads(req.post_data or "{}")
                except Exception: sent = {}
                state["patched"].append({"table": t, "url": u, "row": sent})
                return route.fulfill(status=200, content_type="application/json",
                                     body=json.dumps([sent]))
            if t == "conversation_messages":
                which = (re.search(r"conversation_id=eq\.([A-Za-z0-9-]+)", u) or [None, ""])[1]
                return route.fulfill(status=200, content_type="application/json",
                    headers={"content-range": "0-0/0"},
                    body=json.dumps(MESSAGES.get(which, [])))
            data = {
                "conversation_state": CONVOS, "escalation_topics": RULES,
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
        pg.goto(BASE + "/inbox/", wait_until="networkidle", timeout=20000)
        pg.wait_for_timeout(800)

        # 1. nothing is written, and nothing is sent, just by opening the page
        if state["writes"]:
            bad.append(f"opening the page wrote to {state['writes'][0]['table']}")
        if [s for s in state["sent"] if s.get("action") != "health"]:
            bad.append("opening the page asked the agent to do something")

        body = pg.inner_text("body")

        # 2. the honesty line, and nothing claiming a customer was answered
        note = pg.query_selector("[data-transport]")
        if transport == "none":
            if not note:
                bad.append("no number is attached and the page does not say so")
            elif "has actually been sent" not in note.inner_text():
                bad.append("the no-number note does not say nothing was sent")
        elif note:
            bad.append("a number is attached and the page still says none is")

        # 3. every conversation is listed, the waiting one first
        for c in CONVOS:
            name = c["wa_name"] or c["wa_phone"]
            if name not in body:
                bad.append(f"the conversation with {name!r} is not listed")
        rows = [r.inner_text() for r in pg.query_selector_all(".thread-row")]
        if len(rows) != len(CONVOS):
            bad.append(f"{len(rows)} rows in the list, expected {len(CONVOS)}")
        elif "Meera R" not in rows[0]:
            bad.append("the list does not put a conversation waiting on him first")

        # A status has to carry the right tone, not just the right words. Asserting
        # the text alone let a green "Needs you" through once -- green is this
        # project's done tone, and reading a not-yet-done state as done is the one
        # misunderstanding this page cannot afford.
        want_tone = {"Needs you": "b-amber", "Waiting on customer": "b-blue"}
        for c in CONVOS:
            name = c["wa_name"] or c["wa_phone"]
            row = pg.query_selector(f".thread-row:has-text({name!r})")
            if not row:
                continue
            badge = row.query_selector(".badge")
            if not badge:
                bad.append(f"{name}'s status is not a badge")
                continue
            cls = badge.get_attribute("class") or ""
            if badge.inner_text().strip() != c["status"]:
                bad.append(f"{name} shows {badge.inner_text().strip()!r}, "
                           f"expected {c['status']!r}")
            tone = want_tone.get(c["status"], "")
            if tone and tone not in cls:
                bad.append(f"{name} is {c['status']!r} but its badge is {cls!r}, "
                           f"expected {tone}")
            if "b-green" in cls:
                bad.append(f"{name} is {c['status']!r} and shows the done tone")

        # 4. the filter actually filters
        pg.check("input[type=checkbox]")
        pg.wait_for_timeout(250)
        after = [r.inner_text() for r in pg.query_selector_all(".thread-row")]
        if len(after) != 2:
            bad.append(f"the waiting-on-you filter left {len(after)} rows, expected 2")
        if any("Anand" in r for r in after):
            bad.append("the filter kept a conversation the agent had handled")
        pg.uncheck("input[type=checkbox]")
        pg.wait_for_timeout(250)

        # 5. the escalated conversation says which rule fired and why
        pg.click(".thread-row:has-text('Meera R')")
        pg.wait_for_timeout(500)
        esc = pg.query_selector("[data-escalated]")
        if not esc:
            bad.append("an escalated conversation does not say why it reached him")
        else:
            e = esc.inner_text()
            if "Price negotiation" not in e:
                bad.append("the rule that escalated it is not named")
            if "discount" not in e:
                bad.append("the word that matched is not shown")
        win = pg.query_selector("[data-window]")
        if not win or "left to reply" not in win.inner_text():
            bad.append("the open window is not shown on an escalated conversation")

        # 6. the owner's own reply reaches the agent as his, not as a draft
        pg.fill("textarea", "No discount, but I can show you two at that price.")
        pg.click("button.btn-primary:has-text('Reply')")
        pg.wait_for_timeout(900)
        mine = [s for s in state["sent"] if s.get("action") == "answer"]
        if not mine:
            bad.append("pressing Reply sent nothing to the agent")
        else:
            if "No discount" not in str(mine[0].get("body") or ""):
                bad.append("his reply did not reach the agent")
            if mine[0].get("conversation_id") != "C-ESC":
                bad.append(f"his reply went to {mine[0].get('conversation_id')!r}")

        # 7. a drafted reply must never read as a sent one
        pg.click(".thread-row:has-text('Anand')")
        pg.wait_for_timeout(600)
        thread = pg.inner_text("body")
        if "Ready to send" not in thread:
            bad.append("a written-but-not-sent reply does not show that status")
        if "hunting forest" not in thread:
            bad.append("the agent's own reply is not shown")
        if "woven in silk" in thread and "Sent" in thread.replace("Ready to send", ""):
            bad.append("a reply that was never sent is shown as Sent")

        # 8. the draft the rails stopped, with the reason, and not as a reply sent
        if "by Friday" not in thread:
            bad.append("a draft the rails stopped is hidden rather than shown")
        if "Only you can commit to a date" not in thread:
            bad.append("the reason a draft was stopped is not shown")
        if "Held" not in thread:
            bad.append("a stopped draft is not marked as held")

        # 9. our side and their side are told apart
        ours = pg.query_selector_all(".chat.owner")
        theirs = [c for c in pg.query_selector_all(".chat")
                  if "owner" not in (c.get_attribute("class") or "")]
        if len(ours) != 2:
            bad.append(f"{len(ours)} of our messages are marked as ours, expected 2")
        if len(theirs) != 1:
            bad.append(f"{len(theirs)} of theirs are marked as theirs, expected 1")

        # 10. a shut window says a template is needed rather than offering a free reply
        pg.click(".thread-row:has-text('919900000003')")
        pg.wait_for_timeout(500)
        win = pg.query_selector("[data-window]")
        if not win or "template" not in win.inner_text().lower():
            bad.append("a closed window does not say a reply needs an approved template")

        # 11. trying a message runs the real path and reports what happened to it
        pg.fill("[data-try] textarea", "whats the best price you can do")
        pg.click("[data-try] button.btn-primary")
        pg.wait_for_timeout(900)
        tried = [s for s in state["sent"] if s.get("action") == "test"]
        if not tried:
            bad.append("Try it sent nothing to the agent")
        else:
            if "best price" not in str(tried[0].get("text") or ""):
                bad.append("the test message did not reach the agent")
            if not str(tried[0].get("from") or ""):
                bad.append("the test message carried no number")
        out = pg.query_selector("[data-outcome]")
        if not out:
            bad.append("trying a message says nothing about what happened to it")
        else:
            o = out.inner_text()
            if "Price negotiation" not in o:
                bad.append("the outcome does not name the rule that caught it")
            if "Needs you" not in o:
                bad.append("the outcome does not say it was handed over")

        # 12. the rules he tunes are listed, and a toggle writes
        rl = pg.query_selector("[data-rules]")
        if not rl:
            bad.append("the escalation rules are not on the page")
        else:
            r = rl.inner_text()
            for x in RULES:
                if x["label"] not in r:
                    bad.append(f"the rule {x['label']!r} is not listed")
            if "never states a price" not in r:
                bad.append("the page does not say the rails hold whatever the rules say")
        boxes = pg.query_selector_all("[data-rules] input[type=checkbox]")
        if len(boxes) != len(RULES):
            bad.append(f"{len(boxes)} rule toggles, expected {len(RULES)}")
        elif boxes:
            boxes[0].click()
            pg.wait_for_timeout(600)
            tog = [p for p in state["patched"] if p["table"] == "escalation_topics"]
            if not tog:
                bad.append("turning a rule off wrote nothing")
            elif tog[0]["row"].get("active") is not False:
                bad.append(f"turning a rule off wrote {tog[0]['row']!r}")

        bad.extend(errs)
        b.close()
    return bad


problems = run("none")
# With a number attached the honesty note must disappear, and nothing else change.
problems += [f"(with a number attached) {p}" for p in run("connected")]
# And if the health call itself fails, the note must still be there. It used to be
# swallowed, which left the inbox looking live while nothing was being sent --
# the worst way for this page to be wrong.
problems += [f"(health call failing) {p}" for p in run("none", health_fails=True)]

print("=== inbox: %d problem(s)" % len(problems))
for p in problems:
    print(p)
sys.exit(1 if problems else 0)
