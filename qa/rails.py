#!/usr/bin/env python3
"""Who answers, and what may be said.

Two decisions in whatsapp-agent are not allowed to be wrong, and neither can be
checked by looking at the screen:

  ruleHit    -- whether a customer message goes to the owner instead of the
                agent. Too eager and the owner answers everything by hand; too
                slack and a customer gets told something untrue.
  railBreak  -- whether a finished draft may actually be sent. This is the net
                under the prompt: a model told never to invent a price will
                still occasionally invent one.

Both are pure functions, so this suite does not need a browser. It does not copy
them either -- it slices them out of the real source file and runs those, so the
checks cannot drift away from the code that is deployed.
"""
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "supabase/functions/whatsapp-agent/index.ts")

problems = []


def fail(msg):
    problems.append(msg)


def pure_source():
    """Everything from `digits` to the end of `railBreak`, which is contiguous.

    If the file is reordered this raises rather than silently testing less.
    """
    text = open(SRC, encoding="utf-8").read()
    start = text.index("const digits =")
    end = text.index("async function brandContext")
    chunk = text[start:end]
    for name in ("function incoming", "function ruleHit", "const ORDER_TALK",
                 "const PRICE_BEFORE", "const TIMING", "const PROMISE",
                 "function railBreak"):
        if name not in chunk:
            raise SystemExit(
                "rails.py slices the source between `const digits` and "
                "`async function brandContext`, and %r is no longer in there. "
                "The file was reordered; fix the slice rather than this message."
                % name)
    return chunk


HARNESS = r"""
%s

const out = [];
function t(name, got, want) { out.push({ name, got, want }); }

// --- ruleHit, against the owner's seeded list -------------------------------
const ROWS = %s;
const hit = (s) => { const r = ruleHit(s, ROWS); return r ? r.label : null; };

for (const [text, want] of %s) t(`ruleHit: ${text}`, hit(text), want);

// --- railBreak --------------------------------------------------------------
const PRICES = new Set(["18500", "42000"]);
const rb = (d, note) => railBreak(d, PRICES, note || "");
for (const [draft, shouldBlock, note] of %s) {
  const got = rb(draft, note);
  t(`railBreak: ${draft.slice(0, 54)}`, got ? "blocked" : "allowed",
    shouldBlock ? "blocked" : "allowed");
  if (shouldBlock && !got) out[out.length - 1].why = "nothing stopped it";
  if (!shouldBlock && got) out[out.length - 1].why = got;
}

// --- incoming, both payload shapes -----------------------------------------
const flat = incoming({ from: "+91 98765 43210", name: "A", text: "hello", wa_message_id: "x1" });
t("incoming flat: phone digits only", flat && flat.from, "919876543210");
t("incoming flat: id carried", flat && flat.id, "x1");

const meta = incoming({ entry: [{ changes: [{ value: {
  contacts: [{ profile: { name: "B" } }],
  messages: [{ from: "919999988888", id: "wamid.XYZ", text: { body: "is this in stock" } }],
} }] }] });
t("incoming meta: from", meta && meta.from, "919999988888");
t("incoming meta: body", meta && meta.text, "is this in stock");
t("incoming meta: id", meta && meta.id, "wamid.XYZ");
t("incoming meta: profile name", meta && meta.name, "B");

// A delivery-status callback carries no message, and must not be answered.
t("incoming: status callback ignored",
  String(incoming({ entry: [{ changes: [{ value: { statuses: [{ id: "a", status: "read" }] } }] }] })),
  "null");

// A sticker has no text, which is different from not being a message at all:
// it still opens a conversation, so it must parse with an empty body.
const sticker = incoming({ entry: [{ changes: [{ value: {
  messages: [{ from: "911111122222", id: "wamid.S", sticker: { id: "s" } }] } }] }] });
t("incoming: sticker parses with no text", sticker && sticker.text, "");

console.log(JSON.stringify(out));
"""

# The owner's own list, as seeded in supabase/0014_escalation_topics_seed.sql.
ROWS = [
    {"label": "Complaint or damage",
     "patterns": ["damag*", "torn", "tear", "stain*", "faded", "colour bleed", "color bleed",
                  "not as shown", "not as described", "fake", "duplicate", "cheated", "fraud",
                  "scam", "worst", "disappoint*", "complaint*", "poor quality", "legal",
                  "consumer court", "report you"]},
    {"label": "Return, exchange or cancellation",
     "patterns": ["return*", "exchang*", "replace*", "cancel*", "send it back", "take it back"]},
    {"label": "Refund or money back",
     "patterns": ["refund*", "money back", "reverse the payment", "chargeback", "money deducted",
                  "amount debited", "payment failed", "double charged"]},
    {"label": "Delivery date or courier promise",
     "patterns": ["when will it", "when will i", "how long will", "how many days",
                  "delivery date", "by when", "reach me by", "deliver by", "dispatch date",
                  "in time for", "before diwali", "before the wedding", "urgent delivery",
                  "same day", "next day"]},
    {"label": "Price negotiation or discount",
     "patterns": ["discount*", "best price", "last price", "final price", "any offer",
                  "negotiat*", "negotiable", "reduce the price", "lower price", "kam kar",
                  "kam karo", "kitna", "thoda kam", "coupon", "promo code", "cheaper",
                  "budget me"]},
    {"label": "Custom or made to order",
     "patterns": ["custom", "customise", "customize", "customised", "customized",
                  "made to order", "can you make", "can you weave", "same design in",
                  "different colour", "different color", "stitch*", "fall and pico", "alter",
                  "alteration", "my measurement"]},
    {"label": "Bulk, wholesale or reseller",
     "patterns": ["bulk", "wholesale", "reseller", "re-seller", "distributor", "dealership",
                  "franchise", "large quantity", "for my shop", "for my store"]},
    {"label": "Press, collaboration or barter",
     "patterns": ["collaborat*", "barter", "influencer", "feature you", "press", "media",
                  "shoot with", "pr package", "gifting", "sponsor*"]},
    {"label": "Asked for a person",
     "patterns": ["speak to", "talk to someone", "talk to a person", "call me",
                  "give me a call", "call back", "phone me", "is this a bot", "are you a bot",
                  "real person", "human", "owner", "manager", "customer care"]},
]

# What must reach the owner, and -- just as important -- what must not.
ESCALATE = [
    # The nine rules, each actually firing.
    ["the saree arrived torn at the border", "Complaint or damage"],
    ["this is damaged", "Complaint or damage"],
    ["I want to return this please", "Return, exchange or cancellation"],
    ["I returned it last week", "Return, exchange or cancellation"],
    ["please cancel my order", "Return, exchange or cancellation"],
    ["when will I get the refund", "Refund or money back"],
    ["when will it reach me", "Delivery date or courier promise"],
    ["how many days for delivery", "Delivery date or courier promise"],
    ["can you give me a discount", "Price negotiation or discount"],
    ["iska kitna hoga", "Price negotiation or discount"],
    ["do you have anything cheaper", "Price negotiation or discount"],
    ["can you make this in green", "Custom or made to order"],
    ["I need custom stitching", "Custom or made to order"],
    ["I want to buy in bulk for my store", "Bulk, wholesale or reseller"],
    ["would you like to collaborate with me", "Press, collaboration or barter"],
    ["I want to speak to someone", "Asked for a person"],
    ["are you a bot", "Asked for a person"],

    # Questions the agent is supposed to answer. Every one of these reaching the
    # owner is the failure that makes him switch the whole thing off.
    ["is this one still available", None],
    ["what is the price of the red Banarasi", None],
    ["what does the shikargah motif depict", None],
    ["how do I wash this", None],
    ["what is the blouse length", None],
    ["is the zari real", None],
    ["do you have it in a deeper red", None],
    ["where is your showroom", None],
    ["how do I order", None],
    ["tell me about this weave", None],

    # The false positives that a bare-substring match would produce. These are
    # the reason ruleHit matches on word boundaries.
    ["does it have metallic zari", None],              # "eta" inside "metallic"
    ["I am a happy customer, lovely piece", None],     # "custom" inside "customer"
    ["my name is Beta Sharma", None],                  # "eta" inside "Beta"
    ["is the alteration of the pallu visible", "Custom or made to order"],
]

# A draft is allowed only if every price in it is recorded, it promises no
# timing, and it promises nothing at all.
RAILS = [
    ["It is available. The price is Rs 18500.", False, ""],
    ["This one is Rs 42,000 and there is one left.", False, ""],
    # An invented price: the single mistake a customer will hold the brand to.
    ["It is a lovely piece, yours for just Rs 9,999.", True, ""],
    ["The price is ₹25000 including shipping.", True, ""],
    # Timing, in all the shapes a model reaches for.
    ["Your parcel will reach you within 3-4 days.", True, ""],
    ["We will deliver it by Friday.", True, ""],
    ["It will be there tomorrow.", True, ""],
    ["We can dispatch before 15 Dec.", True, ""],
    # The one timing it may state is the one the business wrote down itself.
    ["We dispatch within 2 days of the order.", False,
     "We dispatch within 2 days of the order."],
    # Promises.
    ["I guarantee you will love it.", True, ""],
    ["Rest assured it will be perfect.", True, ""],
    # Ordinary, safe answers.
    ["The shikargah shows riders and deer woven into the foliage.", False, ""],
    ["Yes, that one is in stock. Shall I send you a few photographs?", False, ""],
    # A number that is not a price must not trip the price check.
    ["It is 100% silk with a 9 inch border.", False, ""],
    ["The naqsha is drawn on graph paper before a single thread is thrown.", False, ""],
]


def run():
    js = HARNESS % (pure_source(), json.dumps(ROWS), json.dumps(ESCALATE),
                    json.dumps(RAILS))
    built = subprocess.run(
        ["npx", "--yes", "esbuild", "--loader=ts", "--format=cjs", "--log-level=error"],
        input=js, capture_output=True, text=True, cwd=ROOT)
    if built.returncode != 0:
        raise SystemExit("could not transpile the sliced source:\n" + built.stderr)
    ran = subprocess.run(["node", "-e", built.stdout],
                         capture_output=True, text=True, cwd=ROOT)
    if ran.returncode != 0:
        raise SystemExit("the sliced source threw:\n" + (ran.stderr or ran.stdout))
    line = [l for l in ran.stdout.strip().splitlines() if l.startswith("[")]
    if not line:
        raise SystemExit("no result from the harness:\n" + ran.stdout)
    return json.loads(line[-1])


for case in run():
    if case["got"] != case["want"]:
        extra = (" -- %s" % case["why"]) if case.get("why") else ""
        fail("%s\n    got %r, expected %r%s"
             % (case["name"], case["got"], case["want"], extra))

print("=== rails: %d problem(s)" % len(problems))
for p in problems:
    print(p)
sys.exit(1 if problems else 0)
