# Avisos DCA globales por usuario

- La watchlist conserva el veredicto en tarjetas/tabla. El bloque inferior es un disclosure nativo cerrado con histórico de watchlist y cartera, cinco empresas por página, y enlace a Ajustes.
- `/api/settings/dca` GET/PUT exige identidad de tenant. Cada usuario guarda subida y bajada por separado, de 1X a 4X; 0 desactiva esa dirección.
- Valores efectivos iniciales: subida 3X, bajada 1X. No hace falta guardar para que se apliquen cuando existe contexto de tenant.
- Subida: nivel nuevo mayor o igual que el umbral. Bajada: nivel nuevo menor o igual que el umbral. Ejemplos iniciales: 2→3, 3→4 y 2→1 avisan; 1→2, 3→2, 4→3 no. Primera evaluación y nivel sin cambio no avisan.
- Los recortes conservan su opt-in independiente del servidor. La deduplicación por mes/nivel/dirección y los canales existentes no cambian. Guardar no activa envíos desactivados en el servidor.
- Los overrides antiguos por ticker se conservan en su tabla, sin efecto para usuarios con contexto tenant. El endpoint antiguo permanece por compatibilidad; no reintroduce prioridad por ticker. Sesiones de desarrollo sin tenant conservan el contrato legacy.
- Migración 0098 añade solo `dca_alert_settings`, sin backfill ni cambios de env. Downgrade elimina solo esa tabla; no toca overrides ni señales. Volver al código anterior restaura la política legacy. Guardar valores nuevos no genera avisos retroactivos.

## Validación local

Pruebas de umbrales y desactivación, aislamiento entre dos tenants, validación HTTP, errores de identidad, persistencia, conservación de overrides y migración up/down. Pruebas del servicio con fetcher sintético verifican defaults y ajustes guardados. Frontend: disclosure, paginación, enlaces, selectores globales, guardado y fallo; contratos OpenAPI generados.

Capturas y axe a 390px usan los componentes y CSS reales con datos sintéticos y dobles de navegación/acciones en un montaje local. No son capturas de producción. No se probó entrega real de correo/Telegram, datos de la cuenta, iPhone/Safari, despliegue ni build completo de Next.
