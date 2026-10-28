import { test } from '@e2e-dev/web';
import { z } from 'zod';

// Pasada QUIRURGICA de agente (Nico 2026-10-28): tests cortos y precisos,
// pocos pasos cada uno, contra paginas publicas. Los topes duros viven en
// e2e.config.ts (maxSteps/maxModelCalls/maxInputTokens por agente): un test
// no puede pasarse de presupuesto aunque el modelo divague. El uso de tokens
// por llamada lo imprime el reporter del CLI y el workflow lo vuelca al
// summary (seccion "Uso de tokens").
const RULES =
  'READ-ONLY. Never create, edit, delete or submit anything except the login form. ' +
  'Do not click buttons that save, add, remove, buy, sell, import, or generate. Only navigate and read. ' +
  'Be quick: at most 3 actions per test.';

const SKIP_AGENT: string | false =
  process.env.E2E_AGENT !== '1' &&
  'Pasada de agente NO ejecutada: el precheck del proveedor Zen fallo o falta OPENCODE_API_KEY.';

test.describe('pasada quirurgica (proveedor Zen)', { skip: SKIP_AGENT }, () => {
  test('landing CTA reaches the sign-up page', async ({ app, agent }) => {
    await app.open('/');
    await agent.act(`${RULES} Click the primary call to action "Empezar mi primera tesis".`);
    await agent.assert('the browser is on a sign-up or create-account page and it shows a registration form');
  });

  test('sign-in rejects bad credentials with a visible error', async ({ app, agent }) => {
    await app.open('/sign-in');
    await agent.act(
      `${RULES} Type "qa-no-existe@example.com" into the email field and "clave-incorrecta-123" into the password field, then submit the login form once.`,
    );
    await agent.assert('an error message about invalid credentials is visible and the user is NOT logged in');
  });

  test('help page FAQ expands an answer', async ({ app, agent }) => {
    await app.open('/help');
    await agent.act(`${RULES} Open the first frequently-asked-question item on this page.`);
    const info = await agent.extract(
      'Is an answer to the first FAQ now visible? Answer as JSON with exactly two keys: "checked" (the boolean true) and "answerVisible" (boolean).',
      { schema: z.object({ checked: z.literal(true), answerVisible: z.boolean() }) },
    );
    console.log('[faq]', JSON.stringify(info));
    if (!info.answerVisible) throw new Error('La primera FAQ de /help no muestra respuesta al abrirla');
  });
});
