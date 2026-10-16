"""Writes each person's access in plain English (for the README).
Run:  python -m app.describe"""
from .db import connect

def scope_text(g):
    parts = []
    parts.append(f"client {g['client']}" if g["client_id"] else "all clients")
    parts.append(f"branch {g['branch']}" if g["branch_id"] else "all branches")
    parts.append(f"{g['direction']}s only" if g["direction"] else "both directions")
    parts.append(f"{g['mode'].upper()} only" if g["mode"] else "all modes")
    return ", ".join(parts)

def describe(con):
    out = []
    for u in con.execute("SELECT * FROM users ORDER BY rowid"):
        line = f"**{u['name']}** ({u['kind']})"
        if u["absent_from"]:
            line += f" — absent {u['absent_from']} to {u['absent_until']}"
        gs = con.execute("""SELECT g.*, c.name AS client, b.name AS branch FROM grants g
              LEFT JOIN clients c ON c.id=g.client_id LEFT JOIN branches b ON b.id=g.branch_id
              WHERE g.user_id=? ORDER BY g.role, g.id""", (u["id"],)).fetchall()
        out.append(line)
        if not gs: out.append("  - No grants: can do nothing (deny by default).")
        for g in gs:
            when = f"since {g['valid_from']}" + (f", ended {g['valid_to']}" if g["valid_to"] else "")
            out.append(f"  - Has role **{g['role']}** for {scope_text(g)} ({when}).")
    for d in con.execute("SELECT * FROM delegations"):
        out.append(f"\nDelegation: {d['to_user']} covers jobs owned by {d['from_user']} "
                   f"from {d['valid_from']} to {d['valid_to']}.")
    return "\n".join(out)

if __name__ == "__main__":
    print(describe(connect()))
