# Conservación de ibkr_raw_rows

## Estado actual

No se añade TTL, purga programada ni borrado por antigüedad. Se conservan
las filas crudas de Flex, incluidas las secciones todavía no interpretadas.
Desconectar IBKR elimina las credenciales, no estas filas. Reimportar una fila
idéntica no crea otra copia; valores distintos se conservan como otra fila.

La migración 0096 admite repetir upgrade y downgrade sobre una tabla vacía.
Si contiene cualquier fila, el downgrade se detiene antes de eliminarla:
no puede distinguir automáticamente un dato prescindible de una prueba fiscal.
No se debe sortear esta protección con un DROP manual para resolver un rollback.

## Decisión pendiente de Nico

Falta aprobar una política de conservación con fuente legal verificada para su
caso. Este cambio no establece un plazo legal ni supone que una fila antigua
haya perdido valor fiscal. En particular, no implementa una purga a los cuatro
años: el plazo de prescripción no debe convertirse sin más en un TTL desde la
fecha de creación de la fila.

Antes de habilitar cualquier purga hay que definir y verificar:

- qué pruebas hacen falta para justificar coste de adquisición, lotes abiertos,
  divisas, operaciones corporativas y ejercicios afectados;
- desde qué hecho y fecha se computa cada plazo aplicable, y cómo se tratan
  interrupciones, comprobaciones o litigios y obligaciones de conservación;
- archivo recuperable, integridad, restauración probada y autorización expresa
  antes de borrar la única copia de cualquier prueba.

No se ha verificado aquí una fuente jurídica que permita fijar la fecha de
borrado. La decisión sigue abierta; no hay cambios de retención destructivos.
