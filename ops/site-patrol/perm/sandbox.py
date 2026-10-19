"""Run SQL as a given role/user inside a transaction that is always discarded.

The block ends by raising RESULT:<json>. That exception aborts the transaction, so nothing a test
does survives — but the message carries what the test saw. A genuine error inside the block
comes back as that error instead.
"""
import json, os, urllib.request
REF = os.environ["SUPABASE_PROJECT_REF"]; TOKEN = os.environ["SUPABASE_ACCESS_TOKEN"]

def raw(sql):
    req = urllib.request.Request(f"https://api.supabase.com/v1/projects/{REF}/database/query",
        data=json.dumps({"query": sql}).encode(), headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        try: return e.code, json.loads(body)
        except Exception: return e.code, body

def as_user(body_sql, uid=None, role="authenticated", setup_sql=""):
    """body_sql: plpgsql statements; must assign the jsonb variable `res`."""
    claims = json.dumps({"sub": uid, "role": role}) if uid else json.dumps({"role": role})
    sql = f"""do $sandbox$ declare res jsonb := '{{}}'::jsonb; tmp jsonb; n int; t text; begin
{setup_sql}
perform set_config('request.jwt.claims', {pg(claims)}, true);
perform set_config('request.jwt.claim.sub', {pg(uid or '')}, true);
perform set_config('request.jwt.claim.role', {pg(role)}, true);
execute 'set local role {role}';
{body_sql}
raise exception 'RESULT:%', res::text;
end $sandbox$;"""
    st, out = raw(sql)
    msg = out.get("message", "") if isinstance(out, dict) else str(out)
    if "RESULT:" in msg:
        return True, json.loads(msg.split("RESULT:", 1)[1].split("\n")[0].strip())
    return False, msg

def pg(s): return "'" + str(s).replace("'", "''") + "'"

def as_user_raw(body_sql):
    """Run a block that switches identities itself (see suite.become). Always discarded."""
    sql = f"""do $sandbox$ declare res jsonb := '{{}}'::jsonb; tmp jsonb; n int; t text; begin
{body_sql}
execute 'reset role';
raise exception 'RESULT:%', res::text;
end $sandbox$;"""
    st, out = raw(sql)
    msg = out.get("message", "") if isinstance(out, dict) else str(out)
    if "RESULT:" in msg:
        return True, json.loads(msg.split("RESULT:", 1)[1].split("\n")[0].strip())
    return False, msg
