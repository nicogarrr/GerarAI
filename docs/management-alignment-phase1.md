# Directivos e incentivos: fase 1

Sección de lectura en Research > Seguimiento, junto a Credibilidad. No añade pestañas ni cambia la tesis, el cerebro, el valor intrínseco o el DCA. La agregación escribe únicamente `management_alignment_snapshots`, aislada por tenant y empresa.

## Cálculo y disponibilidad

- Instantáneas precomputadas por el worker cada seis horas para empresas seguidas y previamente consultadas. La primera consulta sin instantánea encola un cálculo de esa empresa; el GET no calcula cifras ni descarga datos. Deduplicación por tenant/empresa, cola computed existente, sin servicio nuevo.
- Sin job compatible: estado pendiente con causa. Sin hechos verificables: aviso con causa basada en lo que existe en la base, no una nacionalidad supuesta. Un corte con más de un día se señala como desactualizado.
- Últimos cinco ejercicios disponibles. Variación de acciones: `(actual / anterior - 1) * 100`, redondeo decimal half-up a una cifra. Solo ejercicios consecutivos y misma base de acciones. Un split registrado impide comparar saldos sin ajustar; un salto abrupto no registrado se muestra con aviso.
- Prioridad de acciones: saldo reportado, portada DEI, promedio ponderado diluido. Una portada DEI debe compartir accession con hechos anuales verificables y estar entre el último cierre de ese filing y 180 días después. Los comparativos reexpresados de ese mismo filing no pueden desplazar el ejercicio vigente. No se mezclan bases en la variación.
- Recompras en bruto, nunca se restan dólares a acciones. Ausencia de recompras no equivale a cero. La etiqueta de dilución neta solo aparece cuando hay recompras y emisión con evidencia.
- SBC/ingresos requiere el mismo cierre y moneda; SBC/FCF requiere caja operativa y capex del mismo cierre. La ingesta existente guarda capex negativo: FCF = caja operativa + capex. Un denominador no positivo no produce porcentaje. Cada porcentaje conserva todos sus operandos con enlaces y fechas en la instantánea.
- Insiders: seis y doce meses naturales, códigos P/S no derivados. Concesiones A, opciones M, retenciones F y donaciones G quedan fuera. La fecha de filing solo sustituye una fecha de transacción ausente. No se inventan importes ausentes.
- El flujo total incluye compras y ventas P/S. El flujo sin ventas programadas excluye ventas con marca verdadera. Si hay ventas sin marca conocida o importes incompletos, no se publica ese flujo como completo. Enmiendas sin vínculo al original impiden publicar el agregado para evitar duplicación.
- XML: `transactionCoding.aff10b5One` acepta 0/1/false/true. Se añade `data_quality.alignment_10b5_1` nullable, sin cambiar `rule_10b5_1` legacy ni su semántica compartida.
- UI: cifras enlazadas, fecha por bloque, sin etiquetas repetidas de fuentes. Las filas ausentes se omiten con un aviso de cobertura; los valores implausibles conservan aviso y el importe reportado cuando existe.

## Límites y deuda explícita

1. Los valores AAPL/ASTS de los fixtures son sintéticos y NO representan sus cuentas reales. El fixture AENA es un escenario de cobertura ausente, no prueba una causa corporativa concreta. Ninguna de estas atribuciones entra en la UI.
2. El flag acepta el checkbox explícito por transacción. El follow-up `management-alignment-real-filings.md` añade el caso real META con checkbox raíz SOLO cuando una nota afirmativa inequívoca, referenciada una única vez en el código de ESA venta, permite atribuirlo. La raíz sola, notas compartidas o ambiguas y variantes no reconocidas siguen desconocidas. No hay cobertura completa del XML real. La reingesta normal puede enriquecer una clave ausente o JSON null con evidencia atribuible sin tocar el Boolean legacy.
3. `rule_10b5_1 = false` histórico no prueba una venta fuera de plan. Hasta una reingesta normal con evidencia XML explícita, su clasificación nueva sigue siendo desconocida. No se sube la versión del parser ni se fuerza una descarga/backfill global.
4. P/S es la clasificación SEC disponible, no prueba por sí sola que toda compra fuera en bolsa en vez de privada. La UI habla de P/S y operaciones declaradas, no atribuye una motivación.
5. Esta entrega NO migra el transporte SEC preexistente. `connectors/form4.py::fetch_filing_xml` usa `_get_text`/`edgar_common.get_text` contra SEC; `connectors/sec.py` y `connectors/sec_edgar.py` conservan caminos SEC primero y mirror como fallback. Es deuda global pendiente de otro cambio. El guard anti-descarga directo de esta entrega cubre el agregado y el job NUEVOS: solo base persistida, cero llamadas SEC, cero proveedor de pago, cero LLM. No se afirma un guard mirror-only global.
6. Migración aditiva 0135: tabla nueva; downgrade elimina únicamente esa tabla de resultados regenerables. No modifica hechos financieros ni transacciones existentes.

## Verificación local

- Vitest: `tests/unit/research/management-alignment.test.tsx`.
- Pytest: `tests/test_management_alignment.py`, más regresiones de persistencia, monitor, parser, DEI y capital.
- Guards: `scripts/management-alignment-guard.test.ts` y el contrato de seis actores de computed. Bundle completo `npm run test:guards`.
- Cobertura medida solo sobre los módulos nuevos, no una afirmación de cobertura global.
- Mutantes observados en rojo uno a uno: signo de dilución invertido; SBC sin fuente; fallback diluido roto; fallback DEI roto; venta planificada tratada como discrecional; desconocido tratado como false; grant incluido en flujo; recompras ausentes convertidas a cero; enlace de cifra eliminado. Además, tres mutantes de guard: llamada SEC desde el job nuevo, dependencia de tesis y fallback roto.
- Render real del componente con CSS del repo inspeccionado a 390 y 1280 px. Es evidencia local con fixtures, no una sesión de producción ni una prueba de ingesta real actual.

No merge ni deploy en esta entrega: revisión por SHA exacta antes de integrar.

## Correcciones de auditoría

- Solo `split` y `reverse_split` impiden comparar saldos. Un `ticker_change` no es un split ni justifica ocultar la variación. Test ORM rojo antes, verde después, y contrapruebas para ambos tipos de split.
- La reingesta del mismo fingerprint enriquece `alignment_10b5_1: null` con true/false explícitos por transacción. No pisa un valor conocido con ausencia de marca, no duplica filas, no cambia `rule_10b5_1` ni dispara descargas. Test rojo antes con clave null presente, no eliminada.
