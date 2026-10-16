"""HTTP API (Python standard library only: no installs, runs anywhere).
Run:  python -m app.api      then open http://localhost:8000/api

Identity: acting endpoints read the caller from the `X-User` header. There is no login -- authenticating
people is out of scope for an access-DECISION service (see README). Behind a real login, that header
would be set by the gateway, not the client.
Time: NFPL_TODAY (YYYY-MM-DD) pins "today" for demos; default is the real date.
"""
import json, os, re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from . import db, engine, queries

def _today(): return os.environ.get("NFPL_TODAY") or None

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _send(self, code, body):
        data = json.dumps(body, indent=2, default=str).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers(); self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        try: return json.loads(self.rfile.read(n) or b"{}")
        except ValueError: return None

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in (("Access-Control-Allow-Origin", "*"), ("Access-Control-Allow-Headers", "Content-Type, X-User"),
                     ("Access-Control-Allow-Methods", "GET, POST, OPTIONS")): self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        if urlparse(self.path).path in ("/", "/index.html"):
            data = open(os.path.join(os.path.dirname(__file__), "static", "index.html"), "rb").read()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        self._route("GET")
    def do_POST(self): self._route("POST")

    def _route(self, method):
        url = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(url.query).items()}; p = url.path.rstrip("/") or "/"
        con = db.connect()
        try:
            code, body = self.dispatch(con, method, p, q)
        except Exception as e:                       # never leak a stack trace; fail closed
            code, body = 500, {"error": "internal error", "detail": str(e)}
        finally:
            con.close()
        self._send(code, body)

    def dispatch(self, con, m, p, q):
        today = q.get("today") or _today(); who = self.headers.get("X-User") or q.get("user")
        if m == "GET" and p == "/api":
            return 200, {"service": "NFPL access control", "endpoints": [
                "GET  /api/meta", "GET  /api/users", "GET  /api/users/{id}/access", "GET  /api/jobs?limit=&offset=&ref=", "GET  /api/jobs/{id}",
                "GET  /api/can?user=&action=&job=&reason=", "GET  /api/explain?a=&b=&action=&job=",
                "GET  /api/waiting?user=", "GET  /api/jobs/{id}/history?decisions=0|1",
                "GET  /api/jobs/{id}/who-could-change?date=YYYY-MM-DD",
                "POST /api/jobs/{id}/actions/{action}   (X-User header; body {reason})",
                "POST /api/grants   (X-User=admin; body {user, role, client, branch, direction, mode, reason})",
                "POST /api/grants/{id}/revoke   (X-User=admin; body {reason})",
                "GET  /api/audit?limit="]}
        if m == "GET" and p == "/api/meta":
            return 200, {"today": engine._today(today),
                         "clients": [dict(r) for r in con.execute("SELECT * FROM clients")],
                         "branches": [dict(r) for r in con.execute("SELECT * FROM branches")]}
        if m == "GET" and (g := re.fullmatch(r"/api/jobs/(\d+)", p)):
            r = con.execute("SELECT * FROM jobs WHERE id=?", (int(g[1]),)).fetchone()
            return (200, dict(r)) if r else (404, {"error": "no such job"})
        if m == "GET" and p == "/api/users":
            return 200, [dict(r) for r in con.execute("SELECT id,name,kind,status,absent_from,absent_until FROM users")]
        if m == "GET" and (g := re.fullmatch(r"/api/users/(\w+)/access", p)):
            rows = con.execute("""SELECT g.id, g.role, g.client_id, g.branch_id, g.direction, g.mode, g.valid_from,
                g.valid_to, g.created_by, g.reason FROM grants g WHERE user_id=? ORDER BY g.id""", (g[1],)).fetchall()
            return 200, {"user": g[1], "grants": [dict(r) for r in rows],
                         "delegations": [dict(r) for r in con.execute(
                             "SELECT * FROM delegations WHERE to_user=? OR from_user=?", (g[1], g[1]))]}
        if m == "GET" and p == "/api/jobs":
            lim, off = min(int(q.get("limit", 50)), 200), int(q.get("offset", 0))
            if q.get("ref"):
                return 200, [dict(r) for r in con.execute("SELECT * FROM jobs WHERE ref LIKE ? LIMIT 20", (q["ref"] + "%",))]
            return 200, [dict(r) for r in con.execute("SELECT * FROM jobs ORDER BY id LIMIT ? OFFSET ?", (lim, off))]
        if m == "GET" and p == "/api/can":
            if not q.get("user") or not q.get("action"): return 400, {"error": "user and action required"}
            return 200, engine.can(con, q["user"], q["action"], int(q["job"]) if q.get("job") else None,
                                   reason=q.get("reason"), today=today, log=q.get("log") == "1")
        if m == "GET" and p == "/api/explain":
            return 200, engine.explain_diff(con, q["a"], q["b"], q["action"], int(q["job"]), today=today)
        if m == "GET" and p == "/api/waiting":
            if not who: return 400, {"error": "user required"}
            return 200, queries.waiting_for_me(con, who, today=today, limit=min(int(q.get("limit", 50)), 200),
                                               offset=int(q.get("offset", 0)))
        if m == "GET" and (g := re.fullmatch(r"/api/jobs/(\d+)/history", p)):
            return 200, queries.job_history(con, int(g[1]), decisions=q.get("decisions", "1") != "0")
        if m == "GET" and (g := re.fullmatch(r"/api/jobs/(\d+)/who-could-change", p)):
            if not q.get("date"): return 400, {"error": "date=YYYY-MM-DD required"}
            r = queries.who_could_change(con, int(g[1]), q["date"]); return (200, r) if r else (404, {"error": "no such job"})
        if m == "GET" and p == "/api/audit":
            return 200, [dict(r) for r in con.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (min(int(q.get("limit", 50)), 500),))]
        # ---- writes: always need an identified caller ----
        if m == "POST":
            if not who: return 401, {"error": "X-User header required"}
            b = self._body()
            if b is None: return 400, {"error": "invalid JSON"}
            if g := re.fullmatch(r"/api/jobs/(\d+)/actions/(\w+)", p):
                r = engine.perform(con, who, g[2], int(g[1]), reason=b.get("reason"), today=today)
                return (200 if r["allowed"] else 403), r
            if p == "/api/grants":
                r = engine.grant_role(con, who, b.get("user"), b.get("role"), client_id=b.get("client"), branch_id=b.get("branch"),
                                      direction=b.get("direction"), mode=b.get("mode"), reason=b.get("reason"), today=today)
                return (201 if r["ok"] else 403), r
            if g := re.fullmatch(r"/api/grants/(\d+)/revoke", p):
                r = engine.revoke_grant(con, who, int(g[1]), reason=b.get("reason"), today=today)
                return (200 if r["ok"] else 403), r
        return 404, {"error": "not found"}

def main():
    if not os.path.exists(db.DB_PATH):
        from .seed import seed; seed(db.DB_PATH); print("No database found: loaded sample data.")
    port = int(os.environ.get("PORT", 8000))
    print(f"NFPL access service on http://localhost:{port}/api  (db: {db.DB_PATH})")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()

if __name__ == "__main__":
    main()
