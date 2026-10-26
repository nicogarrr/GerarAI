import { chromium } from 'playwright';
const [,, out, mode] = process.argv;
const b = await chromium.launch();
const pg = await b.newPage({viewport:{width:560,height:520}});
pg.on('pageerror', e => console.log('ERR:', String(e).slice(0,200)));
await pg.goto('http://127.0.0.1:8899/search.html');
await pg.waitForTimeout(1000);
// open the palette (button "Abrir buscador")
const opener = pg.getByRole('button').first();
await opener.click();
await pg.waitForTimeout(600);
await pg.evaluate((m)=>{
  const stocks=[
    {symbol:'SAF.PA',name:'Safran SA',exchange:'Euronext Paris',type:'Common Stock',isInWatchlist:false, fichaCoverage: m==='after'?'unknown':undefined},
    {symbol:'SAN.MC',name:'Banco Santander SA',exchange:'BME',type:'Common Stock',isInWatchlist:false, fichaCoverage: m==='after'?'covered':undefined},
  ];
  window.__searchResult={status:'ok',stocks};
}, mode);
await pg.keyboard.type('sa');
await pg.waitForTimeout(1200);
await pg.screenshot({path:out});
console.log(out, '|', (await pg.evaluate(()=>document.body.innerText.slice(0,300))).replace(/\n/g,' / '));
await b.close();
