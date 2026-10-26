import { chromium } from 'playwright';
const [,, out, legacy, width] = process.argv;
const b = await chromium.launch();
const pg = await b.newPage({viewport:{width:Number(width),height:430}});
await pg.goto('http://127.0.0.1:8899/thesis.html' + (legacy==='1' ? '?legacy=1' : ''));
await pg.waitForTimeout(1200);
await pg.evaluate(()=>{ window.__job={id:'j1',status:'succeeded',phases:[],result:{version:1,status:'insufficient_data'}}; });
const btn = pg.getByRole('button').first();
if (await btn.count()) { await btn.click(); await pg.waitForTimeout(800); }
await pg.screenshot({path:out});
console.log(out, '|', (await pg.evaluate(()=>document.getElementById('root')?.innerText ?? '')).replace(/\n/g,' / '));
await b.close();
