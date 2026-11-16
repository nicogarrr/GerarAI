# Sustitucion temporal de DeepSeek por Hy4 Go

Prerequisito: guard worker #5760. Activacion por Piloto despues de FAV/merge:
HY4_REPLACE_DEEPSEEK=1 en backend + workers. Este cambio NO toca produccion.
Flag ausente deja configuracion anterior. Flag1 intercepta SOLO modelos
configurados deepseek-v4.1-flash, deepseek-v4.1-flash-free o hy4-flash-free
antes de construir cascadas/fallbacks. Otro modelo o tenant con proveedor no
Go queda intacto. Usa clave Go de plataforma ya existente, no otra credencial.

Factories cubiertas: create_llm_provider (KPIs/expertos/thesis_v2 y generales),
create_chat_llm_provider, create_background_llm_provider (biblioteca ingesta y
principios), create_free_interactive_provider (debates), free_only_provider y
create_thesis_narrative_provider (deep/news). Devuelven Hy4Provider DIRECTO,
sin fallback/reintentos, endpoint Go actual, preflight precio0 + postflight
metadatos costeGo0. Rutas con proveedor inyectado a mano o adaptador custom
NO quedan certificadas por enumerar estas factories: auditar por ruta.
Cerebro ticker/biblioteca/chat tambien tienen PRs de seleccion explicita.

Caducidad operativa: 30 nov 2026 10:56UTC (11:56 Madrid), calculada como14dias
tras la instruccion del16nov11:56Madrid. NO afirma fin contractual del proveedor.
Puede cortar antes si precio/coste no verificable. Tras ese techo devuelve
DisabledProvider, sin restaurar DeepSeek ni otro modelo pagado automaticamente.
Retirar el flag seria volver a ruta anterior, por eso NO es un rollback gratis
permitido automatico: mantener1 y cierre hasta nueva decision del propietario.

Cambios de cuotas y limites: no se cambia ExtraUsage ni PAYG. Nico declaroOFF,
no se puede comprobar ese flag por API localizada. Latch por proceso, una
inferencia admitida por proceso; procesos distintos no comparten bloqueo.
No garantia retroactiva de primer cargo ante carrera de repricing proveedor.
Tres smokes publicos sintéticos Go200/0EUR pese a cuota mensual100%antes/despues;
no equivalen a capacidad de lotes ilimitados. Prueba inicial1casoporruta, sin
lotesgrandes, stopprimer429/402/coste/fallometadata, sin otros modelos.

Validacion: bateria focalizada factories/guards/regresiones, todos archivos
fuente modificados >=85% lineas y ramas. Comando y salida en evidencia adjunta.
Pyright ficheroscambiados0errores (warningsheredados), ruffverde. CIcompleto
pendiente; no se atribuye despliegue ni activacion por crear este paquete.

## Revision de aislamiento

restricted/free_only se evalua ANTES del reemplazo en las cinco factories.
free_only_provider exige identidad interna verificada, enabled y clave antes
siquiera de resolver Hy4. El transporte mantiene la exigencia de identidad
incluso dentro de selection_scope Hy4. replacement_provider ignora TODA
configuracion de tenant (BYOK), Go incluido: nunca cambia su modelo/endpoint,
no toma su clave y nunca sustituye su clave por la de plataforma. Configuracion
invalida o deshabilitada sigue cerrada. La politica preexistente free_only
para tenants restringidos no cambia.

Reproducir: sh scripts/test-hy4-default-routing.sh (331 tests, sin red real).
Cobertura por fichero completo, lineas/ramas:
chat_provider94,50/89,41; factory96,70/92,50;
free_interactive97,30/85,71; free_only98,08/95,45;
hy498,15/97,06; thesis_go100/100.
TSC no aplica; pyright focalizado0errores11avisos heredados. Ruffverde.
No implica green de toda la suite ni permiso de deploy.
