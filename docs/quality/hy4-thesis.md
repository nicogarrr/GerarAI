# Hy4: narrativas de tesis

Depende del guard worker comun. Cuando THESIS_GO_MODEL=hy4-flash-free,
create_thesis_narrative_provider devuelve Hy4Provider con la clave Go existente,
no endpoint antiguo ni fallback de otro modelo. Sin ese valor explicito,
comportamiento anterior intacto. Las narrativas deep/news que ya usan esta
factory quedan cubiertas. No se modifica valoracion, ingesta SEC, formulas,
reglas de publicacion, validadores de fuentes ni N/D. No implica que todo el
pipeline thesis_v2 use esta factory: equipo de expertos se cubre por otra PR.
Cero llamadas reales de inferencia en tests. No merge/deploy en este cambio.
Activacion default temporal se entrega aparte con mapa completo del reemplazo.
