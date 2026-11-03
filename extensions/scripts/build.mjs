/**
 * PropStein Live Sniper — build script (esbuild).
 * Produces:
 *   dist/propstein-chrome/          — loadable Chrome MV3 extension (prod manifest)
 *   dist/propstein-chrome-dev/      — dev/test build (localhost host permission)
 *   dist/propstein-web-companion/   — standalone companion page
 */
import { build, context } from "esbuild";
import { cp, mkdir, rm, readFile, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const root = dirname(fileURLToPath(import.meta.url));
const extRoot = join(root, "..");
const apps = join(extRoot, "apps");
const repoIcons = join(extRoot, "..", "extension", "icons");

const isWatch = process.argv.includes("--watch");

/** Shared esbuild options for extension bundles. */
const common = {
  bundle: true,
  format: "esm",
  target: ["chrome124", "safari17"],
  sourcemap: process.argv.includes("--dev") ? "inline" : false,
  minify: !process.argv.includes("--dev") && !isWatch,
  legalComments: "none",
  logLevel: "info",
};

async function buildAll() {
  await rm(join(extRoot, "dist"), { recursive: true, force: true });
  await mkdir(join(extRoot, "dist"), { recursive: true });

  // --- Bundles -------------------------------------------------------------
  const entries = [
    {
      entryPoints: [join(apps, "chrome", "src", "background.ts")],
      outfile: join(extRoot, "dist", "propstein-chrome", "background.js"),
    },
    {
      entryPoints: [join(apps, "chrome", "src", "content-bridge.ts")],
      outfile: join(extRoot, "dist", "propstein-chrome", "content-bridge.js"),
    },
    {
      entryPoints: [join(apps, "chrome", "src", "panel-entry.tsx")],
      outfile: join(extRoot, "dist", "propstein-chrome", "panel.js"),
    },
  ];
  for (const e of entries) {
    await build({ ...common, ...e, define: { globalThis: "globalThis" } });
  }

  // --- Static assets -------------------------------------------------------
  const out = join(extRoot, "dist", "propstein-chrome");
  await cp(join(apps, "chrome", "sidepanel.html"), join(out, "sidepanel.html"));
  await cp(join(apps, "chrome", "manifest.json"), join(out, "manifest.json"));
  await mkdir(join(out, "icons"), { recursive: true });
  // Reuse the repository's existing extension icons (swap for dedicated
  // Live Sniper icons before store submission — documented in the release
  // checklist).
  try {
    await cp(repoIcons, join(out, "icons"), { recursive: true });
  } catch {
    // Icons unavailable in this checkout — generate neutral placeholders.
    const { neutralIconPng } = await import("./make-icon.mjs");
    await writeFile(join(out, "icons", "icon16.png"), neutralIconPng(16));
    await writeFile(join(out, "icons", "icon48.png"), neutralIconPng(48));
    await writeFile(join(out, "icons", "icon128.png"), neutralIconPng(128));
  }
  // The web companion ships inside the extension too (extension-page mode).
  await mkdir(join(out, "web-companion"), { recursive: true });
  await cp(join(apps, "web-companion", "index.html"), join(out, "web-companion", "index.html"));
  await cp(join(out, "panel.js"), join(out, "web-companion", "panel.js"));
  await cp(join(out, "panel.css"), join(out, "web-companion", "panel.css"));

  // --- Dev build (adds localhost fixture host permission for e2e) ----------
  const devOut = join(extRoot, "dist", "propstein-chrome-dev");
  await cp(out, devOut, { recursive: true });
  const devManifest = JSON.parse(await readFile(join(devOut, "manifest.json"), "utf8"));
  const devOverride = JSON.parse(await readFile(join(apps, "chrome", "manifest.dev.json"), "utf8"));
  await writeFile(join(devOut, "manifest.json"), JSON.stringify(devOverride, null, 2));

  // --- Standalone web companion --------------------------------------------
  const companionOut = join(extRoot, "dist", "propstein-web-companion");
  await mkdir(companionOut, { recursive: true });
  await cp(join(apps, "web-companion", "index.html"), join(companionOut, "index.html"));
  await cp(join(out, "panel.js"), join(companionOut, "panel.js"));
  await cp(join(out, "panel.css"), join(companionOut, "panel.css"));

  console.log(`\nBuilt:\n  ${out}\n  ${devOut}\n  ${companionOut}`);
  void devManifest;
}

if (isWatch) {
  const ctx = await context({
    ...common,
    entryPoints: [join(apps, "chrome", "src", "panel-entry.tsx")],
    outfile: join(extRoot, "dist", "propstein-chrome", "panel.js"),
  });
  await ctx.watch();
  console.log("watching…");
} else {
  await buildAll();
}
