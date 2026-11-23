"""Fields the browser reads off an edge function must be fields it returns.

The campaign agent was built to return two or three campaign directions, the
studio was built to show them, every test passed — and the function's final
`return json({...})` never included `options` at all. The studio test stubs the
function, so a stub that returns the field proves nothing about the real one.

This reads both sides of that seam: every `out.<field>` in a page that called an
edge function, against the keys that function actually returns.

The same bug has a second home. A page does not only read the reply object: it
reads the proposal inside it, which is stored and read back later, so the chain
is SHAPE -> model -> database -> page. A field the page reads off that proposal
but the SHAPE never declares is the identical mistake one level down, and the
`out.<field>` check above cannot see it. So the declared SHAPE is parsed too and
checked against every `proposal.<field>` the pages read.

    python3 qa/contract.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Which helper calls which function.
HELPERS = {
    "agent": "campaign-agent",
    "assist": "launch-assist",
    "courier": "shiprocket",
}

# Keys every reply carries, from the json() helper or the error path.
ALWAYS = {"ok", "error", "provider", "model"}


def returned(slug):
    """Keys appearing as `key:` inside any `json({ ... })` in the function."""
    path = os.path.join(ROOT, "supabase", "functions", slug, "index.ts")
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    keys = set()
    for m in re.finditer(r"json\(\{", text):
        depth, i = 0, m.end() - 1
        while i < len(text):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        body = text[m.end():i]
        # only the top level of the returned object
        d, buf = 0, ""
        for ch in body:
            if ch in "{[(":
                d += 1
            elif ch in "}])":
                d -= 1
            if ch == "," and d == 0:
                buf += "\n"
            else:
                buf += ch
        for line in buf.split("\n"):
            k = re.match(r"\s*([a-z_][\w]*)\s*:", line)
            if k:
                keys.add(k.group(1))
            else:
                # shorthand, e.g. json({ images, failed })
                k2 = re.fullmatch(r"\s*([a-z_][\w]*)\s*", line)
                if k2:
                    keys.add(k2.group(1))
    return keys


def shape_keys(slug="campaign-agent", const="SHAPE", level="proposal"):
    """The keys a function's declared SHAPE carries at one nesting level.

    The SHAPE is a template literal of JSON-ish text, so it is read as text
    rather than parsed: anything of the form `"key":` inside the braces that
    follow `"<level>"` counts, at that brace depth only.
    """
    path = os.path.join(ROOT, "supabase", "functions", slug, "index.ts")
    if not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    m = re.search(rf"const {const} = `", text)
    if not m:
        return None
    end = text.index("`;", m.end())
    body = text[m.end():end]

    at = body.find(f'"{level}"')
    if at == -1:
        return None
    start = body.find("{", at)
    if start == -1:
        return None
    depth, i = 0, start
    while i < len(body):
        if body[i] == "{":
            depth += 1
        elif body[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    inner = body[start + 1:i]

    keys, d = set(), 0
    for mm in re.finditer(r'[{}\[\]]|"([a-z_][\w]*)"\s*:', inner):
        tok = mm.group(0)
        if tok in "{[":
            d += 1
        elif tok in "}]":
            d -= 1
        elif d == 0 and mm.group(1):
            keys.add(mm.group(1))
    return keys


def pages():
    out = []
    for base, _, names in os.walk(os.path.join(ROOT, "app")):
        for n in names:
            if n.endswith(".jsx"):
                out.append(os.path.join(base, n))
    for n in os.listdir(os.path.join(ROOT, "components")):
        if n.endswith(".jsx"):
            out.append(os.path.join(ROOT, "components", n))
    return out


def main():
    bad, checked = [], 0
    for path in pages():
        text = open(path, encoding="utf-8").read()
        where = os.path.relpath(path, ROOT)
        for helper, slug in HELPERS.items():
            # `const out = await agent({...})` / `= await assist(`
            for m in re.finditer(rf"(?:const|let)\s+(\w+)\s*=\s*await\s+{helper}\(", text):
                var = m.group(1)
                keys = returned(slug)
                if keys is None:
                    bad.append(f"{where}: calls {helper}(), but supabase/functions/{slug} is missing")
                    continue
                # everything read off that variable after the call
                for f in set(re.findall(rf"\b{var}\.([a-z_][\w]*)\b", text[m.end():])):
                    checked += 1
                    if f not in keys and f not in ALWAYS:
                        bad.append(f"{where}: reads {var}.{f} off {slug}, which never returns {f!r}")

    # The second seam: what the pages read off a stored proposal, against the
    # shape the function declares it returns.
    declared = shape_keys()
    if declared is None:
        bad.append("qa/contract.py: could not read SHAPE out of supabase/functions/campaign-agent")
    else:
        for path in pages():
            text = open(path, encoding="utf-8").read()
            if "proposal" not in text:
                continue
            where = os.path.relpath(path, ROOT)
            # A page may add a key of its own to the proposal before storing it
            # -- the studio folds the reply's `options` in, so the directions
            # survive a reload -- and reading that key back is correct. Whatever
            # a page spreads into is as good as declared, for that page.
            merged = set(re.findall(r"\.\.\.(?:\w+\??\.)?proposal,\s*([a-z_][\w]*)\s*:", text))
            ok = declared | merged
            for f in sorted(set(re.findall(r"\bproposal\??\.([a-z_][\w]*)\b", text))):
                checked += 1
                if f not in ok:
                    bad.append(f"{where}: reads proposal.{f}, which campaign-agent's "
                               f"SHAPE never declares and this page never adds")

    # A third seam, the same bug a level sideways: a page hands a shared
    # component a config value of the wrong shape. `Sheet` calls
    # `cfg.matchOn.find(...)`, so a string there is a TypeError the moment
    # somebody imports a spreadsheet -- and nothing on the page says so until
    # they do. Checked statically because the failure needs a real import to
    # show up.
    ARRAY_KEYS = {
        "matchOn": "components/Sheet.jsx calls .find() on it",
        "columns": "crud.jsx maps over it",
        "fields": "crud.jsx maps over it",
        "options": "crud.jsx maps over a field's options",
        "pkCols": "Children.jsx maps over it",
    }
    for path in pages():
        text = open(path, encoding="utf-8").read()
        where = os.path.relpath(path, ROOT)
        for key, why in ARRAY_KEYS.items():
            for m in re.finditer(rf"\b{key}:\s*(.)", text):
                checked += 1
                nxt = m.group(1)
                # An array literal, a spread, or an expression that could be
                # either -- a bare quote is the one that is certainly wrong.
                if nxt in "\"'":
                    bad.append(f"{where}: {key} is a string, but {why} \u2014 wrap it "
                               f"in an array")

    seen, uniq = set(), []
    for b in bad:
        if b not in seen:
            seen.add(b); uniq.append(b)
    print(f"=== contract: {len(uniq)} problem(s) in {checked} field read(s) ===")
    for b in uniq:
        print("  " + b)
    return 1 if uniq else 0


if __name__ == "__main__":
    sys.exit(main())
