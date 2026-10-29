import {expect,test} from "@playwright/test";
test.skip(process.env.E2E_UI_RUN!=="1","Local UI required");
for(const width of [390,820,1440])test(`useful content without filler ${width}`,async({page})=>{
 await page.setViewportSize({width,height:1000});
 for(const route of ["/research","/discover","/screeners","/watchlist","/portfolio"]){
  await page.goto(route);
  // Durante la transición coexisten el <main> saliente y el entrante
  // (aria-busy): esperar a que quede uno antes de asertar (strict mode).
  const main = page.locator("main#content");
  await expect(main).toHaveCount(1);
  await expect(main).toBeVisible();
  await page.addStyleTag({content:"nextjs-portal{display:none!important}"});
  await expect(main).not.toContainText(/Encuentra empresas para estudiar|Construye fórmulas seguras|Seguimiento detallado de valoración|Seguimiento de tus inversiones|Cada ficha agrupa su análisis en seis etapas/);
  if(route==="/portfolio")await expect(main).not.toContainText("Yahoo Finance");
  await page.screenshot({path:`test-results/copy-${route.slice(1)}-${width}.png`});
  console.log('GEOMETRY',route,width,await page.evaluate(()=>({vw:innerWidth,sw:document.documentElement.scrollWidth,offenders:[...document.querySelectorAll('main *')].map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right})).filter(e=>e.right>innerWidth)})));
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.screenshot({path:`test-results/copy-${route.slice(1)}-${width}.png`});
 }
});
