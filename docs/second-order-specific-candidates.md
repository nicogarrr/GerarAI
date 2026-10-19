# Candidatos indirectos específicos

## Cambio

- Excluye `company_id` de la noticia y su ticker, comparado sin espacios y en mayúsculas.
- Cada ticker aparece como máximo una vez, incluso si coincide por industria y por varias etiquetas. Se conserva la primera hipótesis específica que lo selecciona en el reparto por rondas; no se suman confianzas ni se afirma que las otras hipótesis sean falsas.
- El límite de 10 cuenta candidatos únicos, no repeticiones. Máximo 2 por tema específico normalizado. El reparto por rondas da una primera plaza a cada tema antes de volver al primero.
- Dentro de cada tema se prioriza el respaldo exacto de metadatos: factor específico (2 puntos), industria (1), ambos (3). Empates estables por ID, sin preferencia económica afirmada. No se ordena alfabéticamente ni se simula relevancia económica verificada. Cada candidato lleva motivo y `selection_basis` con esa limitación.
- `Insurance`, `Legal` y otras categorías paraguas no bastan para generar candidatos. D&O necesita una coincidencia específica; no se deduce de la industria Insurance.
- Las etiquetas de madurez/riesgo/estilo (`speculative`, `pre_fcf`, `pre_revenue`, `growth`, `high_beta`, etc.) no generan candidatos y se excluyen del contexto de factores del sujeto.
- Un tema legal, D&O o litigation finance sin coincidencia específica en metadatos sigue sin empresas. No se asignan aseguradoras o despachos por intuición.
- Todas las filas siguen siendo hipótesis no verificadas. No cambia tesis, scores, alertas ni relaciones persistidas.

## Pruebas y límites

`tests/test_second_order_news_service.py`: 26 pruebas, incluye regresión ASTS con temas genéricos y varias coincidencias del mismo ticker. ASTS del test es fixture, no una copia del evento 156016. La regresión del hallazgo del 19 de octubre pone Insurance primero, 15 aseguradoras genéricas, Space Launch, Satellite y Legal. Descarta el ruido y el sujeto, permite canales específicos posteriores, comprueba ranking por respaldo de metadatos y un máximo de 2 por tema. Otro test reparte 10 plazas entre 8 temas, sin que los primeros agoten el cupo.

Replay local determinista de dos titulares públicos reales con universo de empresas fixture:

1. Reuters vía StreetInsider, 5 oct 2026: Honda plans highway test of wireless charging for moving trucks.
   https://www.streetinsider.com/Reuters/Honda+plans+highway+test+of+wireless+charging+for+moving+trucks/27144605.html
2. Electrek, 12 oct 2026: Electric trucks meet hydro power at one of Canada's busiest ports.
   https://electrek.co/2026/10/12/electric-trucks-meet-hydro-power-at-one-of-canadas-busiest-ports/

En ambos replays solo salen GRID/OIL del universo fixture por industria exacta. Esto comprueba el código, no acredita exposiciones de empresas reales ni la veracidad de las noticias. No se ejecutó un LLM real ni se accedió al evento 156016.

## Verificación del piloto tras desplegar

Desde `data-engine`, con el entorno de la aplicación y el tenant de prueba:

```bash
PYTHONPATH=. python scripts/verify_second_order_candidates.py --tenant-id 2 --event-id 156016 --use-llm
```

El script fija `db.info["tenant_id"] = 2`, busca el evento con filtro explícito de tenant, imprime el resultado y comprueba tickers únicos, ausencia del sujeto y estado no verificado. `--use-llm` consume cuota limitada del modelo gratuito existente; sin esa opción solo se prueba la ruta determinista. No escribe peer_relationships.

Para otras dos noticias reales del tenant, el piloto debe obtener IDs existentes y repetir el comando con `--event-id ID2 --event-id ID3`. No hay IDs inventados ni un resultado de producción declarado aquí. Verificar además que el número de candidatos útiles puede ser cero: es preferible a recuperar ruido genérico.

## Propuesta de relaciones con fuentes gratuitas (no implementada)

SEC documenta API pública de submissions y acceso sin claves, con nombre, CIK, tickers, bolsas e historial de formularios:
https://www.sec.gov/search-filings/edgar-application-programming-interfaces

Ruta viable sin inventar:

1. Obtener el 10-K/20-F más reciente desde el historial oficial, conservar accession, URL, fecha, fragmento y sección de competencia. Para ESEF haría falta el mismo vínculo a informe anual oficial del emisor.
2. Resolver nombres de competidores explícitos a CIK/ISIN/ticker del universo. Ante ambigüedad o empresa privada sin ticker, no crear enlace a una cotizada distinta. Una mención, cliente, proveedor y competidor son tipos diferentes.
3. Guardar relación tipada y evidencia literal del informe, con alcance y fecha. Es declaración del emisor, no verificación independiente de competencia actual. No activarla en el análisis hasta validar la evidencia y la identidad.
4. SIC exacto, si se obtiene y guarda con procedencia, permite proponer pares de clasificación solamente. No demuestra competencia, suministro ni exposición D&O. GICS no se presume gratuito ni disponible sin fuente/licencia verificada.

`PeerRelationship` actual tiene score/source/rationale/selected/selection_trace pero no contrato obligatorio de tipo, documento, fragmento o vigencia. El selector actual de peers combina industria, sector, tipo y madurez: no equivale a competidores declarados. Primero haría falta un contrato de evidencia y tipos o una estructura separada de candidatos. No poblar selected=True a partir de sector, SIC o un nombre generado por LLM.
