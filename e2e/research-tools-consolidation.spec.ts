import {expect,test} from "@playwright/test";
test.skip(process.env.E2E_UI_RUN!=="1","Local UI required");
for(const width of [390,820,1440]) test(`research tools stay contextual ${width}`,async({page})=>{
 await page.setViewportSize({width,height:1000});
 await page.goto("/research");
 const nav=page.getByRole("navigation",{name:"Herramientas de la sección"});
 // El subnav es plegable (1e172eb9): cerrado por defecto, se abre con su boton.
 await page.locator('button[aria-controls="subnav-seccion-lista"]').click();
 await expect(nav).toBeVisible();
 // "Asistente" salió del subnav en 317c5b3 (unificado en el Cerebro).
 for(const name of ["Empresas","Noticias","Fuentes"])
  await expect(nav.getByRole("link",{name,exact:true})).toBeVisible();
 await expect(page.getByRole("heading",{name:"Herramientas de research",exact:true})).toHaveCount(0);
 await expect(page.getByRole("heading",{name:"Contexto de cartera",exact:true})).toHaveCount(0);
 await page.addStyleTag({content:'nextjs-portal{display:none!important}'});
 await page.screenshot({path:`test-results/research-tools-${width}.png`});
 console.log('GEOMETRY',width,await page.evaluate(()=>({vw:innerWidth,sw:document.documentElement.scrollWidth,offenders:[...document.querySelectorAll('main *')].map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right})).filter(e=>e.right>innerWidth)})));
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:`test-results/research-tools-${width}.png`});
 await expect(page.getByRole("heading",{name:"Herramientas de research",exact:true})).toHaveCount(0);
});
