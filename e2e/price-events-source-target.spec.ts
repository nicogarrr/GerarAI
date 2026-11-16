import {expect,test} from '@playwright/test';
// Applies when the production chart has a sourced stored event. Fixture SSR
// measurement accompanying this PR covers the always-present synthetic SEC link.
test('source links offer mobile tap targets',async({page})=>{
 await page.setViewportSize({width:390,height:844});
 await page.goto('/research/AAPL');
 const list=page.getByTestId('price-events-list');
 const links=list.getByRole('link');
 test.skip(await links.count()===0,'No sourced stored events in this environment');
 for(const link of await links.all()){
  const box=await link.boundingBox();expect(box).not.toBeNull();
  expect(box!.width).toBeGreaterThanOrEqual(24);expect(box!.height).toBeGreaterThanOrEqual(24);
 }
});
