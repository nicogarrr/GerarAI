import { expect, test } from '@playwright/test';

test.describe('landing: tipografía y header compacto', () => {
  test.skip(process.env.E2E_UI_RUN !== '1', 'Necesita frontend E2E');
  for (const width of [320, 360, 390, 400, 500, 639, 640, 767, 768, 1280]) {
    test(`header en una fila sin desbordes a ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await page.goto('/');
      await page.evaluate(() => document.fonts.ready);
      // Titular estilo Kymatio (#rediseño 31-oct-2026, pedido de Nico): el h1
      // va en la sans pública y solo la palabra destacada conserva la serif
      // editorial en cursiva. El contrato de la serif no desaparece: se exige
      // en el span del destacado.
      await expect(page.locator('h1')).toHaveCSS('font-family', /publicsans/i);
      const highlight = page.locator('h1 span').first();
      await expect(highlight).toHaveCSS('font-family', /editorial/i);
      await expect(highlight).toHaveCSS('font-style', 'italic');
      const loadedFamilies = await page.evaluate(() => {
        const normalize = (family: string) => family.replace(/["']/g, '').trim();
        return [document.querySelector('.public-shell')!, document.querySelector('h1')!, document.querySelector('h1 span')!].map((element) => {
          const family = normalize(getComputedStyle(element).fontFamily.split(',')[0]);
          const faces = [...document.fonts].filter((face) => normalize(face.family) === family);
          return { family, statuses: faces.map((face) => face.status) };
        });
      });
      for (const { family, statuses } of loadedFamilies) {
        expect(statuses.length, `FontFace registrada para ${family}`).toBeGreaterThan(0);
        expect(statuses, `FontFace cargada para ${family}`).toContain('loaded');
      }
      const header = page.locator('.public-header-inner');
      await expect(header).toBeVisible();
      const geometry = await header.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        const boxes = [...element.children]
          .filter((child) => child.getClientRects().length > 0 && getComputedStyle(child).display !== 'none')
          .map((child) => child.getBoundingClientRect());
        return {
          height: bounds.height,
          fits: boxes.every((box) => box.left >= bounds.left && box.right <= bounds.right),
          overlap: boxes.some((box, index) => index > 0 && box.left < boxes[index - 1].right - 1),
          overflow: document.documentElement.scrollWidth > innerWidth,
          font: getComputedStyle(element).fontFamily,
        };
      });
      expect(geometry.height).toBe(56);
      expect(geometry.fits).toBe(true);
      expect(geometry.overlap).toBe(false);
      expect(geometry.overflow).toBe(false);
      expect(geometry.font.toLowerCase()).toContain('publicsans');
      const trigger = page.getByRole('button', { name: 'Abrir menú de páginas' });
      if (width < 768) {
        await expect(trigger).toBeVisible();
        await trigger.click();
        await expect(page.getByRole('dialog')).toBeVisible();
        await page.keyboard.press('Escape');
        await expect(page.getByRole('dialog')).toHaveCount(0);
      } else {
        await expect(trigger).toBeHidden();
      }
    });
  }
});
