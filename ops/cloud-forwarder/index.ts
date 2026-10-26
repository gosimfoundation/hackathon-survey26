// Deployed to the retired Supabase cloud project (vdiemcofukuxglqsmlyz) under the names of the functions that
// published clients still call by their cloud URL (survey26-cli, kimi-relay, sophon). Every request is passed
// through unchanged to the same function on the self-hosted backend, so CLIs older than 1.9.2 keep working.
const TARGET = "https://survey26-api.liyao.space/functions/v1";

Deno.serve(async (request) => {
  const url = new URL(request.url);
  // Supabase passes the path starting with the function name: /<slug>/<rest>
  const path = url.pathname.startsWith("/functions/v1/") ? url.pathname.slice("/functions/v1".length) : url.pathname;
  const headers = new Headers(request.headers);
  for (const name of ["host", "content-length", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-for", "x-real-ip"]) {
    headers.delete(name);
  }
  const init: RequestInit & { duplex?: string } = { method: request.method, headers, redirect: "manual" };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }
  try {
    const response = await fetch(TARGET + path + url.search, init);
    return new Response(response.body, { status: response.status, headers: response.headers });
  } catch {
    return new Response(JSON.stringify({ error: "upstream_unavailable" }), {
      status: 502,
      headers: { "content-type": "application/json" },
    });
  }
});
