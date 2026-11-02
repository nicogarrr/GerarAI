# Biblioteca: renderizar solo el panel activo

Base: ffd803fddb1490a0e8ff1eb1f97b7676c1d4cccf. Candidato: mismas dependencias, imagen de producción separada y mismo backend/identidad de QA. Fecha: 2026-11-02, Europe/Madrid.

La página ya seleccionaba pestaña por URL, pero construía los tres paneles en el servidor antes de que TabsContent ocultara dos en el cliente. El cambio evita construir los paneles inactivos. No cambia APIs, permisos, datos, enlaces ni acciones.

## A/B público sin backup concurrente

Mismo navegador, GET RSC sin caché, candidato/base/base/candidato/candidato/base. El header de QA dirige solo las peticiones elegidas al contenedor candidato. Ambas versiones conservan Documentos; el candidato no envía Subir en el panel Biblioteca. Todas las respuestas 200, sin digest de error.

| Versión | Tiempo total ms | TTFB ms | Bytes RSC sin compresión |
|---|---|---|---|
| Candidato | 783, 507, 509 | 232, 233, 245 | 140511 |
| Base | 1462, 1070, 2133 | 225, 230, 227 | 565917 |

Mediana 1462 a 509 ms (-65,2%); payload -75,2%. TTFB no mejora. Es reducción de construcción/transferencia de contenido, no una afirmación de que toda la app sea fluida.

Bloque quieto anterior ABBAABBA: base 44229/2983/5317/1947 ms, candidato1469/1214/948/955 ms. Se conserva el valor extremo de44,2s; no se atribuye una causa a ese extremo. En pruebas previas con backup concurrente hubo una primera respuesta candidata incompleta, excluida como evidencia de rendimiento. Una prueba visual mezcló chunks de dos builds por el routing temporal; se corrigió el routing de prueba y se inspeccionaron Biblioteca, Principios y Subir correctamente, sin cambiar código para esconder el fallo.

## Validación

- 2899/2899 guards verdes, entorno limpio.
- Build producción candidato verde; TypeScript dentro del build terminó en63s.
- ESLint y tsc focalizados previos verdes. Dos reintentos locales posteriores de tsc superaron el límite de ejecución120s, no se cuentan como éxitos.
- Inspección visual real de las tres pestañas: datos, filtros y formularios presentes. No se enviaron formularios ni mutaciones de cartera.
