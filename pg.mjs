import { chromium } from '@playwright/test';
const b = await chromium.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] });
const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const p = await ctx.newPage();
for (const [n,u] of [['p1','/temas'],['p2','/temas?pagina=2'],['plast','/temas?pagina=999'],['p2_1m','/temas?orden=1m&pagina=2'],['pbad','/temas?pagina=abc']]) {
  await p.goto('http://127.0.0.1:3100'+u,{waitUntil:'networkidle',timeout:45000}).catch(()=>{});
  const info = await p.evaluate(()=>({cards:document.querySelectorAll('main > ul > li').length, nav:document.querySelector('nav[aria-label="Paginación de temas"]')?.innerText.replace(/\n+/g,' | '), names:[...document.querySelectorAll('main > ul > li h2')].map(h=>h.innerText)}));
  console.log(n,u,JSON.stringify(info));
  await p.evaluate(()=>document.querySelector('nav[aria-label="Paginación de temas"]')?.scrollIntoView({block:'center'}));
  await p.waitForTimeout(300);
  await p.screenshot({path:`/downloads/tour/pg_${n}.png`});
}
// click Siguiente from p1
await p.goto('http://127.0.0.1:3100/temas',{waitUntil:'networkidle'}).catch(()=>{});
await p.getByRole('link',{name:'Siguiente'}).click(); await p.waitForURL(/pagina=2/,{timeout:15000}).catch(()=>{});
console.log('after click', p.url());
await b.close();
