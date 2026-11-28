// Screenshot pages of the running dev app (./dev.sh) with a headless browser.
//
//   node web/scripts/shot.mjs /                     # jobs list, English, desktop
//   node web/scripts/shot.mjs /new --lang ar        # Arabic (RTL)
//   node web/scripts/shot.mjs / /new --mobile       # several pages, phone width
//   node web/scripts/shot.mjs /login                # the login page (not signed in)
//
// Signs in as CERTIFLOW_DEV_USER / CERTIFLOW_DEV_PASSWORD (from .env.dev).
// Saves PNGs to out/shots/ and prints their paths, plus any browser console errors.
import { chromium } from "@playwright/test";
import { mkdirSync, readFileSync, existsSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const envFile = resolve(root, ".env.dev");
if (existsSync(envFile)) {
  for (const line of readFileSync(envFile, "utf8").split("\n")) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2];
  }
}

const args = process.argv.slice(2);
const flag = (name) => args.includes(name);
const opt = (name, def) => { const i = args.indexOf(name); return i >= 0 ? args[i + 1] : def; };
const optValues = new Set(["--lang", "--base", "--width", "--height"].flatMap((n) => { const i = args.indexOf(n); return i >= 0 ? [i + 1] : []; }));
const paths = args.filter((a, i) => !a.startsWith("--") && !optValues.has(i));
if (!paths.length) paths.push("/");

const base = opt("--base", "http://localhost:5173");
const lang = opt("--lang", "en");
const mobile = flag("--mobile");
const dark = flag("--dark");   // the UI follows the system theme unless the user picked one
const viewport = { width: Number(opt("--width", mobile ? 390 : 1440)), height: Number(opt("--height", mobile ? 844 : 900)) };
const user = process.env.CERTIFLOW_DEV_USER, password = process.env.CERTIFLOW_DEV_PASSWORD;

const outDir = resolve(root, "out/shots");
mkdirSync(outDir, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport, deviceScaleFactor: mobile ? 2 : 1, colorScheme: dark ? "dark" : "light" });
const page = await ctx.newPage();
const errors = [];
page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
page.on("pageerror", (e) => errors.push(String(e)));

const signIn = !paths.every((p) => p === "/login");
if (signIn) {
  if (!user || !password) throw new Error("set CERTIFLOW_DEV_USER and CERTIFLOW_DEV_PASSWORD in .env.dev");
  const h = { "X-CertiFlow": "1" };
  const r = await ctx.request.post(`${base}/api/auth/login`, { headers: h, data: { username: user, password } });
  if (!r.ok()) throw new Error(`login failed: ${r.status()} ${await r.text()}`);
  await ctx.request.post(`${base}/api/me/prefs`, { headers: h, data: { ui_language: lang } });
}
await ctx.addInitScript((l) => { try { localStorage.setItem("cf_lang", l); } catch {} }, lang);

for (const p of paths) {
  const url = base + (p === "/login" ? "/" : p);
  // Pages with a live (SSE) connection never go network-idle: fall back to "loaded + a short wait".
  try { await page.goto(url, { waitUntil: "networkidle", timeout: 8000 }); await page.waitForTimeout(400); }
  catch { await page.waitForLoadState("load"); await page.waitForTimeout(2000); }
  const name = `${(p.replace(/[^a-z0-9]+/gi, "_").replace(/^_|_$/g, "") || "home")}.${lang}${mobile ? ".mobile" : ""}${dark ? ".dark" : ""}.png`;
  const file = resolve(outDir, name);
  await page.screenshot({ path: file, fullPage: true });
  console.log(file);
}
if (errors.length) console.log("BROWSER ERRORS:\n" + errors.join("\n"));
await browser.close();
