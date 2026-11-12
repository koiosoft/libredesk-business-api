// Thin send/read bridge for human-in-the-loop (the agent decides each turn).
//
//   node scripts/livechat/turn.mjs open                 # opens chat, prints transcript
//   node scripts/livechat/turn.mjs send "texto"         # sends as customer, waits reply
//   node scripts/livechat/turn.mjs read                 # just print current transcript
//
// Keeps one browser alive between calls via a persistent context + state file.
import { chromium } from 'playwright';
import fs from 'node:fs';

const PORT = process.env.PORT || 8790;
const STATE = '/tmp/livechat-turn/state.json';
const MODE = process.argv[2] || 'read';
// 'handoff' mode: PUT .../assignee/user/remove with the AGENT's own api key, so
// LibreDesk records actor = assistant user and emits conversation.unassigned
// exactly like a real no-answer handoff. Credentials come from env.
if (MODE === 'handoff') {
  const conv = process.env.CONV_UUID;
  if (!conv) { console.error('CONV_UUID required'); process.exit(1); }
  const auth = Buffer.from(`${process.env.HUB_LIBREDESK_API_KEY}:${process.env.HUB_LIBREDESK_API_SECRET}`).toString('base64');
  const res = await fetch(`http://localhost:8090/api/v1/conversations/${conv}/assignee/user/remove`, {
    method: 'PUT', headers: { Authorization: `Basic ${auth}` },
  });
  console.log('handoff HTTP', res.status, (await res.text()).slice(0, 120));
  process.exit(0);
}
const TEXT = process.argv[3] || '';

const browser = await chromium.launch({ headless: true });
const ctx = await browser.newContext();
const page = await ctx.newPage();

if (MODE === 'send' && fs.existsSync(STATE)) {
  await page.goto(JSON.parse(fs.readFileSync(STATE)).url);
} else {
  await page.goto(`http://localhost:${PORT}/`, { waitUntil: 'networkidle' });
}
await page.waitForTimeout(1500);

// Open the widget if collapsed.
const launcher = page.locator('button[aria-label="Open chat"]');
if (await launcher.count()) { try { await launcher.click({ timeout: 3000 }); } catch {} }
await page.waitForTimeout(1200);

const frameEl = await page.locator('iframe').first().elementHandle();
const frame = await frameEl.contentFrame();
const start = frame.getByText(/start conversation/i).first();
if (await start.count()) { try { await start.click({ timeout: 3000 }); await page.waitForTimeout(1000); } catch {} }

async function transcript() {
  const raw = await frame.locator('body').innerText();
  return raw.split('\n').map(l => l.trim()).filter(Boolean).join('\n');
}

if (MODE === 'send') {
  const before = (await transcript()).length;
  const nameBox = frame.locator('input[type=text]').first();
  if (await nameBox.count()) { try { await nameBox.fill('Cliente Prueba', { timeout: 2000 }); } catch {} }
  const input = frame.locator('textarea, [contenteditable=true], input[type=text]').last();
  await input.waitFor({ timeout: 8000 });
  await input.click();
  await input.fill(TEXT);
  await input.press('Enter');
  console.log(`ENVIADO: ${TEXT}\n`);
  // Wait until the transcript grows (agent or hub-api correction).
  const deadline = Date.now() + Number(process.env.WAIT || 150) * 1000;
  let grew = false;
  while (Date.now() < deadline) {
    await page.waitForTimeout(4000);
    if ((await transcript()).length > before + 60) { grew = true; break; }
  }
  if (!grew) console.log('(sin respuesta nueva en la ventana)\n');
}

fs.writeFileSync(STATE, JSON.stringify({ url: page.url(), at: new Date().toISOString() }));
console.log(await transcript());
await browser.close();
