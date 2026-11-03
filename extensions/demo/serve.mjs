/**
 * Local static server for the DemoBook fixture page.
 * Usage: node demo/serve.mjs [port]   (default 4173)
 */
import { createServer } from "node:http";
import { readFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(fileURLToPath(import.meta.url));
const port = Number(process.argv[2] ?? 4173);

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
};

const server = createServer(async (req, res) => {
  try {
    const url = new URL(req.url ?? "/", `http://localhost:${port}`);
    const path = url.pathname === "/" ? "/demo-sportsbook.html" : url.pathname;
    const file = join(root, path.replace(/^\/+/, ""));
    const body = await readFile(file);
    res.writeHead(200, {
      "Content-Type": MIME[path.slice(path.lastIndexOf("."))] ?? "application/octet-stream",
      "Cache-Control": "no-store",
    });
    res.end(body);
  } catch {
    res.writeHead(404, { "Content-Type": "text/plain" });
    res.end("not found");
  }
});

server.listen(port, "127.0.0.1", () => {
  console.log(`DemoBook fixture: http://localhost:${port}/demobook`);
});
