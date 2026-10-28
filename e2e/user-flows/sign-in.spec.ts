import { expect, expectHealthyPage, runUiE2E, test, VIEWPORTS, visit } from "./support";

const EMAIL = "e2e-user-flows@example.com";
const PASSWORD = "Correcta-Clave-123";

for (const vp of VIEWPORTS) {
  test.describe(`inicio de sesión (${vp.name})`, () => {
    test.skip(!runUiE2E, "Set E2E_UI_RUN=1 E2E_USER_FLOWS=1 to run the user-flow suite.");
    test.use(vp.use);

    test("validación, contraseña incorrecta con copy y acceso correcto", async ({ page, health, baseURL }) => {
      // Cuenta real de Better Auth (Mongo). Si ya existe, el alta responde 4xx
      // y da igual: lo que se prueba es el inicio de sesión.
      await page.request.post(`${baseURL}/api/auth/sign-up/email`, {
        data: { email: EMAIL, password: PASSWORD, name: "Flujo E2E" },
        headers: { Origin: baseURL ?? "" },
        failOnStatusCode: false,
      });
      // El intento fallido es un 401 esperado del propio flujo.
      health.allowResponse(/\/api\/auth\/sign-in\/email/, 401);

      await visit(page, "/sign-in");
      await expect(page.getByRole("heading", { name: "Bienvenido de nuevo", level: 1 })).toBeVisible();
      await expectHealthyPage(page, "sign-in");

      await page.getByRole("button", { name: "Iniciar sesión" }).click();
      await expect(page.getByText("El email es obligatorio")).toBeVisible();
      await expect(page.getByText("La contraseña es obligatoria")).toBeVisible();

      await page.getByRole("textbox", { name: "Email" }).fill(EMAIL);
      await page.getByRole("textbox", { name: "Contraseña" }).fill("incorrecta-000");
      await page.getByRole("button", { name: "Iniciar sesión" }).click();
      await expect(page.getByText(/incorrect|no válid|inválid|no coinciden/i).first()).toBeVisible({ timeout: 20_000 });
      await expect(page).toHaveURL(/\/sign-in/);
      await expectHealthyPage(page, "contraseña incorrecta");

      await page.getByRole("textbox", { name: "Contraseña" }).fill(PASSWORD);
      await page.getByRole("button", { name: "Iniciar sesión" }).click();
      await expect(page).not.toHaveURL(/\/sign-in/, { timeout: 30_000 });
      await page.waitForLoadState("networkidle").catch(() => undefined);
      await expectHealthyPage(page, "tras iniciar sesión");
    });
  });
}
