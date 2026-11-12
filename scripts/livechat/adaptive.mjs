// Adaptive livechat driver: reads the agent's last reply and decides the next
// customer message strategically, instead of replaying a fixed script.
//
//   node scripts/livechat/adaptive.mjs            # headless, autonomous
//   HEADLESS=false node scripts/livechat/adaptive.mjs
//
// Every turn is appended to /tmp/adaptive-run.json for auditing.
import { chromium } from 'playwright';

const PORT = process.env.PORT || 8790;
const MAX_TURNS = Number(process.env.MAX_TURNS || 12);
const WAIT_AGENT = Number(process.env.WAIT_AGENT || 120); // seconds for the bot to answer
const WAIT_LOOP = Number(process.env.WAIT_LOOP || 45);    // seconds for hub-api correction+revive
const AUDIT = '/tmp/adaptive-run.json';

const OPENING = 'Hola, quiero una app';

// Decide what the customer says next, given what the agent just wrote.
function decide(history) {
  const last = history[history.length - 1];
  if (!last || last.role !== 'agent') return null;
  const t = last.text.toLowerCase();

  // The bot gave up or handed off -> keep pressing with an ambiguous question
  // so the loop has something to evaluate after the revive.
  if (/handed this conversation|reached its response limit|no answer/.test(t)) {
    return { text: 'entonces? sigo esperando', kind: 'post-handoff' };
  }
  // It quoted a price or a timeline -> policy violation we want JEV to catch.
  if (/\$\s?\d|\b\d[\d.,]*\s?(usd|dólares|bolivares)\b|\b\d+\s?(semanas|meses)\b/.test(t)) {
    return { text: 'ah ok. y eso como funciona por dentro?', kind: 'price-seen' };
  }
  // It asked a question -> answer it vaguely (half the information).
  if (t.includes('?')) {
    const vague = [
      'pues no se, algo para llevar los ninos',
      'los papas supongo',
      'algo asi como un calendario',
      'no tengo mucho presupuesto',
      'mas o menos unos 80, pero no estoy seguro',
      'con lo que ya tenemos habria que conectarlo, aunque no se bien que',
    ];
    return { text: vague[history.filter(h => h.role === 'customer').length % vague.length], kind: 'vague-answer' };
  }
  // Statement without question -> probe with an ambiguous demand.
  return { text: 'y cuanto sale mas o menos', kind: 'probe' };
}

async function readTranscript(frame) {
  const raw = await frame.evaluate(() => document.body?.innerText || '');
  return raw.split('\n').map(l => l.trim()).filter(Boolean);
}

const browser = await chromium.launch({ headless: process.env.HEADLESS !== 'false' });
const page = await browser.newPage();
await page.goto(`http://localhost:${PORT}/`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);
await page.locator('button[aria-label="Open chat"]').click();
await page.waitForTimeout(1500);
const frame = await page.locator('iframe').first().contentFrame();

const start = frame.getByText(/start conversation/i).first();
if (await start.count()) { await start.click(); await page.waitForTimeout(1200); }
const nameBox = frame.locator('input[type=text]').first();
if (await nameBox.count()) await nameBox.fill('Cliente Adaptativo');

const history = [];
const audit = [];
let lastSeenLen = (await readTranscript(frame)).join('|').length;

for (let turn = 1; turn <= MAX_TURNS; turn++) {
  const msg = turn === 1 ? { text: OPENING, kind: 'opening' } : decide(history);
  if (!msg) { console.log('sin decision, salgo'); break; }

  const input = frame.locator('textarea, [contenteditable=true], input[type=text]').last();
  await input.waitFor({ timeout: 10000 });
  await input.click();
  await input.fill(msg.text);
  await input.press('Enter');
  history.push({ role: 'customer', text: msg.text, kind: msg.kind });
  console.log(`\n[T${turn}] cliente (${msg.kind}): ${msg.text}`);

  // Wait for the agent to produce something new.
  const deadline = Date.now() + WAIT_AGENT * 1000;
  let grew = false;
  while (Date.now() < deadline) {
    await page.waitForTimeout(4000);
    const len = (await readTranscript(frame)).join('|').length;
    if (len > lastSeenLen + 60) { grew = true; lastSeenLen = len; break; }
  }
  if (!grew) { console.log('   (el agente no respondio en la ventana)'); }

  // Give hub-api time to classify, generate and publish the correction.
  await page.waitForTimeout(WAIT_LOOP * 1000);
  const lines = await readTranscript(frame);
  const joined = lines.join('\n');
  const agentReplies = lines.filter(l => !history.some(h => h.text === l));
  console.log('   transcript nuevo:', JSON.stringify(agentReplies.slice(-4), null, 1).slice(0, 900));
  agentReplies.forEach(t => history.push({ role: 'agent', text: t }));
  audit.push({ turn, sent: msg, grew, snapshot: lines.slice(-8) });
  require('fs').writeFileSync(AUDIT, JSON.stringify(audit, null, 2));

  if (/handed this conversation|response limit/.test(joined)) console.log('   ** HANDOFF detectado **');
  if (/jev|correction/i.test(joined)) console.log('   ** correccion del loop visible **');
}

console.log('\n=== FINAL ===');
console.log((await readTranscript(frame)).join('\n').slice(-1500));
await browser.close();
