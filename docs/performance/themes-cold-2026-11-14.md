# Temas: no esperar al proveedor en la primera visita

Base: f4969f0b5. Sólo backend. Sin pruebas nuevas contra producción.

## Diagnóstico

[Medido en entorno aislado] `ThemesCache.get()` ejecutaba el cálculo en el
hilo de la petición si no había dato previo. La caché caducada ya se servía
sin esperar. El cómputo descarga las velas del universo de cestas con seis
trabajadores y plazo global de 40 segundos. No se modifican esas reglas.

[Medido en producción por revisión móvil, no repetido aquí] El documento de
`/temas` tardó 21,8 s en la primera visita y 4,1 s en la siguiente, una muestra
por visita. No hay trazas del backend que atribuyan esos segundos a una
función concreta. Es compatible con el camino frío, no prueba causal de
esos tiempos de producción.

## Cambio

La ruta usa `get_background()` y añade `refreshing: boolean`:

- Sin descarga terminada: `themes=[]`, `as_of=null`, `generated_at=null`,
  `status="sin_datos"`, `stale=false`, `refreshing=true`.
- Con descarga terminada: mismo dato, fechas y clasificación intradía que
  antes; `refreshing` dice si hay un refresco en curso.
- Dato caducado: se conserva el anterior con `stale=true`. Un fallo nunca
  lo sustituye por vacío.
- Completo: 1 h. Parcial: 5 min. Fallo o vacío: 60 s antes de reintentar.
- Un refresco por proceso, compartido por el precalentado de arranque de
  producción y las peticiones. Ni el arranque ni la petición esperan a Yahoo.

El frontend debe aceptar `generated_at: string | null`, mostrar
"Preparando datos de mercado" sólo mientras no hay datos y `refreshing`
es verdadero y reconsultar espaciadamente. `refreshing=false` sin datos es
una descarga vacía o fallida, no una preparación infinita. La parte visual
se entrega por separado. La caché sigue siendo local al proceso, no global
entre réplicas; este cambio no añade persistencia ni un planificador nuevo.

## Antes/después, mismo entorno

[Medido, carga controlada artificial, NO latencia de producción]
Cálculo con espera fija de 50 ms, caché nueva por muestra, 20 muestras por
versión, mismo proceso e intérprete. Se espera a terminar cada refresco
fuera de la ventana medida. Percentil por rango más próximo.

| Camino | p50 ms | p95 ms | N |
|---|---:|---:|---:|
| Antes: get sin dato previo | 50,074 | 50,093 | 20 |
| Después: ruta no bloqueante | 0,080 | 0,164 | 20 |

Los 50 ms se siguen pagando en segundo plano: no se afirma que Yahoo ni el
análisis sean más rápidos. Las muestras completas están en
`evidence/themes-cold-controlled-2026-11-14.json`.

## Validación

Rojo primero: los cuatro tests nuevos fallan contra la base. Con el cambio:
61 tests verdes (cálculo, caché, ruta, bordes y arranque). Los tests usan
barreras para demostrar que la petición termina antes que el proveedor,
single-flight, recuperación/cooldown, fechas originales y precalentado.
Cobertura medida con `coverage --source=app,main`: 26/26 líneas ejecutables
cambiadas de backend, 100 %. No se usa un umbral de tiempo frágil para la CI.
