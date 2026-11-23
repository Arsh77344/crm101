"""The part labels the browser offers must be ones the model is told the meaning of.

lib/parts.js holds the labels and the filename patterns; the KINDS table in
supabase/functions/launch-assist/index.ts holds what each label MEANS. They are
two files that have to agree. A label offered in the browser that the function
does not know is explained to the model as "unlabelled" rather than failing — so
nothing breaks loudly, which is exactly why this is worth checking.

    python3 qa/parts.py
"""
import os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLIENT = os.path.join(ROOT, "lib", "parts.js")
SERVER = os.path.join(ROOT, "supabase", "functions", "launch-assist", "index.ts")

# A label the browser always offers and the function handles by name, not by table.
ALWAYS = {"Unlabelled"}


def client_kinds():
    """{kind name: [labels]} for the kinds actually REACHABLE from kindFor().

    Reading every `const X = {options: ...}` in the file is not the same thing:
    a kind can be declared and then left out of the exported KINDS array, which
    means no product ever resolves to it. That is the bug this function exists
    to see, so it starts from the export, not from the declarations.
    """
    text = open(CLIENT, encoding="utf-8").read()
    declared = {}
    for m in re.finditer(r"const (\w+) = \{(.*?)\n\};", text, re.S):
        name, body = m.group(1), m.group(2)
        opts = re.search(r"options: \[(.*?)\]", body, re.S)
        if opts:
            declared[name] = re.findall(r"'([^']+)'", opts.group(1))

    exported = re.search(r"export const KINDS = \[(.*?)\];", text, re.S)
    names = re.findall(r"\w+", exported.group(1)) if exported else []
    # GENERIC is the fallback kindFor() returns, so it is reachable without
    # being listed.
    if "GENERIC" in declared:
        names.append("GENERIC")

    out = {n: declared[n] for n in names if n in declared}
    for n in sorted(set(declared) - set(names)):
        out[f"{n} (DECLARED BUT NOT IN KINDS)"] = declared[n]
    return out


def server_kinds():
    """{kind name: [labels]} from each `parts: {...}` block in the KINDS table."""
    text = open(SERVER, encoding="utf-8").read()
    out = {}
    # KINDS entries plus the GENERIC fallback
    for m in re.finditer(r"(\w+): \{\n\s+whole: \"[^\"]+\",(.*?)\n  \},", text, re.S):
        out[m.group(1)] = re.findall(r"^\s+\"?([A-Z][\w-]*)\"?:", m.group(2), re.M)
    g = re.search(r"const GENERIC: Kind = \{(.*?)\n\};", text, re.S)
    if g:
        p = re.search(r"parts: \{(.*?)\n  \},", g.group(1), re.S)
        if p:
            out["GENERIC"] = re.findall(r"^\s+\"?([A-Z][\w-]*)\"?:", p.group(1), re.M)
    return out


def main():
    client, server = client_kinds(), server_kinds()
    known = set()
    for labels in server.values():
        known |= set(labels)
    known |= ALWAYS

    bad = []
    if not client:
        bad.append("could not read any labels out of lib/parts.js")
    if not server:
        bad.append("could not read any labels out of the KINDS table")

    for name, labels in sorted(client.items()):
        if "NOT IN KINDS" in name:
            bad.append(f"lib/parts.js declares {name.split()[0]!r} but leaves it out of the "
                       f"exported KINDS array, so no product can ever resolve to it")
        for l in labels:
            if l not in known:
                bad.append(f"lib/parts.js {name} offers {l!r}, which the function cannot explain")

    # Every kind the function knows should be reachable from the browser too,
    # or the browser can never produce a photo of that kind labelled properly.
    reachable = set(k.split()[0].lower() for k in client if "NOT IN KINDS" not in k)
    missing = sorted(set(k.lower() for k in server) - reachable - {"generic"})
    for k in missing:
        bad.append(f"the function has a {k!r} kind the browser offers no labels for")

    print(f"=== parts: {len(bad)} problem(s) "
          f"({len(client)} kinds in the browser, {len(server)} in the function, "
          f"{len(known)} labels known) ===")
    for b in bad:
        print("  " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
