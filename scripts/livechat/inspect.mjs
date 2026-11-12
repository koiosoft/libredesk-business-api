import { chromium } from 'playwright';
const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
await page.goto(`http://localhost:${process.env.PORT || 8790}/`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

console.log('=== DOM de la pagina (lo que el widget monto) ===');
const html = await page.evaluate(() => document.body.innerHTML);
console.log(html.slice(0, 1800));

// Contenido del iframe (aunque este oculto).
const frameEl = await page.$('iframe');
if (frameEl) {
  const fr = await frameEl.contentFrame();
  const inner = await fr.evaluate(() => document.body ? document.body.innerText.slice(0, 600) : '(vacio)');
  console.log('=== texto dentro del iframe ===');
  console.log(inner);
}
await browser.close();
