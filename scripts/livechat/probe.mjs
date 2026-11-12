// Prueba end-to-end por LiveChat: cliente escribe, Agente IA responde,
// hub-api evalua (y corrige si JEV lo pide). Todo via el widget real.
import { chromium } from 'playwright';

const PORT = process.env.PORT || 8790;
const TEXT = process.argv[2] || 'Hola, necesito ayuda urgente: mi sistema productivo esta caido desde hace dos horas y estamos perdiendo ventas.';
const WAIT_AGENT = Number(process.env.WAIT_AGENT || 45); // segundos para la primera respuesta del agente

const browser = await chromium.launch({ headless: true });

// --- Modo guion: conversacion completa de 6 turnos (academia de futbol) ------
if (process.env.SCRIPT === "guion") {
  const TURNS = JSON.parse(process.env.TURNS_JSON || '[]');
  const page = await browser.newPage();
  await page.goto(`http://localhost:${PORT}/`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(2000);
  await page.locator('button[aria-label="Open chat"]').click();
  await page.waitForTimeout(1500);
  const frame = await page.locator('iframe').first().contentFrame();
  const start = frame.getByText(/start conversation/i).first();
  if (await start.count()) { await start.click(); await page.waitForTimeout(1200); }
  const nameBox = frame.locator('input[type=text]').first();
  if (await nameBox.count()) { await nameBox.fill('Cliente Guion'); }

  for (let i = 0; i < TURNS.length; i++) {
    const input = frame.locator('textarea, [contenteditable=true], input[type=text]').last();
    await input.waitFor({ timeout: 10000 });
    await input.click();
    await input.fill(TURNS[i]);
    await input.press('Enter');
    console.log(`\n=== turno ${i + 1} enviado (${TURNS[i].slice(0, 40)}...) ===`);
    // Esperar SIEMPRE la respuesta del agente antes de atacar el siguiente turno:
    // el transcript crece con texto nuevo que no sea el propio mensaje enviado.
    const before = (await frame.locator('body').innerText()).length;
    const deadline = Date.now() + Number(process.env.PER_TURN_WAIT || 90) * 1000;
    let answered = false;
    while (Date.now() < deadline) {
      await page.waitForTimeout(4000);
      const t = await frame.locator('body').innerText();
      if (t.length > before + 60) { answered = true; break; }
    }
    console.log(answered ? '(respuesta recibida)' : '(SIN RESPUESTA en el ventana)');
    // Pausa extra para que hub-api termine su ciclo (webhook->JEV->copilot->publicar)
    // sin que nuestro siguiente ataque caiga a mitad.
    await page.waitForTimeout(Number(process.env.POST_ANSWER_DELAY || 15) * 1000);
    const t = await frame.locator('body').innerText();
    console.log(t.slice(-1400));
  }
  console.log('\n=== TRANSCRIPT FINAL ===');
  console.log(await frame.locator('body').innerText());
  await browser.close();
  process.exit(0);
}
const page = await browser.newPage();
await page.goto(`http://localhost:${PORT}/`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);

// 1) Abrir el launcher ("Open chat").
await page.locator('button[aria-label="Open chat"]').click();
await page.waitForTimeout(1500);
const frame = await page.locator('iframe').first().contentFrame();

// 2) Start conversation -> nombre -> mensaje.
const start = frame.getByText(/start conversation/i).first();
if (await start.count()) { await start.click(); await page.waitForTimeout(1200); }

const nameBox = frame.locator('input[type=text]').first();
if (await nameBox.count()) { await nameBox.fill('Cliente de Prueba'); }

const input = frame.locator('textarea, [contenteditable=true], input[type=text]').last();
await input.waitFor({ timeout: 10000 });
await input.click();
await input.fill(TEXT);
await input.press('Enter');
console.log('cliente dijo:', TEXT.slice(0, 60) + '...');

// 3) Esperar la(s) respuesta(s): agente IA y correccion de hub-api.
const deadline = Date.now() + WAIT_AGENT * 1000;
let last = '';
while (Date.now() < deadline) {
  await page.waitForTimeout(4000);
  last = await frame.locator('body').innerText();
  const turns = last.split('\n').map(l => l.trim()).filter(Boolean);
  if (turns.length >= 5) break; // saludo + nuestro msg + al menos una respuesta
}
console.log('=== transcript final del iframe ===');
console.log(last.slice(-2200));
await browser.close();
