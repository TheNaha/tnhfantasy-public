#!/usr/bin/env node
/**
 * A controllable headless browser for looking at a page, not for asserting on it.
 *
 * The Playwright specs are the right tool for "does this behave correctly", and
 * the full e2e suite (177 tests) is far too slow to run on every change. But
 * most UI defects announce themselves as a fact about the rendered DOM, and
 * getting that fact takes seconds here and minutes through a test runner.
 *
 * It is deliberately a script and not a test: no runner, no fixtures, no
 * retries, no report. You drive it, and it tells you what it saw.
 *
 *   node scripts/page-probe.mjs /gallery
 *   node scripts/page-probe.mjs /gallery --click "Group by session" --wait 2000
 *   node scripts/page-probe.mjs /gallery --testid gallery-filter-panel
 *   node scripts/page-probe.mjs /gallery --screenshot /tmp/shot.png
 *   node scripts/page-probe.mjs /gallery --text "Filters"
 *
 * Options, in any order and repeatable where noted:
 *   --click <name|role>   click the first match (a `role:name` or a `title:` or
 *                         bare accessible-name substring). Repeatable.
 *   --wait <ms>           settle time after each step. Default 1200.
 *   --testid <id>         require this testid to be present; report its text.
 *   --text <substr>       require this text to be present.
 *   --count <selector>    print how many match a CSS selector.
 *   --expand [selector]  click every match of selector (default: every
 *                         collapsed `button[aria-expanded]`). Repeatable.
 *   --screenshot <path>   write a PNG.
 *   --url <base>          where the app lives. Default http://localhost:5174.
 *
 * It is not a replacement for a spec. Anything whose result depends on a fetch
 * that React starts after the network has already gone idle — expanding a
 * session and waiting for its assets, say — is a job for
 * `npx playwright test <spec>`, which waits deterministically. Use this to find
 * out what a page is doing; use a spec to decide whether it is right.
 *
 * Console errors and page errors are always reported, and a non-empty list is
 * the single most useful thing this tool tells you — a blank page with a clean
 * console is a very different bug from a blank page with a stack trace in it.
 */
import { chromium } from '@playwright/test';

const argv = process.argv.slice(2);
const flag = (name, fallback = null) => {
  const i = argv.indexOf(`--${name}`);
  return i === -1 ? fallback : argv[i + 1];
};
const all = (name) => argv.reduce((acc, a, i) => (a === `--${name}` ? [...acc, argv[i + 1]] : acc), []);

const path = argv.find((a) => !a.startsWith('--') && argv[argv.indexOf(a) - 1]?.startsWith('--') !== true) || '/';
const base = flag('url', 'http://localhost:5174');
const wait = Number(flag('wait', 1200));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });

const consoleErrors = [];
const pageErrors = [];
page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });
page.on('pageerror', (e) => pageErrors.push(String(e)));
const apiCalls = [];
page.on('response', (r) => {
  const u = r.url();
  if (u.includes('/api/')) apiCalls.push({ status: r.status(), url: u.replace(base, '') });
});

const report = {};
const problems = [];

try {
  await page.goto(base + path, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(wait);

  if (argv.includes('--expand')) {
    // Scopeable, because "whatever collapsed thing comes first" is not a
    // reliable thing to click: it can be behind a sticky header or outside the
    // virtualizer's mounted range, and the click just times out.
    const collapsed = page.locator(all('expand')[0] || 'button[aria-expanded="false"]');
    const n = await collapsed.count();
    for (let i = 0; i < n; i += 1) {
      // One at a time, settling on the network between each: an expanded panel
      // usually fetches, and a fixed sleep races it. This is the difference
      // between "the panel is empty" and "I looked too early".
      // NOT swallowed. An earlier version of this line was
      // `.click().catch(() => {})`, which made a failing click look exactly
      // like a page that had nothing to expand — the tool reporting "0
      // sections expanded" when in fact it had failed seven times. A diagnostic
      // that hides its own errors is worse than no diagnostic.
      try {
        await collapsed.first().click({ timeout: 5000 });
        report.expandedClicks = (report.expandedClicks || 0) + 1;
      } catch (err) {
        problems.push(`expand click ${i + 1} of ${n} failed: ${err.message.split('\n')[0]}`);
        break;
      }
      await page.waitForLoadState('networkidle', { timeout: 10000 }).catch(() => {});
    }
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    report.expandedCandidates = n;
  }

  for (const target of all('click')) {
    // Resolved in order of reliability: a title attribute, then a button's
    // accessible name, then any visible text. A bare `getByText` alone is the
    // trap here — it happily resolves to a wrapper that swallows the click.
    const candidates = target.startsWith('title:')
      ? [page.locator(`[title*="${target.slice(6)}"]`).first()]
      : [
          page.getByRole('button', { name: target }).first(),
          page.getByRole('link', { name: target }).first(),
          page.locator(`[data-testid="${target}"]`).first(),
          page.getByText(target, { exact: false }).first(),
        ];

    let clicked = false;
    for (const locator of candidates) {
      if (!(await locator.count())) continue;
      await locator.click({ timeout: 5000 }).catch(() => {});
      clicked = true;
      break;
    }
    if (!clicked) {
      problems.push(`could not find anything to click matching "${target}"`);
      break;
    }
    // Same reasoning: a click that navigates or fetches is not done when the
    // timeout expires.
    await page.waitForLoadState('networkidle', { timeout: 15000 }).catch(() => {});
    await page.waitForTimeout(wait);
  }

  for (const id of all('testid')) {
    const el = page.locator(`[data-testid="${id}"]`);
    if (!(await el.count())) {
      problems.push(`no [data-testid="${id}"] on the page`);
      continue;
    }
    report[id] = (await el.first().innerText()).replace(/\s+/g, ' ').trim().slice(0, 200);
  }

  for (const needle of all('text')) {
    if (!(await page.getByText(needle, { exact: false }).count())) {
      problems.push(`no element containing the text "${needle}"`);
    }
  }

  for (const selector of all('count')) {
    report[`count ${selector}`] = await page.locator(selector).count();
  }

  const shot = flag('screenshot');
  if (shot) {
    await page.screenshot({ path: shot, fullPage: false });
    report.screenshot = shot;
  }

  report.bodyChars = (await page.evaluate(() => document.body.innerText)).length;
  report.testids = await page.evaluate(() => (
    [...new Set([...document.querySelectorAll('[data-testid]')].map((e) => e.getAttribute('data-testid')))]
  ));
} catch (err) {
  problems.push(`navigation failed: ${err.message}`);
}

const bad = apiCalls.filter((c) => c.status >= 400);
report.apiErrors = bad;

await browser.close();

console.log(JSON.stringify({ ...report, problems, consoleErrors, pageErrors }, null, 2));
process.exit(problems.length || pageErrors.length ? 1 : 0);
