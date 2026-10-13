#!/usr/bin/env node
// Screenshot pages of a running app with headless Chromium, as small JPEGs.
// Queues itself through host-check when it exists. Run with --help for usage.

import { spawnSync } from "node:child_process";
import { mkdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import process from "node:process";
import { chromium } from "playwright";

const USAGE = `Usage: shots [options] <url-or-path>...

Writes <out>/<page>-<viewport>.jpg for every page at every viewport and
prints one line per file. Paths resolve against --base-url.

Options:
  --base-url URL         Origin for paths, e.g. https://homes-x.pnav.dev
  --viewport [NAME=]WxH  Repeatable or comma-separated
                         (default: desktop=1440x900,phone=390x844)
  --full                 Capture the whole page, not just the viewport
  --out DIR              Output directory (default: /tmp/shots-<time>)
  --cookie NAME=VALUE    Send a cookie to every page; repeatable
  --signin "COMMAND"     Run COMMAND and use the cookie from its "Cookie:" line,
                         e.g. "homes-preview signin homes-x"
  --wait-for SELECTOR    Wait for this selector before each capture
  --click TEXT           Click the button or link with this text when it shows
                         up (a notice dialog); repeatable, skipped if absent
  --cors URL_GLOB        Add Access-Control-Allow-Origin to these responses,
                         for an origin missing from a CDN's CORS list
  --settle MS            Extra wait after load (default: 800)
  --png                  PNG instead of JPEG
  --timeout MS           Navigation timeout (default: 45000)

WebGL renders through SwiftShader, so maps draw. Exit 1 when a page fails to
load or answers 4xx/5xx; the other captures are still written.`;

const DEFAULT_VIEWPORTS = "desktop=1440x900,phone=390x844";
const REPEATABLE = new Set(["--viewport", "--cookie", "--click", "--cors"]);
const VALUED = new Set([...REPEATABLE, "--base-url", "--out", "--signin", "--wait-for", "--settle", "--timeout"]);
const FLAGS = new Set(["--full", "--png", "--help"]);
const CHROMIUM_ARGS = ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--hide-scrollbars"];

function queueThroughHostCheck() {
  if (process.env.HOST_CHECK_ACTIVE === "1" || process.argv.includes("--help")) return;
  const hostCheck = join(process.env.HOME ?? "", ".local/bin/host-check");
  try {
    statSync(hostCheck);
  } catch {
    return;
  }
  const run = spawnSync(hostCheck, process.argv.slice(1), { stdio: "inherit", env: { ...process.env, HOST_CHECK_CLASS: "light" } });
  process.exit(run.status ?? 1);
}

function readOption(options, name, value) {
  if (!VALUED.has(name)) throw new Error(`unknown option ${name}`);
  if (value === undefined) throw new Error(`${name} needs a value`);
  if (REPEATABLE.has(name)) options[name] = [...(options[name] ?? []), value];
  else options[name] = value;
}

function parseArgs(argv) {
  const options = { pages: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (FLAGS.has(arg)) options[arg] = true;
    else if (arg.startsWith("--")) readOption(options, arg, argv[++i]);
    else options.pages.push(arg);
  }
  return options;
}

function parseViewports(values) {
  return values.flatMap((value) => value.split(",")).map((spec) => {
    const match = /^(?:([\w-]+)=)?(\d+)x(\d+)$/.exec(spec.trim());
    if (!match) throw new Error(`bad viewport "${spec}"; expected [NAME=]WIDTHxHEIGHT`);
    const [, name, width, height] = match;
    return { name: name ?? `${width}x${height}`, width: Number(width), height: Number(height) };
  });
}

function signinCookie(command) {
  const run = spawnSync("bash", ["-c", command], { encoding: "utf8" });
  const line = /^Cookie:\s*(\S+=\S+)/m.exec(run.stdout ?? "");
  if (run.status !== 0 || !line) throw new Error(`--signin printed no "Cookie:" line:\n${run.stderr || run.stdout}`);
  return line[1];
}

function pageUrl(page, baseUrl) {
  if (/^https?:\/\//.test(page)) return page;
  if (!baseUrl) throw new Error(`"${page}" is a path; pass --base-url`);
  return new URL(page, baseUrl).href;
}

function slug(url) {
  const { pathname, search } = new URL(url);
  const text = `${pathname}${search}`.replace(/[^\w.-]+/g, "-").replace(/^-+|-+$/g, "");
  return text || "home";
}

function cookiesFor(options, urls) {
  const pairs = [...(options["--cookie"] ?? []), ...(options["--signin"] ? [signinCookie(options["--signin"])] : [])];
  const origins = [...new Set(urls.map((url) => new URL(url).origin))];
  return pairs.flatMap((pair) => {
    const split = pair.indexOf("=");
    const [name, value] = [pair.slice(0, split), pair.slice(split + 1)];
    return origins.map((url) => ({ name, value, url, secure: url.startsWith("https:"), sameSite: "Lax" }));
  });
}

async function allowCors(context, globs) {
  for (const glob of globs) {
    await context.route(glob, async (route) => {
      const response = await route.fetch();
      await route.fulfill({ response, headers: { ...response.headers(), "access-control-allow-origin": "*" } });
    });
  }
}

async function clickIfShown(page, text) {
  const target = page.getByRole("button", { name: text }).or(page.getByRole("link", { name: text })).first();
  try {
    await target.click({ timeout: 3000 });
  } catch {
    // Absent: nothing to dismiss.
  }
}

async function capture(context, url, viewport, options) {
  const page = await context.newPage();
  const timeout = Number(options["--timeout"] ?? 45000);
  try {
    const response = await page.goto(url, { waitUntil: "load", timeout });
    await page.waitForLoadState("networkidle", { timeout: 5000 }).catch(() => {});
    for (const text of options["--click"] ?? []) await clickIfShown(page, text);
    if (options["--wait-for"]) await page.waitForSelector(options["--wait-for"], { timeout });
    await page.waitForTimeout(Number(options["--settle"] ?? 800));
    const type = options["--png"] ? "png" : "jpeg";
    const path = join(options.outDir, `${slug(url)}-${viewport.name}.${type === "png" ? "png" : "jpg"}`);
    await page.screenshot({ path, type, quality: type === "jpeg" ? 75 : undefined, fullPage: Boolean(options["--full"]) });
    return { path, status: response?.status() ?? 0, landed: page.url() };
  } finally {
    await page.close();
  }
}

async function shootViewport(browser, urls, viewport, options) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  await context.addCookies(options.cookies);
  await allowCors(context, options["--cors"] ?? []);
  let failed = false;
  for (const url of urls) {
    try {
      const { path, status, landed } = await capture(context, url, viewport, options);
      failed ||= status >= 400;
      const redirect = landed === url ? "" : ` [redirected to ${landed}]`;
      console.log(`${status} ${viewport.name} ${url}${redirect} -> ${path} (${Math.round(statSync(path).size / 1024)} KB)`);
    } catch (error) {
      failed = true;
      console.log(`FAIL ${viewport.name} ${url}: ${error.message.split("\n")[0]}`);
    }
  }
  await context.close();
  return failed;
}

async function main() {
  queueThroughHostCheck();
  const options = parseArgs(process.argv.slice(2));
  if (options["--help"] || options.pages.length === 0) {
    console.log(USAGE);
    return options["--help"] ? 0 : 2;
  }
  const urls = options.pages.map((page) => pageUrl(page, options["--base-url"]));
  const viewports = parseViewports(options["--viewport"] ?? [DEFAULT_VIEWPORTS]);
  options.cookies = cookiesFor(options, urls);
  options.outDir = resolve(options["--out"] ?? `/tmp/shots-${new Date().toISOString().replace(/\D/g, "").slice(0, 14)}`);
  mkdirSync(options.outDir, { recursive: true });
  const browser = await chromium.launch({ args: CHROMIUM_ARGS });
  let failed = false;
  for (const viewport of viewports) failed = (await shootViewport(browser, urls, viewport, options)) || failed;
  await browser.close();
  return failed ? 1 : 0;
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(`shots: ${error.message}`);
    process.exit(2);
  },
);
