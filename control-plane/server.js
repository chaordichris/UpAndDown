// UpAndDown control plane — zero-dependency local server.
// Reads strategy status files (see CONTRACT.md), serves the dashboard,
// and runs whitelisted actions. It never computes edges or sizes.

import http from "node:http";
import { readFileSync, existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { loadConfig, buildOverview } from "./lib/status.js";
import { ActionRunner } from "./lib/actions.js";

const ROOT = path.dirname(fileURLToPath(import.meta.url));
const config = loadConfig(ROOT);
const runner = new ActionRunner(ROOT, config.actions);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
};

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(body, null, 2));
}

function serveStatic(res, urlPath) {
  const rel = urlPath === "/" ? "index.html" : urlPath.replace(/^\/+/, "");
  const file = path.join(ROOT, "public", path.normalize(rel));
  if (!file.startsWith(path.join(ROOT, "public")) || !existsSync(file)) {
    res.writeHead(404).end("not found");
    return;
  }
  res.writeHead(200, { "content-type": MIME[path.extname(file)] ?? "application/octet-stream" });
  res.end(readFileSync(file));
}

const server = http.createServer((req, res) => {
  const url = new URL(req.url, "http://localhost");
  try {
    if (req.method === "GET" && url.pathname === "/api/overview") {
      return json(res, 200, buildOverview(ROOT, config));
    }
    if (req.method === "GET" && url.pathname === "/api/runs") {
      return json(res, 200, runner.list());
    }
    const runMatch = url.pathname.match(/^\/api\/runs\/([\w-]+)$/);
    if (req.method === "GET" && runMatch) {
      const run = runner.get(runMatch[1]);
      return run ? json(res, 200, run) : json(res, 404, { error: "unknown run" });
    }
    const actMatch = url.pathname.match(/^\/api\/actions\/([\w-]+)\/run$/);
    if (req.method === "POST" && actMatch) {
      const result = runner.start(actMatch[1]);
      return result.error ? json(res, 400, result) : json(res, 202, result);
    }
    if (req.method === "GET") return serveStatic(res, url.pathname);
    json(res, 405, { error: "method not allowed" });
  } catch (err) {
    json(res, 500, { error: String(err?.message ?? err) });
  }
});

server.listen(config.port, "127.0.0.1", () => {
  console.log(`UpAndDown control plane → http://localhost:${config.port}`);
});
