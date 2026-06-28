import { httpRouter } from "convex/server";
import { httpAction } from "./_generated/server";
import { internal } from "./_generated/api";

const http = httpRouter();

function unauthorized(): Response {
  return new Response(JSON.stringify({ error: "unauthorized" }), {
    status: 401,
    headers: { "Content-Type": "application/json" },
  });
}

function authorize(request: Request): boolean {
  const expected = process.env.INGEST_TOKEN;
  if (!expected) return false;
  const header = request.headers.get("Authorization") ?? "";
  const prefix = "Bearer ";
  if (!header.startsWith(prefix)) return false;
  return header.slice(prefix.length) === expected;
}

http.route({
  path: "/ingest",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    if (!authorize(request)) return unauthorized();

    let body: any;
    try {
      body = await request.json();
    } catch {
      return new Response(JSON.stringify({ error: "invalid json" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const message = typeof body.message === "string" ? body.message : "";
    if (!message) {
      return new Response(JSON.stringify({ error: "message required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const timestamp =
      typeof body.timestamp === "string" ? body.timestamp : new Date().toISOString();
    const ts = Date.parse(timestamp);

    const id = await ctx.runMutation(internal.prompts.insert, {
      username: body.username ?? undefined,
      message,
      response: body.response ?? undefined,
      timestamp,
      ts: Number.isFinite(ts) ? ts : Date.now(),
      project: typeof body.project === "string" ? body.project : "unknown",
      projectPath:
        typeof body.project_path === "string"
          ? body.project_path
          : typeof body.projectPath === "string"
            ? body.projectPath
            : "",
      sessionId:
        typeof body.session_id === "string"
          ? body.session_id
          : typeof body.sessionId === "string"
            ? body.sessionId
            : "",
      model: body.model ?? undefined,
    });

    return new Response(JSON.stringify({ ok: true, id }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }),
});

http.route({
  path: "/unprocessed",
  method: "GET",
  handler: httpAction(async (ctx, request) => {
    if (!authorize(request)) return unauthorized();

    const url = new URL(request.url);
    const startTs = Number(url.searchParams.get("startTs"));
    const endTs = Number(url.searchParams.get("endTs"));
    if (!Number.isFinite(startTs) || !Number.isFinite(endTs) || endTs <= startTs) {
      return new Response(
        JSON.stringify({ error: "startTs and endTs (ms) required, endTs > startTs" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    const rows = await ctx.runQuery(internal.prompts.listInRange, {
      startTs,
      endTs,
      onlyUnprocessed: true,
    });

    return new Response(JSON.stringify({ rows }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }),
});

http.route({
  path: "/all",
  method: "GET",
  handler: httpAction(async (ctx, request) => {
    if (!authorize(request)) return unauthorized();

    const url = new URL(request.url);
    const startTs = Number(url.searchParams.get("startTs"));
    const endTs = Number(url.searchParams.get("endTs"));
    if (!Number.isFinite(startTs) || !Number.isFinite(endTs) || endTs <= startTs) {
      return new Response(
        JSON.stringify({ error: "startTs and endTs (ms) required, endTs > startTs" }),
        { status: 400, headers: { "Content-Type": "application/json" } },
      );
    }

    const rows = await ctx.runQuery(internal.prompts.listInRange, {
      startTs,
      endTs,
      onlyUnprocessed: false,
    });

    return new Response(JSON.stringify({ rows }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }),
});

http.route({
  path: "/mark-processed",
  method: "POST",
  handler: httpAction(async (ctx, request) => {
    if (!authorize(request)) return unauthorized();

    let body: any;
    try {
      body = await request.json();
    } catch {
      return new Response(JSON.stringify({ error: "invalid json" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const ids = Array.isArray(body.ids) ? body.ids : null;
    if (!ids) {
      return new Response(JSON.stringify({ error: "ids array required" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    const result = await ctx.runMutation(internal.prompts.markProcessed, { ids });
    return new Response(JSON.stringify({ ok: true, ...result }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }),
});

export default http;
