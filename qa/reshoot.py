"""The re-shoot loop: does a rejected frame cost the owner what it should?

The browser suites stub the whole edge function, so none of them can see whether
`shootOne` re-shoots, stops, or feeds the rejection back -- and that loop is what
decides how much of the owner's image quota a wrong frame costs. So this does two
things: it asserts the loop in `supabase/functions/launch-assist/index.ts` still
has the shape the cases below assume, and then it runs the rule those cases
describe. The first half is what stops this file quietly testing a rule the
function no longer follows.

    python3 qa/reshoot.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FN = os.path.join(ROOT, "supabase", "functions", "launch-assist", "index.ts")


def shape_problems():
    """The function must still be built the way the cases below assume."""
    out = []
    if not os.path.exists(FN):
        return [f"{FN} is missing"]
    s = open(FN, encoding="utf-8").read()
    body = s[s.index("async function shootOne"):] if "async function shootOne" in s else ""
    if not body:
        return ["there is no shootOne in launch-assist: the loop these cases "
                "describe does not exist"]
    body = body[:body.index("\nasync function ") + 1] if "\nasync function " in body[1:] else body
    body = body[:4000]

    if "MAX_ATTEMPTS" not in body:
        out.append("shootOne does not bound itself with MAX_ATTEMPTS")
    if not re.search(r"MAX_ATTEMPTS\s*=\s*Math\.max\(1,\s*Math\.min\(", s):
        out.append("MAX_ATTEMPTS is not clamped, so a bad env var could run the "
                   "loop away with the owner's quota")
    if "correctionBlock" not in body:
        out.append("shootOne does not feed the rejection back as corrections, "
                   "so a second attempt is as blind as the first")
    if not re.search(r"verdict\.match\s*\|\|\s*verdict\.confidence === \"unchecked\"", body):
        out.append("shootOne does not stop on a passing or an unchecked frame")
    if "wantCheck ? MAX_ATTEMPTS : 1" not in body:
        out.append("with checking off, shootOne does not fall back to one attempt")
    # The frame is uploaded by the caller, after the loop -- that is what makes a
    # rejected attempt cost a generation and no storage.
    if "store(" in body:
        out.append("shootOne uploads inside the loop, so rejected attempts are "
                   "stored and charged for")
    return out


MAX_ATTEMPTS = 3
calls = []

def correction_block(differences, attempt):
    lst = [str(d).strip() for d in (differences or []) if str(d).strip()]
    if not lst:
        return ""
    return f"\n\nTHIS IS ATTEMPT {attempt}." + "".join(f"\n- {d}" for d in lst)

def shoot_one(instruction, verdicts, want_check=True):
    """verdicts: what the checker says about attempt 1, 2, 3..."""
    limit = MAX_ATTEMPTS if want_check else 1
    kept = None
    for attempt in range(1, limit + 1):
        note = correction_block(kept["verdict"].get("differences"), attempt) if kept else ""
        calls.append(instruction + note)
        img = f"img-{attempt}"
        if not want_check:
            return {"img": img, "verdict": None, "attempts": attempt}
        verdict = verdicts[min(attempt - 1, len(verdicts) - 1)]
        kept = {"img": img, "verdict": verdict}
        if verdict.get("match") or verdict.get("confidence") == "unchecked":
            return {"img": img, "verdict": verdict, "attempts": attempt}
    return {"img": kept["img"], "verdict": kept["verdict"], "attempts": limit}

bad = []
OK = {"match": True, "confidence": "high", "differences": []}
NO = {"match": False, "confidence": "high",
      "differences": ["The border is wider than the photographs show."]}
UNCHECKED = {"match": True, "confidence": "unchecked",
             "differences": ["Could not check this one: boom"]}

# 1. A frame that passes first time costs exactly one generation.
calls.clear()
r = shoot_one("shot", [OK])
if r["attempts"] != 1 or len(calls) != 1:
    bad.append(f"a frame that passed first time cost {len(calls)} generations")

# 2. A rejected frame is re-shot, and the rejection's words go back in.
calls.clear()
r = shoot_one("shot", [NO, OK])
if r["attempts"] != 2:
    bad.append(f"a rejected frame reported {r['attempts']} attempts, expected 2")
if len(calls) != 2:
    bad.append(f"a rejected frame cost {len(calls)} generations, expected 2")
elif "border is wider" not in calls[1]:
    bad.append("the second attempt was not told what was wrong with the first")
elif "ATTEMPT 2" not in calls[1]:
    bad.append("the second attempt was not told it was a second attempt")
if calls and "border is wider" in calls[0]:
    bad.append("the first attempt was given a correction it could not have earned")

# 3. It stops. A frame rejected every time costs the cap and no more.
calls.clear()
r = shoot_one("shot", [NO, NO, NO, NO, NO])
if len(calls) != MAX_ATTEMPTS:
    bad.append(f"a frame rejected every time cost {len(calls)} generations, "
               f"expected the cap of {MAX_ATTEMPTS}")
if r["verdict"]["match"] is not False:
    bad.append("a frame rejected every time was returned as if it passed")

# 4. An unchecked frame is not a rejected one: re-shooting it would spend money
#    to learn nothing.
calls.clear()
r = shoot_one("shot", [UNCHECKED, OK])
if len(calls) != 1:
    bad.append(f"an unchecked frame was re-shot {len(calls)} times; it should cost 1")

# 5. Checking off means one attempt, whatever the checker would have said.
calls.clear()
r = shoot_one("shot", [NO, NO, NO], want_check=False)
if len(calls) != 1:
    bad.append(f"with checking off a frame cost {len(calls)} generations, expected 1")

bad = shape_problems() + bad

print(f"=== re-shoot loop: {len(bad)} problem(s) in 5 cases, "
      f"against the loop in launch-assist ===")
for b in bad:
    print("  " + b)
sys.exit(1 if bad else 0)
