// Browser tests for index.html.
// Setup:  npm install playwright && npx playwright install chromium
// Run:    node tests/e2e.js
const assert = require('assert');
const path = require('path');
const { chromium } = require('playwright');

const PAGE = 'file://' + path.resolve(__dirname, '..', 'index.html');

function repo(n, s, extra) {
  return Object.assign({ n: 'o/' + n, d: n + ' does things', l: 'Python', s: s, f: 2,
    c: '2026-10-01', u: '2026-11-03', t: ['topic-' + n] }, extra || {});
}

// Fixture with momentum numbers. "generated" is 4 Nov, so "fresh" counts as new.
function withMomentum() {
  const hot = repo('hot', 900, { c: '2026-11-04', g1: 500 });
  const quiet = repo('quiet', 1200, { c: '2026-11-04', g1: 3 });
  const fresh = repo('fresh', 10, { c: '2026-11-04' });
  const steady = repo('steady', 5000, { g1: 0, g7: 40 });
  const py = repo('py', 300);
  return {
    generated: '2026-11-04', at: '2026-11-04T03:17:00Z',
    lanes: [
      { id: 'today', name: 'Today', hint: 'Repos created in the last 24 hours, most starred first.',
        matches: 77, repos: [quiet, hot, fresh] },
      { id: 'week', name: 'This week', hint: 'Repos created in the last 7 days.',
        matches: 500, repos: [steady, hot] },
      { id: 'python', name: 'Python', hint: 'Python repos.', matches: 9, repos: [py] },
    ],
  };
}

// First day of data: nothing has a gain yet.
function withoutMomentum() {
  const d = withMomentum();
  d.lanes.forEach(l => l.repos.forEach(r => { delete r.g1; delete r.g7; }));
  return d;
}

async function openWith(browser, data, viewport) {
  const ctx = await browser.newContext({ viewport: viewport || { width: 1280, height: 900 } });
  const page = await ctx.newPage();
  const problems = [];
  page.on('pageerror', e => problems.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() === 'error' && !/fonts|net::|Failed to load resource/.test(m.text())) problems.push(m.text());
  });
  if (data) {
    await page.route('**/data.js', route => route.fulfill({
      contentType: 'application/javascript',
      body: 'window.GITTUBE = ' + JSON.stringify(data) + ';',
    }));
  }
  await page.goto(PAGE);
  await page.waitForSelector('.card');
  return { ctx, page, problems };
}

const names = page => page.locator('.card .nm').allInnerTexts();
const chipTexts = page => page.locator('.chip').allInnerTexts().then(a => a.map(t => t.replace(/\s+/g, ' ').trim()));

const tests = [];
const test = (name, fn) => tests.push([name, fn]);

test('lanes appear in order, Today first, with counts', async b => {
  const { ctx, page, problems } = await openWith(b, withMomentum());
  assert.deepStrictEqual(await chipTexts(page),
    ['All lanes 5', 'Today 3', 'This week 2', 'Python 1']);
  assert.deepStrictEqual(problems, []);
  await ctx.close();
});

test('header shows the refresh date and time', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  assert.strictEqual(await page.locator('#stamp').innerText(), 'data from 4 Nov 2026, 03:17 UTC');
  await ctx.close();
});

test('Today lane lists its repos and explains itself', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  await page.locator('.chip', { hasText: 'Today' }).click();
  assert.deepStrictEqual((await names(page)).sort(), ['fresh', 'hot', 'quiet']);
  assert.match(await page.locator('#how').innerText(), /created in the last 24 hours/);
  assert.match(await page.locator('#how').innerText(), /77 repos match/);
  await ctx.close();
});

test('default order is most stars, with duplicates removed in All lanes', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  assert.deepStrictEqual(await names(page), ['steady', 'quiet', 'hot', 'py', 'fresh']);
  await ctx.close();
});

test('momentum badges: today, this week, and NEW', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  const badgesOf = async n => (await page.locator('.card', { has: page.locator('.nm', { hasText: new RegExp('^' + n + '$') }) })
    .locator('.bd').allInnerTexts());
  assert.ok((await badgesOf('hot')).includes('▲ +500 today'));
  assert.ok((await badgesOf('quiet')).includes('▲ +3 today'));
  const steady = await badgesOf('steady');
  assert.ok(steady.includes('▲ +40 this week'));
  assert.ok(!steady.some(t => /today/.test(t)), 'a gain of 0 shows no "today" badge');
  assert.ok((await badgesOf('fresh')).includes('NEW'));
  assert.ok(!(await badgesOf('py')).some(t => /NEW|▲/.test(t)), 'old repo without data has no momentum badge');
  assert.ok(!(await badgesOf('hot')).includes('NEW'), 'NEW is hidden when a gain is shown');
  await ctx.close();
});

test('sorting by gain puts the biggest gain first and repos without data last', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  await page.selectOption('#sort', 'gain');
  assert.deepStrictEqual(await names(page), ['hot', 'quiet', 'steady', 'py', 'fresh']);
  await ctx.close();
});

test('the gain sort is switched off until there is data', async b => {
  const { ctx, page } = await openWith(b, withoutMomentum());
  const opt = page.locator('#sort option[value="gain"]');
  assert.strictEqual(await opt.isDisabled(), true);
  assert.match(await opt.innerText(), /after 2 daily refreshes/);
  assert.strictEqual(await page.locator('.bd.up').count(), 0);
  await ctx.close();
});

test('the gain sort is available when data exists', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  assert.strictEqual(await page.locator('#sort option[value="gain"]').isDisabled(), false);
  await ctx.close();
});

test('search still filters', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  await page.fill('#q', 'steady');
  assert.deepStrictEqual(await names(page), ['steady']);
  await page.fill('#q', 'nothing-matches-this');
  assert.strictEqual(await page.locator('.card').count(), 0);
  assert.match(await page.locator('.empty').innerText(), /No repos match/);
  await ctx.close();
});

test('every card links to the real GitHub repo', async b => {
  const { ctx, page } = await openWith(b, withMomentum());
  const hrefs = await page.locator('a.go').evaluateAll(a => a.map(x => x.href).sort());
  assert.deepStrictEqual(hrefs, ['https://github.com/o/fresh', 'https://github.com/o/hot',
    'https://github.com/o/py', 'https://github.com/o/quiet', 'https://github.com/o/steady']);
  await ctx.close();
});

test('old data files without time or history still render', async b => {
  const d = withoutMomentum();
  delete d.at;
  const { ctx, page, problems } = await openWith(b, d);
  assert.strictEqual(await page.locator('#stamp').innerText(), 'data from 4 Nov 2026');
  assert.deepStrictEqual(problems, []);
  await ctx.close();
});

test('the real data.js loads without errors', async b => {
  const { ctx, page, problems } = await openWith(b, null);
  assert.ok(await page.locator('.card').count() > 10);
  assert.deepStrictEqual(problems, []);
  await ctx.close();
});

test('no sideways scrolling at phone width, with badges', async b => {
  const { ctx, page } = await openWith(b, withMomentum(), { width: 400, height: 800 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  assert.strictEqual(overflow, false);
  await ctx.close();
});

(async () => {
  const browser = await chromium.launch();
  let failed = 0;
  for (const [name, fn] of tests) {
    try { await fn(browser); console.log('ok    ' + name); }
    catch (e) { failed++; console.log('FAIL  ' + name + '\n      ' + String(e.message).split('\n').join('\n      ')); }
  }
  await browser.close();
  console.log('\n' + (tests.length - failed) + ' passed, ' + failed + ' failed');
  process.exit(failed ? 1 : 0);
})();
