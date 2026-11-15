# ASTS: anexo de escenario atribuido a Deutsche Bank

Recepción: 2026-11-15. Informe original: fecha y URL desconocidas.

Se conserva una transcripción de una captura de la tabla Figure 3: ASTS
Model Summary atribuida a Deutsche Bank. No se ha obtenido ni autenticado
el informe del banco. La atribución se mantiene como no verificada.

La página de lectura ASTS muestra un anexo separado ES/EN: ingresos, EBITDA
ajustado y FCF 2025-2030; capex 2026E; satélites comerciales acumulados
2026E-2030E; margen EBITDA 2030; mezcla de contratos 2027 y escenario de
financiación. Las ausencias se muestran como no transcritas, nunca cero.
2025 no se etiqueta como resultado real validado. Las cifras futuras son
estimaciones, no guidance ni consenso. La cobertura de financiación se
presenta como hipótesis, no como fondos asegurados.

No altera FinancialFact, consenso, probabilidades, IRR, precio objetivo,
valoración, escenarios del motor ni versiones aprobadas de tesis. El anexo
no se incorpora a las exportaciones históricas PDF/EPUB. No se regenera
ninguna narrativa mediante LLM. El anexo es común de research para ASTS,
no una nota personal ni una modificación del documento aprobado.

## Fuentes y límites

- Captura transcrita, recibida 15/11/2026: fuente de la tabla; informe original
  pendiente. No se crea una URL ficticia al tuit o al informe DB.
- https://lunarcrush.ai/topic/$asts/posts, consultado 15/11/2026:
  reproduce literalmente el texto del tuit y lo atribuye a @StockSavvyShay
  a las 12:30 UTC del 15/11/2026. Es un agregador secundario, no el post
  original ni prueba de la autenticidad de la tabla o del banco.
- https://www.sec.gov/Archives/edgar/data/1780312/000149315226050513/ex99-1.htm,
  comunicado de AST SpaceMobile del 06/11/2026 presentado en SEC:
  Blacklift se diseña para hasta cinco BlueBird por lanzamiento desde
  finales de 2028. Esto es un plan de desarrollo, no capacidad demostrada.
- https://ast-science.com/blacklift/ confirma el diseño de hasta cinco
  BlueBird. Esta fuente solo verifica Blacklift, no las estimaciones DB.

Búsquedas por valores distintivos 4490.3/3606.5/556.8 y por Figure 3 no
localizaron el informe original. No se usa otra nota anterior de Deutsche
Bank como sustituto. La fecha social no se traslada al informe bancario.

## Pruebas

27 tests de producto (componente, routing ASTS, error, retención y lectura
ES/EN) más 1 exportador visual temporal. Componente/datos nuevos: 100%
líneas y ramas. Guards completos 3069 pass / 0 fail / 1 skip; check-i18n,
typecheck, ESLint y diff-check. Sin cambios de baseline.

Cuatro capturas estáticas de componentes reales, ES/EN a 390/1440,
inspeccionadas con avisos y cifras legibles y sin overflow horizontal.
No prueba de hidratación, clics, PDF, backend completo ni producción.
