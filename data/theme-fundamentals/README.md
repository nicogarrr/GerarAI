# Materiales críticos: instantánea pública revisada

Actualizar con `python scripts/theme-fundamentals/import_usgs.py`, revisar el
diff y publicar mediante PR. Fuente: USGS MCS 2026, CC0, CSV con producción
minera mundial 2025 (estimada) y dependencia neta US 2025. Unidades explícitas;
convertir miles de toneladas a toneladas solo cuando la fuente lo declara.
No sumar metales, ni sumar países y totales de control. W/ausencias son null,
umbrales como >50 conservan su desigualdad. No se promete refresco automático.

World Bank Pink Sheet queda como enlace externo. La metadata de las series de
precios cita proveedores terceros y no se ha confirmado el derecho específico
de redistribución. No se copia la serie mensual ni cifras de Cameco/UxC.

El componente compartido tiene el mismo contrato que la fase Nuclear #1961;
ambas PR usan la misma integración de /temas. Al juntar las fases, conservar
este README y el README Nuclear en una versión combinada.
