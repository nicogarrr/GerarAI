# Tests del frontend

Revisión GerarAI, hallazgo M2: la mayoría de `scripts/*.test.ts` leen el código
con `readFileSync` y lo validan con expresiones regulares. Eso fija **cómo está
escrito** el código, no **qué hace**: un refactor correcto los rompe y un bug
que respeta el texto los pasa. Desde este cambio hay dos tipos de test y cada
uno tiene su sitio.

## Qué test escribir

| Quieres comprobar… | Escribe | Dónde |
|---|---|---|
| Lo que ve o hace el usuario: textos, N/D, formato es-ES, errores de formulario, teclado, estados vacío/error | Test de comportamiento (Vitest + Testing Library) | `tests/unit/**/*.test.tsx` |
| Una función pura de `lib/` (cálculo, formato, etiquetas) | Test que importa la función y comprueba su resultado. Vale `node --test` (patrón actual) o Vitest | `scripts/*.test.ts` o `tests/unit/**/*.test.ts` |
| Una **política de código** que no se ve renderizando: «sin `use client` aquí», «este fichero no importa X», «el CSS reserva el alto con este atributo» | Guard de texto (regex) | `scripts/*.test.ts` |

Regla: si el test se puede escribir importando el código real, no se escribe
con regex. Un guard de texto solo es la opción buena cuando lo que se protege
**es** el texto.

## Cómo se ejecutan

```bash
npm run test:unit        # Vitest: tests/unit/**
npm run test:coverage    # Vitest + cobertura v8 (falla si baja del suelo)
npm run test:guards      # bundle node --test de scripts/*.test.{ts,mjs}
npm run test:guards -- --coverage   # lo mismo, dejando coverage/frontend/guards.lcov
npm run coverage:summary # tabla: Vitest, guards y unión por lib/ y components/
```

Un fichero concreto: `npx vitest run tests/unit/components/PortfolioSummary.test.tsx`.

## Cómo escribir un test de componente

- Importa el componente real con el alias `@/` y renderízalo con `render()`.
- Busca por **rol y texto accesible** (`getByRole('button', { name: 'Guardar Inversión' })`,
  `getByLabelText('Cantidad')`), no por clases ni por `data-testid`, salvo que no haya otra forma.
- Simula solo los bordes: server actions (`@/lib/actions/*`), `next/navigation`,
  `sonner`. Nunca el código que estás probando. Ejemplo en
  `tests/unit/components/AddTransactionButton.test.tsx`.
- Para valores con formato usa las funciones de `lib/format.ts` en el esperado, o una
  regex tolerante a espacios duros: `Intl` mete U+00A0/U+202F.
- Debounces y timeouts: `vi.useFakeTimers()` + `vi.advanceTimersByTimeAsync(ms)` dentro de `act`.
  Ejemplo en `tests/unit/components/TickerSearchInput.test.tsx`.
- Comprueba que el test muerde: rompe a mano el comportamiento (p. ej. quita el
  `noData ? NA :`) y el test tiene que ponerse rojo.
- jsdom no tiene layout. Lo que dependa de geometría real (scroll, anchos, móvil) va a
  `e2e/` con Playwright.

Los polyfills mínimos de jsdom (`scrollIntoView`, `ResizeObserver`, pointer capture) están
en `tests/unit/setup.ts`.

## Cobertura

Se mide **todo** `lib/`, `components/` y `middleware.ts`; lo que ningún test
importa cuenta como 0 %. Línea base (27-oct-2026):

| Ámbito | Vitest | Guards `node --test` | Unión |
|---|---|---|---|
| `lib/` | 1,50 % | 49,84 % | 50,18 % |
| `components/` | 4,11 % | 1,25 % | 4,96 % |
| `middleware.ts` | 100 % | 0 % | 100 % |
| Total (12.014 líneas, 445 ficheros) | 2,71 % | 28,43 % | 30,31 % |

Lectura: los guards que importan funciones de `lib/` ya ejecutan la mitad de `lib/`; los
componentes casi no tienen tests que los rendericen (≈5 %). Ahí está el trabajo.

- El **trinquete que bloquea CI** son los `thresholds` de `vitest.config.mts` (cobertura de
  los tests de Vitest). Se fijaron con lo medido y solo se suben: cuando un PR añade tests,
  sube el suelo en el mismo PR.
- La tabla de unión la imprime CI en el resumen del job `Frontend quality` y se publica como
  artefacto `frontend-coverage`. Es informativa.
- La tabla que imprime `node --test --experimental-test-coverage` en el log («all files 92 %»)
  **no** es la cobertura del frontend: solo cuenta los ficheros que algún guard llegó a
  cargar. La cifra honesta es la de `coverage:summary`.
- Si el informe de ficheros sin cubrir no puede transformar un fichero (p. ej. uno que
  importa `server-only`), Vitest avisa en el log («Failed to parse … Excluding it from
  coverage») y ese fichero queda fuera del denominador. Medido: 1 fichero
  (`lib/research/assistant-client.ts`).

## Migrar un guard de regex

1. Escribe el test de comportamiento que cubre la misma intención.
2. Comprueba que falla si rompes el comportamiento.
3. Borra del guard las aserciones que ahora cubre el test (o el guard entero) y deja un
   comentario apuntando al test nuevo. Lo que sea política de código se queda.

Ya migrados: `OnlineBanner`, `PortfolioSummary` (N/D sin base de coste),
`TickerSearchInput` (debounce, error ≠ sin resultados, respuestas tardías, teclado),
`AddTransactionButton` (validación sin submits silenciosos, divisa por sufijo, envío),
`ErrorBoundary` y `middleware.ts` (redirección sin cookie, bypass E2E, matcher). El guard
`scripts/middleware-guard.test.ts` se mantiene de momento como red adicional.
