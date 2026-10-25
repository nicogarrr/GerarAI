import { expect, test } from "@playwright/test";

// Carril 0.9: humo de rutas clave. Cada pantalla debe renderizar su heading
// y NUNCA un error boundary (ni el de segmento de ruta, ni el global, ni el
// ErrorBoundary de sección). Si una ruta clave rompe, este spec lo dice con
// el nombre de la ruta, no con un fallo indirecto tres specs más allá.
test.skip(!process.env.E2E_UI_RUN, "Set E2E_UI_RUN=1 to run browser tests.");

// Textos exclusivos de los tres boundaries: app/(root)/error.tsx,
// app/global-error.tsx y components/ErrorBoundary.tsx.
const BOUNDARY_TEXTS = [
  "No se pudo completar la operación",
  "Algo ha fallado",
  "Algo salió mal",
];

const ROUTES: Array<{ path: string; heading: string }> = [
  { path: "/inicio", heading: "Qué ha cambiado" },
  { path: "/portfolio", heading: "Resumen" },
  { path: "/watchlist", heading: "Watchlist" },
  { path: "/research", heading: "Índice de research" },
  { path: "/taxes", heading: "Impuestos" },
  { path: "/propicks", heading: "ProPicks IA" },
];

for (const { path, heading } of ROUTES) {
  test(`humo ${path}: contenido sin error boundary`, async ({ page }) => {
    const response = await page.goto(path);
    expect(response?.status(), `${path} respondió ${response?.status()}`).toBeLessThan(400);
    await page.addStyleTag({ content: "nextjs-portal{display:none!important}" });
    for (const text of BOUNDARY_TEXTS) {
      await expect(page.getByText(text)).toHaveCount(0);
    }
    // El índice de research agrega dashboard + cartera + watchlist: margen.
    await expect(page.getByRole("heading", { name: heading, level: 1, exact: true })).toBeVisible({ timeout: 30_000 });
  });
}
