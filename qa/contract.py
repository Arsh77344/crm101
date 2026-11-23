"""Fields the browser reads off an edge function must be fields it returns.

The campaign agent was built to return two or three campaign directions, the
studio was built to show them, every test passed — and the function's final
`return json({...})` never included `options` at all. The studio test stubs the
function, so a stub that returns the field proves nothing about the real one.

This reads both sides of that seam: every `out.<field>` in a page that called an
edge function, against the keys that function actually returns.

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
