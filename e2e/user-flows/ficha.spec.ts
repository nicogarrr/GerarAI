import { expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";

// MSFT es la ficha determinista del fixture E2E (sin red ni LLM).
for (const vp of VIEWPORTS) {
  test.describe(`ficha (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);

    test("rangos del gráfico, DCA, tesis y «Diario de decisiones»", async ({ page }) => {
      await visit(page, "/research/MSFT");
      await expect(page.getByRole("heading", { level: 1 }).first()).toBeVisible();
      await expectHealthyPage(page, "ficha MSFT");

      // Rangos: cada botón habilitado queda pulsado al elegirlo y la página sigue sana.
      const ranges = ["1D", "5D", "1M", "6M", "YTD", "1A", "5A", "Máx"];
      for (const label of ranges) {
        const button = page.getByRole("button", { name: label, exact: true }).first();
        if (!(await button.isVisible().catch(() => false)) || !(await button.isEnabled())) continue;
        await button.click();
        await expect(button).toHaveAttribute("aria-pressed", "true");
        await expectHealthyPage(page, `rango ${label}`);
      }

      // DCA: o un nivel evaluado o el estado vacío con copy, nunca nada. En
      // móvil el histórico va plegado tras «Señales DCA: histórico».
      const dcaToggle = page.getByRole("button", { name: "Señales DCA: histórico" });
      if (await dcaToggle.isVisible().catch(() => false)) {
        await dcaToggle.scrollIntoViewIfNeeded();
        await dcaToggle.click();
      }
      await expect(
        page.getByText(/señal DCA|Nivel DCA|Sin nivel|DCA ·/).filter({ visible: true }).first(),
      ).toBeVisible();

      // Tesis: sin tesis hay copy y la acción para generarla (no se pulsa: LLM).
      await expect(page.getByText(/Sin tesis todavía|Tesis/).filter({ visible: true }).first()).toBeVisible();

      // «Diario de decisiones»: vive en el menú de cabecera «Más acciones»
      // (CompanyActionsMenu; antes en un <details>). El enlace lleva al
      // diario de la pestaña Seguimiento y lo deja a la vista.
      await page.getByRole("button", { name: "Más acciones" }).click();
      const link = page.getByTestId("decision-journal-entry");
      await expect(link).toBeVisible();
      await link.click();
      await expect(page).toHaveURL(/view=seguimiento#diario-decisiones/);
      const journal = page.locator("#diario-decisiones");
      await expect(journal).toBeVisible({ timeout: 30_000 });
      await expect(journal).toBeInViewport({ timeout: 10_000 });
      await expectHealthyPage(page, "diario de decisiones");
    });
  });
}
