import { expect, test } from "@playwright/test";
import { waitForHydration } from "./fixtures/wait-for-hydration";

const runUiE2E = process.env.E2E_UI_RUN === "1";

test.describe("investor thesis alert flow", () => {
  test.skip(!runUiE2E, "Set E2E_UI_RUN=1 to run browser tests.");

  test("research thesis exposes the quick alert control", async ({ page }) => {
    await page.goto("/research/MSFT");

    await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
    // La ficha hidrata tarde sus secciones en streaming: sin esta espera el
    // clic podía caer antes de hidratar (ver wait-for-hydration.ts).
    await waitForHydration(page);
    // El formulario de alerta vive en un popover tras el botón campana.
    await page.getByRole("button", { name: "Alerta de precio" }).click();
    await expect(page.getByPlaceholder("Precio objetivo $")).toBeVisible();
    await expect(page.getByRole("button", { name: "+ Alerta" })).toBeVisible();

    const alertsLink = page.getByRole("link", { name: "Ver alertas" });
    await expect(alertsLink).toBeVisible();
    await expect(alertsLink).toHaveAttribute("href", "/alerts");
  });

  test("quick alert validates the target price client-side", async ({ page }) => {
    await page.goto("/research/MSFT");

    await expect(page.getByRole("heading", { name: "MSFT", level: 1 })).toBeVisible();
    await waitForHydration(page);
    await page.getByRole("button", { name: "Alerta de precio" }).click();
    await page.getByRole("button", { name: "+ Alerta" }).click();
    await expect(page.getByText("Introduce un precio objetivo válido")).toBeVisible();
  });

  // Clic pre-hidratación determinista: reteniendo los chunks de cliente el
  // clic cae SEGURO antes de hidratar (no depende de la velocidad de la
  // máquina). Sin la retención early-open el clic se pierde y el popover no
  // abre nunca: es el rojo que vio el piloto en la suite completa a 2 CPU.
  test("retains a pre-hydration alert click and opens the popover", async ({ page }) => {
    let releaseChunks!: () => void;
    const gate = new Promise<void>((resolve) => {
      releaseChunks = resolve;
    });
    await page.route("**/_next/static/**/*.js*", async (route) => {
      await gate;
      await route.continue();
    });
    try {
      // Solo se retienen los .js (como research-controls-hydration): el CSS y el
      // resto de estáticos pasan, así el HTML del servidor pinta el botón sin React.
      // "commit": con los chunks retenidos DOMContentLoaded no llega nunca (los
      // scripts diferidos lo bloquean) y un goto a "domcontentloaded" se
      // quedaria colgado antes de liberar la puerta.
      await page.goto("/research/MSFT?view=thesis", { waitUntil: "commit" });

      // HTML inicial sin React: el script de captura (inline) es el único dueño.
      const trigger = page.getByRole("button", { name: "Alerta de precio" });
      await expect(trigger).toBeVisible();
      await trigger.click();
    } finally {
      releaseChunks();
    }

    // Tras hidratar, QuickAlertButton consume la intención retenida y abre.
    await expect(page.getByPlaceholder("Precio objetivo $")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "+ Alerta" })).toBeVisible();
  });
});
