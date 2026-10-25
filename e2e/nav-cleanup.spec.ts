import {expect,test} from '@playwright/test';
test.skip(process.env.E2E_UI_RUN!=='1','Local UI required');
const names=['Inicio','Cartera','Research','Descubrir','Watchlist','Biblioteca'];
for(const width of [390,820,1440])test(`six hubs and contextual discovery ${width}`,async({page})=>{
 await page.setViewportSize({width,height:1000});
 await page.goto('/discover');
 await expect(page.getByRole('heading',{name:'Descubrir',exact:true})).toBeVisible();
 await page.addStyleTag({content:'nextjs-portal{display:none!important}'});
 if(width<768){
  await page.getByRole('button',{name:'Abrir menú de navegación'}).click();
  const nav=page.getByRole('dialog',{name:'Menú de navegación'});
  for(const name of names)await expect(nav.getByRole('link',{name,exact:true})).toBeVisible();
  await expect(nav.getByRole('link')).toHaveCount(6);
  await page.screenshot({path:`test-results/nav-six-drawer-${width}.png`});
  await page.keyboard.press('Escape');
 }else{
  const nav=page.getByRole('navigation',{name:'Navegación principal',exact:true});
  await expect(nav.getByRole('link')).toHaveCount(6);
  for(const name of names)await expect(nav.getByRole('link',{name,exact:true})).toBeVisible();
  const expand = page.locator('aside').getByRole('button',{name:'Expandir menú'});
  if(await expand.count())await expand.click();
 }
 await expect(page.getByRole('link',{name:'Alertas',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Menú de usuario'}).click();
 await expect(page.getByRole('menuitem',{name:'Ayuda',exact:true})).toBeVisible();
 await expect(page.getByRole('menuitem',{name:'Seguridad',exact:true})).toBeVisible();
 await page.keyboard.press('Escape');
 await expect(page.getByRole('menu')).toBeHidden();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:`test-results/nav-six-${width}.png`});
});
