"""Every column and join the app asks Postgres for, checked against the schema.

The dashboard once asked for `order_items.units`, which has never existed — the
table was already there with `quantity` when a `create table if not exists`
quietly did nothing. Nothing caught it until the page went white in front of the
owner. This reads the real query strings out of the source and checks each name,
so the next one is caught here instead.

    python3 qa/schema.py

The snapshot in qa/schema-snapshot.json is read from the live database with
information_schema. After a migration, refresh it by running this against the
project and replacing the file — the query is in `SNAPSHOT_SQL` below.
"""
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

SNAPSHOT_SQL = """
select json_build_object(
  'taken_at', now()::date,
  'columns', (select json_object_agg(table_name, cols) from (
      select table_name, json_agg(column_name order by ordinal_position) as cols
      from information_schema.columns where table_schema='public'
      group by table_name) x),
  'relations', (select json_agg(r) from (
      select distinct tc.table_name || '>' || ccu.table_name as r
      from information_schema.table_constraints tc
      join information_schema.constraint_column_usage ccu
        on ccu.constraint_name=tc.constraint_name and ccu.table_schema=tc.table_schema
      where tc.constraint_type='FOREIGN KEY' and tc.table_schema='public') y))::text;
"""

# PostgREST names that are not columns.
NOT_A_COLUMN = {"count", "*"}


def sources():
    out = []
    for base, _, names in os.walk(ROOT):
        if "node_modules" in base or "/.next" in base or "/out" in base:
            continue
        for n in names:
            if n.endswith((".jsx", ".js", ".ts")) and not n.endswith(".d.ts"):
                out.append(os.path.join(base, n))
    return out


def split_top(cols):
    """Split a select list on the commas that are not inside a join's brackets."""
    out, depth, buf = [], 0, ""
    for ch in cols:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(buf); buf = ""
        else:
            buf += ch
    out.append(buf)
    return [x.strip() for x in out if x.strip()]


def asked_for(text):
    """(table, name, is_join) for every .from('t').select('...') in one file.

    A token holding a bracket is an embedded relation — `products(cost_price)`
    asks for the join, not for a column called `products`. Everything else at
    the top level is a column of the table itself.
    """
    for m in re.finditer(
            r"\.from\(\s*['\"]([a-z_]+)['\"]\s*\)[\s\S]{0,400}?\.select\(\s*(['\"`])([\s\S]*?)\2",
            text):
        table, cols = m.group(1), m.group(3)
        cols = re.sub(r"\$\{[^}]*\}", "", cols)      # template holes
        for token in split_top(cols):
            if "(" in token:
                # alias:relation!hint(...)  ->  relation
                head = token.split("(", 1)[0]
                name = head.split(":")[-1].split("!")[0].strip()
                if name and re.fullmatch(r"[a-z_][a-z0-9_]*", name):
                    yield table, name, True
                # columns inside the join belong to that relation, checked there
                inner = token[token.index("(") + 1:token.rindex(")")] if ")" in token else ""
                for sub in split_top(inner):
                    if "(" in sub:
                        continue
                    c = sub.split(":")[-1].split("!")[0].strip()
                    if c and c not in NOT_A_COLUMN and re.fullmatch(r"[a-z_][a-z0-9_]*", c):
                        yield name, c, False
            else:
                c = token.split(":")[-1].split("!")[0].strip()
                if c and c not in NOT_A_COLUMN and re.fullmatch(r"[a-z_][a-z0-9_]*", c):
                    yield table, c, False


def main():
    snap = json.load(open(os.path.join(ROOT, "qa", "schema-snapshot.json")))
    cols, rels = snap["columns"], set(snap["relations"])
    bad, checked = [], 0

    for path in sources():
        try:
            text = open(path, encoding="utf-8").read()
        except OSError:
            continue
        for table, name, is_join in asked_for(text):
            checked += 1
            where = os.path.relpath(path, ROOT)
            if table not in cols:
                bad.append(f"{where}: no table {table!r}")
                continue
            if is_join:
                # An embedded relation needs a foreign key in one direction.
                if name not in cols:
                    bad.append(f"{where}: {table} joins {name!r}, which is not a table")
                elif f"{table}>{name}" not in rels and f"{name}>{table}" not in rels:
                    bad.append(f"{where}: {table} joins {name} with no foreign key between them")
            elif name not in cols[table]:
                near = [c for c in cols[table] if c.startswith(name[:4])]
                bad.append(f"{where}: {table} has no column {name!r}"
                           + (f" — did you mean {', '.join(near)}?" if near else ""))

    seen, uniq = set(), []
    for b in bad:
        if b not in seen:
            seen.add(b); uniq.append(b)
    print(f"=== schema: {len(uniq)} problem(s) in {checked} column and join references "
          f"(snapshot {snap['taken_at']}) ===")
    for b in uniq:
        print("  " + b)
    return 1 if uniq else 0


if __name__ == "__main__":
    sys.exit(main())
