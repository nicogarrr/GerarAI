# Mutation testing (mutmut + Stryker)

Mide si los tests **detectarían un fallo real**: la herramienta introduce un cambio
pequeño en el código (un `>` por `>=`, un `+=` por `=`, una etiqueta vacía…) y
vuelve a pasar los tests. Si ningún test falla, el mutante **sobrevive**: ese
camino del código no está protegido. La puntuación es mutantes matados / total.

No es un gate. Se lanza a mano y nunca bloquea un PR (cada módulo tarda minutos).

## Cómo correrlo

Backend (desde `data-engine/`, con el venv del proyecto y `pip install "mutmut>=3.8,<4"`):

```bash
python scripts/mutation/run_mutmut.py --list                 # módulos configurados
python scripts/mutation/run_mutmut.py currency --max-children 4 --survivors
```

El script copia el árbol versionado a un directorio temporal, escribe ahí un
`[tool.mutmut]` que muta **solo** el módulo elegido y corre **solo** sus tests
relacionados (la lista está en `TARGETS`), así que no toca tu árbol de trabajo.
`--survivors` imprime el diff de cada superviviente.

**Módulos grandes (`--lines` / `--chunks`).** mutmut escribe una copia de la
función entera por cada mutante: `compute_report` (~530 líneas, >1.100 mutantes)
genera un fichero de cientos de miles de líneas y la pasada no termina. Se parte
el fichero en tramos y se corre cada tramo por separado (en paralelo si hay CPU):

```bash
python scripts/mutation/run_mutmut.py tax_report_service --chunks 60      # imprime tramos A-B
python scripts/mutation/run_mutmut.py tax_report_service --lines 411-494 --max-children 2 --survivors
python scripts/mutation/run_mutmut.py tax_report_service --chunks 60 | \
  xargs -P 3 -I{} sh -c 'python scripts/mutation/run_mutmut.py tax_report_service --lines {} --survivors > mut-{}.log 2>&1'
```

`--lines` no toca el código: lanza mutmut con un runner que añade las líneas fuera
del tramo a las ignoradas (igual que un `# pragma: no mutate`). No se usan
pragmas `start`/`end` porque mutmut no los recorre en orden de texto: un `end`
dentro de una función y un `start` en la siguiente `def` de primer nivel dan
`PragmaParseError`. La puntuación del módulo es la suma de los tramos.

Los ficheros de test se copian solo si están versionados (`git ls-files`):
un test nuevo necesita `git add` antes de medirlo.

Frontend (desde la raíz; Stryker no está en `package.json` para no engordar `npm ci`):

```bash
npm i --no-save @stryker-mutator/core@9
npx stryker run stryker.conf.mjs     # informe en reports/mutation/mutation.html
```

`stryker.conf.mjs` usa el runner `command`: la mayoría de los tests de estas
librerías son guards `node --test` (`scripts/*.test.ts`) además de Vitest.

CI: workflow manual **Mutation testing (manual)** (`.github/workflows/mutation.yml`,
solo `workflow_dispatch`): eliges un módulo de backend y/o el frontend.

## Qué hacer con un superviviente

1. ¿Es equivalente (no cambia el comportamiento observable)? Ignóralo.
2. ¿Es un fallo plausible (un borde, una unidad, una etiqueta que ve el usuario)?
   Añade la aserción que falta. Los tests nacidos así se llaman
   `test_mutation_gaps_*.py` / `scripts/mutation-gaps-fe.test.ts`.
3. ¿El mutante revela que el código ya está mal? Test que falla en main + fix, PR aparte.

## Resultados (28-oct-2026)

Puntuación = matados / total; los timeouts cuentan como no matados.

| Módulo | Antes | Después |
|---|---|---|
| `currency` (divisas, GBp/GBP) | 58,7 % | 95,2 % |
| `units` (unidades de tipos) | 68,9 % | 95,6 % |
| `thesis_publication_gate` | 71,6 % | 95,5 % |
| `dca_signal_engine` | 70,2 % | 84,6 % |
| `tax_irpf_filing` | 68,2 % | 75,2 % |
| `fx_attribution` | 95,0 % | 100 % |
| `price_units` | 33 % | 44 % → **88,4 %** en ronda 2 (bug GBp/GBP arreglado en #2658) |
| `portfolio_snapshot_service` (fotos diarias/TWR) | 70,4 % | 84,3 % |
| `dca_signal_service` | 75,3 % (ronda 2: 81,8 %) | **94,7 %** (ronda 2) |
| `portfolio_fx_service` | 82,6 % (ronda 2: 85,5 %) | **86,9 %** (ronda 2; 23 timeouts por carga) |
| `tax_modelo720_service` | 56,7 % (ronda 2, completa) | **71,9 %** (ronda 2; 76,9 % sin los textos de `_notas()`) |
| `tax_report_service` | 76,4 % (ronda 2, primera medición completa por tramos) | **85,0 %** (ronda 2) |
| Frontend `lib/dca/format.ts` | 56,4 % | 96,9 % |
| Frontend `lib/market/quote-freshness.ts` | 83,8 % | 88,0 % |
| Frontend `lib/watchlist/sort-rows.ts` | 83,0 % | 88,7 % |
| Frontend `lib/portfolio-allocation.ts` | 86,7 % | 100 % |
| **Frontend total** | **71,0 %** | **92,6 %** |

Bug real encontrado por un superviviente: `resolve_fx` pasaba `GBp` a mayúsculas
(`GBP`), así que unos peniques habrían cruzado el FX como libras (×100). Latente
(el único llamador pasaba la moneda mayor); arreglado en #2598.

Ronda 2 (mutation-2): bug real en `price_units.close_in_company_currency`: una cotización en
GBp de una empresa en GBP salía ×100 (capitalización y PER). Arreglado en #2658. Tests de
supervivientes en #2665, #2671 y #2678. La lista `TARGETS` de `tax_report_service` no incluía 7
suites que ya lo ejercitaban; ahora están.

Pendiente: los supervivientes de `compute_report` en dividendos, pagos especiales y retenciones,
los tramos de valores de `check_thresholds` (720) y repetir `portfolio_fx_service` sin carga
para separar los timeouts.
