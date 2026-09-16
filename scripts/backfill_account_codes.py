"""One-off migration: add Accounts.code and backfill it.

Already applied to this repo's dev accounting.db - kept here for
reference/reproducibility (e.g. if you're migrating your own pre-existing
database that predates the `code` column). A brand new/empty database
needs none of this: Base.metadata.create_all() creates the Accounts table
with the `code` column already in it.

Numbering scheme: hierarchical, parent-prefixed. Each of the top-level
(root) accounts gets a 3-digit code in id order (001, 002, 003, ...).
Every account below that gets its parent's code plus a 2-digit position
among that parent's children, also in id order - so "Assets" = 001,
"Fixed Assets" (Assets' 1st child) = 00101, "Assets" -> "Current Assets"
(2nd child) -> "Customers" (1st child of that) = 0010201, and so on.
Codes are plain, unseparated digit strings (no dots) so this repo's
GET /reports/chart-of-accounts?/=&sort-by-code and the Accounts page's
client-side sort both work with a single lexicographic string comparison
(NOT numeric-aware collation - a fixed-width parent prefix is what keeps
each subtree contiguous when sorted as plain strings; numeric collation
would compare the whole digit run as one number and break that).

Recomputes every account's code from the tree's current shape - re-running
this after codes have been hand-edited through the UI will overwrite them.

Usage: python scripts/backfill_account_codes.py [path/to/accounting.db]
"""
import sqlite3
import sys


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else "accounting.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    cur.execute("PRAGMA table_info(Accounts)")
    columns = {row["name"] for row in cur.fetchall()}
    if "code" not in columns:
        cur.execute("ALTER TABLE Accounts ADD COLUMN code TEXT")
        print("Added Accounts.code column.")
    else:
        print("Accounts.code column already exists.")

    cur.execute("SELECT id, name, parentAccount FROM Accounts")
    rows = cur.fetchall()
    accounts_by_id = {r["id"]: r for r in rows}

    children_of = {}
    for r in rows:
        children_of.setdefault(r["parentAccount"], []).append(r["id"])
    for kids in children_of.values():
        kids.sort()

    roots = sorted(children_of.get(None, []))

    codes = {}

    def assign(acc_id, code):
        codes[acc_id] = code
        for position, child_id in enumerate(children_of.get(acc_id, []), start=1):
            assign(child_id, code + f"{position:02d}")

    for position, root_id in enumerate(roots, start=1):
        assign(root_id, f"{position:03d}")

    if len(codes) != len(rows):
        missing = set(accounts_by_id) - set(codes)
        print(f"ERROR: {len(missing)} account(s) unreachable from any root (cycle or bad data): {missing}")
        sys.exit(1)

    for acc_id, code in codes.items():
        cur.execute("UPDATE Accounts SET code = ? WHERE id = ?", (code, acc_id))

    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_accounts_code ON Accounts(code)")

    conn.commit()

    print(f"\nBackfilled {len(codes)} accounts:\n")
    cur.execute("SELECT id, code, name, parentAccount FROM Accounts ORDER BY code")
    for r in cur.fetchall():
        depth = (len(r["code"]) - 3) // 2 if r["code"] else 0
        indent = "  " * depth
        print(f"{r['code']:<12} {indent}{r['name']}  (id={r['id']}, parent={r['parentAccount']})")

    conn.close()


if __name__ == "__main__":
    main()
