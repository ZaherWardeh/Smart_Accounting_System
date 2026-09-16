"""One-off migration: add Accounts.code and backfill it.

Already applied to this repo's dev accounting.db - kept here for
reference/reproducibility (e.g. if you're migrating your own pre-existing
database that predates the `code` column). A brand new/empty database
needs none of this: Base.metadata.create_all() creates the Accounts table
with the `code` column already in it.

Numbering scheme: depth-first pre-order traversal of the chart of
accounts, root accounts taken in id order (in this dataset: Assets,
Liabilities, Revenue, Expenses - the existing account creation order
already groups them into sensible categories), children within each
parent also taken in id order. Assets' whole subtree is numbered before
moving to the next root, matching "start at 001 for assets and so on".
Codes are zero-padded to 3 digits.

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
    counter = [0]

    def visit(acc_id):
        counter[0] += 1
        codes[acc_id] = f"{counter[0]:03d}"
        for child_id in children_of.get(acc_id, []):
            visit(child_id)

    for root_id in roots:
        visit(root_id)

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
        indent = "  " if r["parentAccount"] else ""
        print(f"{r['code']}  {indent}{r['name']}  (id={r['id']}, parent={r['parentAccount']})")

    conn.close()


if __name__ == "__main__":
    main()
