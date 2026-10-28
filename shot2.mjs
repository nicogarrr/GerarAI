import { chromium } from '@playwright/test';
const b = await chromium.launch({ executablePath: '/usr/bin/google-chrome', args: ['--no-sandbox'] });
const ctx = await b.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const p = await ctx.newPage();
for (const [n,u] of [['cal','/calendar'],['macro','/macro-calendar'],['corp','/corporate-actions'],['port','/portfolio'],['temas','/temas']]) {
  await p.goto('http://127.0.0.1:3100'+u,{waitUntil:'networkidle',timeout:45000}).catch(()=>{});
  await p.waitForTimeout(1500);
  const m = await p.evaluate(()=>({h1:document.querySelector('h1')?.innerText, h1Top:Math.round(document.querySelector('h1')?.getBoundingClientRect().top+scrollY), sectionBtn:!!document.querySelector('#subnav-seccion-lista'), navs:[...document.querySelectorAll('nav')].map(n=>n.getAttribute('aria-label'))}));
  console.log(n,JSON.stringify(m));
  await p.screenshot({path:`/downloads/tour/final_${n}.png`});
}
await b.close();
