"""Run SQL as a given role/user inside a transaction that is always discarded.

The block ends by raising RESULT:<json>. That exception aborts the transaction, so nothing a test
does survives — but the message carries what the test saw. A genuine error inside the block
comes back as that error instead.
"""
import json, os, urllib.request
# The self-hosted backend answers SQL at <SUPABASE_URL>/pg/query for the service role key; Supabase cloud at
# its management API for an access token. Both take {"query": ...} and return the rows as JSON.
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
if SERVICE_KEY:
    QUERY_URL = os.environ["SUPABASE_URL"].rstrip("/") + "/pg/query"
    HEADERS = {"apikey": SERVICE_KEY, "Authorization": f"Bearer {SERVICE_KEY}"}
else:
    QUERY_URL = f"https://api.supabase.com/v1/projects/{os.environ['SUPABASE_PROJECT_REF']}/database/query"
    HEADERS = {"Authorization": f"Bearer {os.environ['SUPABASE_ACCESS_TOKEN']}"}

def raw(sql):
    req = urllib.request.Request(QUERY_URL, data=json.dumps({"query": sql}).encode(),
        headers={**HEADERS, "Content-Type": "application/json", "User-Agent": "survey26-site-patrol"}, method="POST")
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
