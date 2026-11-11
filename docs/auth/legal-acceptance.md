# Aceptación en el alta

El alta por email exige `acceptTerms === true` tanto en la acción servidor como en el endpoint HTTP. No se aceptan cadenas, números ni valores ausentes. El checkbox cubre los términos y la privacidad ya enlazados en el formulario.

El hook previo a insertar el usuario guarda en el mismo documento Mongo:
- `termsVersion`: SHA-256 del texto de términos publicado en español e inglés.
- `privacyVersion`: SHA-256 del texto de privacidad publicado en español e inglés.
- `legalAcceptedAt`: fecha del servidor (Date UTC), no enviada por el navegador.

Los tres campos son opcionales, privados en la respuesta de BetterAuth y no editables desde `/update-user` ni desde el alta. Las versiones identifican contenido, no declaran que los textos estén validados jurídicamente. No se cambia ningún texto legal.

No se hace backfill: una cuenta existente sin estos campos conserva evidencia desconocida. Login y aprobación no fuerzan ni inventan aceptación. Un alta duplicada no modifica la evidencia anterior. La creación interna tampoco equivale a una aceptación.

## Compatibilidad y vuelta atrás

Mongo no necesita migración de esquema ni índices. Volver al código anterior deja campos adicionales ignorados; no borrar evidencia recogida. Si en el futuro se exige reaceptación a cuentas existentes, requiere un flujo explícito independiente. No se deben sustituir las fechas ausentes por la fecha de registro.

## Pruebas

`tests/unit/auth/legal-acceptance.test.ts` ejecuta el pipeline HTTP real de BetterAuth con el adaptador oficial en memoria, sin correo/red/Mongo de producción. Cubre rechazos antes de insertar, persistencia, campos falsificados, cuenta antigua, login y no alteración posterior. La acción servidor y los guards existentes se prueban aparte.
