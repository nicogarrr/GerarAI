import { chromium } from 'playwright';
const base = 'http://localhost:3000/research/UBER/management-credibility';
const out = '/home/sandbox/qa-sweep/shots2';
const banner = async (page) => {
  await page.addStyleTag({ content: 'nextjs-portal{display:none!important}' });
  await page.evaluate(() => {
    const d = document.createElement('div');
    d.textContent = 'Vista de prueba · datos ficticios';
    d.style.cssText = 'position:sticky;top:0;z-index:60;background:#451a03;color:#fcd34d;font-size:12px;padding:6px 12px;text-align:center;border-bottom:1px solid #92400e';
    document.body.prepend(d);
  });
};
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 390, height: 850 } });
await page.goto(base, { waitUntil: 'networkidle' });
await banner(page);
// DESPUÉS sección: mismo ancla DOM que antes
await page.evaluate(() => {
  const h = [...document.querySelectorAll('h2')].find((x) => x.textContent.includes('Registrar una promesa'));
  const y = h.getBoundingClientRect().top + window.scrollY - 260;
  window.scrollTo(0, y);
});
await new Promise((r) => setTimeout(r, 400));
await page.screenshot({ path: `${out}/CAND3_despues_seccion_390.png` });
// Candidato: ancla en la cita, incluye contexto + inicio review form
await page.evaluate(() => {
  const h = [...document.querySelectorAll('h2')].find((x) => x.textContent.includes('seven cities'));
  const y = h.getBoundingClientRect().top + window.scrollY - 70;
  window.scrollTo(0, y);
});
await new Promise((r) => setTimeout(r, 400));
await page.screenshot({ path: `${out}/CAND3_candidato_390.png` });
console.log('despues+candidato ok');
await page.close();
await browser.close();
