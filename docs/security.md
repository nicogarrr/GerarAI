# Prácticas y Arquitectura de Seguridad en GerarAI

Fulfills: VAL-DOC-007

Este documento describe la arquitectura de seguridad, defensas en profundidad y directrices para colaboradores en GerarAI.

---

## 1. Arquitectura de Seguridad y Modelo de Amenazas

GerarAI opera con una arquitectura desacoplada:
- **Frontend**: Next.js (App Router) en Edge / Node.js, gestionando la interfaz de usuario, autenticación (Better-Auth) y sesiones seguras con cookies HttpOnly/SameSite.
- **Backend (Research Engine)**: FastAPI en Python 3.12, sirviendo análisis fundamental, valuaciones de cartera, integración con mercados y RAG.
- **Canal de Identidad Criptográfico**: Las comunicaciones mutantes entre Next.js y FastAPI se autentican mediante firma HMAC (`X-CavaAI-Signature`) con nonces de un solo uso y expiración temporal (anti-replay y anti-tampering).

```
[ Navegador ] ──(HTTPS + Cookies HttpOnly + CSRF)──> [ Next.js Frontend ]
                                                            │
                                              (HMAC firmado + Nonce)
                                                            ▼
                                                   [ FastAPI Backend ]
                                                     ├── CSRFMiddleware
                                                     ├── Tenancy & Isolation
                                                     ├── Database (Postgres)
                                                     └── Audit Logs (Inmutable)
```

---

## 2. Gestión Segura de Credenciales

1. **Cero Secretos Hardcodeados**: Ninguna contraseña, clave privada, ni token de API se almacena en el código fuente. Las suites de prueba `test_no_hardcoded_credentials.py` verifican continuamente el repositorio.
2. **Carga desde Variables de Entorno**: Todas las credenciales sensibles provienen de variables de entorno seguras (`ADMIN_EMAIL`, `ADMIN_PASSWORD`, `DATABASE_URL`, `BETTER_AUTH_SECRET`, etc.).
3. **Rechazo de Contraseñas Débiles**: El sistema bloquea contraseñas comunes (`admin`, `password123`, etc.) y exige un mínimo de 12 caracteres combinando mayúsculas, minúsculas y caracteres no alfabéticos.
4. **Inicialización de Administrador Segura**: El script `data-engine/scripts/create_initial_admin.py` permite crear o inicializar la cuenta administrativa sin exponer claves en logs ni en historial de terminales.

---

## 3. Validación de Entradas y Protección contra Inyecciones

1. **Prevención de Inyección SQL**:
   - Todas las consultas a la base de datos utilizan expresiones parametrizadas mediante SQLAlchemy 2.0 (`select(...)`, `where(...)`).
   - La búsqueda global sanitiza los términos de entrada antes de generar filtros de texto.
   - Verificado contra 13 variantes de payloads maliciosos en `test_sql_injection_search.py`.
2. **Restricciones a Nivel de Base de Datos**:
   - Campos críticos marcados como `NOT NULL`.
   - Restricciones `CHECK` para garantizar que cantidades, precios y comisiones sean estrictamente no negativos (`quantity >= 0`, `price >= 0`, `fees >= 0`).
   - Restricciones `UNIQUE` por tenant (`portfolios.name`, `tenants.external_id`).

---

## 4. Protección contra Server-Side Request Forgery (SSRF)

Los endpoints que descargan contenido externo (como importación de documentos o fuentes financieras):
1. **Fijación de IP (IP Pinning)**: Implementado en `data-engine/app/services/public_fetch.py`. Resuelve la dirección IP del host remoto antes de iniciar la conexión HTTP.
2. **Bloqueo de Rangos Privados y Loopback**: Se rechazan inmediatamente conexiones dirigidas a:
   - Loopback (`127.0.0.0/8`, `localhost`, `::1`).
   - Redes privadas RFC 1918 (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`).
   - Metadatos de la nube (`169.254.169.254`).
   - Formas alternativas (decimales, hex, IPv6 embebida, `nip.io`).
3. **Límite de Redirecciones y Tamaño**: Máximo 3 redirecciones validadas individualmente y límite estricto de bytes en stream para evitar ataques de agotamiento de memoria.
4. Verificado exhaustivamente con servidor canario en `test_ssrf_url_params.py` (39 pruebas).

---

## 5. Protección contra Cross-Site Request Forgery (CSRF)

1. **Middleware CSRF Activo**: `CSRFMiddleware` en `data-engine/app/core/csrf.py` intercepta todos los métodos mutantes (`POST`, `PUT`, `DELETE`, `PATCH`).
2. **Token Criptográfico**:
   - Los clientes obtienen un token firmado mediante `GET /api/csrf-token`.
   - El token incluye timestamp y firma criptográfica contra la clave secreta del servidor.
   - Peticiones sin token o con token alterado reciben `403 Forbidden`.
3. Verificado en `test_csrf_protection.py`.

---

## 6. Cabeceras de Seguridad HTTP

Configuradas a través de `next.config.ts`, `middleware.ts` y el middleware de FastAPI:

| Cabecera | Valor | Propósito |
| :--- | :--- | :--- |
| `Content-Security-Policy` | `default-src 'self'; script-src 'self' 'nonce-...' 'strict-dynamic'` | Mitigación de XSS estricto con nonce dinámico por petición |
| `X-Frame-Options` | `DENY` / `SAMEORIGIN` | Protección total contra Clickjacking |
| `X-Content-Type-Options` | `nosniff` | Previene que el navegador infiera tipos MIME |
| `Strict-Transport-Security` | `max-age=63072000; includeSubDomains; preload` | Fuerza el uso de HTTPS en navegadores modernos |
| `Referrer-Policy` | `strict-origin-when-cross-origin` | Limita la exposición de URLs sensibles en peticiones salientes |
| `Permissions-Policy` | `camera=(), microphone=(), geolocation=()` | Bloquea el acceso no autorizado a APIs del dispositivo |

Verificado en `test_security_headers.py`.

---

## 7. Registro de Auditoría Inmutable (Append-Only)

1. **Tabla de Auditoría**: Las operaciones críticas (creación de carteras, bajas, modificaciones de permisos, operaciones por lotes) se registran en `audit_logs`.
2. **Inmutabilidad Garantizada**:
   - El listener `_assign_tenant_to_new_rows` en `app/core/database.py` intercepta el ciclo de vida de la sesión SQLAlchemy.
   - Si se detecta un intento de `UPDATE` o `DELETE` sobre una fila de `AuditLog`, la operación se aborta con `RuntimeError`.
3. Verificado en `test_database_audit_log.py`.

---

## 8. Proceso de Notificación de Vulnerabilidades

Si descubres una vulnerabilidad de seguridad en GerarAI:
1. **No abras un issue público**: Para proteger a los usuarios, no divulgues la vulnerabilidad públicamente.
2. **Contacto**: Envía un informe detallado por correo a `security@gerarai.com` (o al contacto de seguridad del repositorio).
3. **Información requerida**:
   - Descripción de la vulnerabilidad y componentes afectados.
   - Pasos detallados para reproducir o prueba de concepto (PoC).
   - Impacto estimado sobre la confidencialidad, integridad o disponibilidad.
4. **Tiempo de respuesta**: El equipo confirmará la recepción en un plazo máximo de 48 horas y proporcionará actualizaciones periódicas hasta su resolución.
