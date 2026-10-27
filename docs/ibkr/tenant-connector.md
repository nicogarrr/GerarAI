# IBKR por usuario: alcance y validación

Esta versión conecta UNA cuenta Flex por tenant. No incorpora trading, transferencias, Client Portal Gateway ni credenciales de login IBKR. Token cifrado con la infraestructura Fernet existente; producción exige LLM_SETTINGS_ENCRYPTION_KEY explícita. Nunca se devuelve el token al navegador.

## Alta

En Ajustes se introduce token Flex, Query ID y cuenta esperada. Antes de guardar se descarga un informe y se verifica cuenta única, cierre reciente, OpenPositions y CashReport, columnas y fechas coherentes. La conexión no escribe posiciones hasta el paso de importar, iniciado por el mismo botón explícito 'Conectar e importar'. Ningún tenant hereda las credenciales globales.

La consulta completa se declara explícitamente: permite reconciliar solo filas ibkr_flex bajo los guards del importador. Sin esa declaración se hace merge y se muestra estado parcial: posiciones que desaparezcan del extracto no se eliminan. Un extracto incompleto no autoriza a vaciar la cartera. La casilla no convierte XML filtrado en completo; el usuario debe configurar realmente la consulta sin filtros.

El modelo de cartera no separa cuentas de bróker. Se impide cambiar la cuenta fuente incluso tras desconectar para evitar sobreescribir/agregar incorrectamente holdings. Multi-cuenta necesita un modelo de cuenta/ledger aparte.

## Sincronización

Diaria a las 06:50 UTC mediante scheduler existente. Solo conexiones habilitadas de tenants activos. Cada job tiene sesión/identidad explícitas. Descarga sin transacción DB abierta; vuelve a comprobar revisión y bloqueo de fila antes del import. Rechaza extractos anteriores al último verificado. Errores conservan datos previos y producen estado/error seguro. No se promete tiempo real ni alta inicial en menos de dos minutos.

Desconectar borra ciphertext, incrementa revisión y deshabilita siguientes importaciones. Datos previos se conservan. La fila de desconexión evita que el job global/endpoint legacy vuelva a conectar por sorpresa. La revocación del token en IBKR se hace en la web de IBKR.

## Despliegue

Migración 0089 aditiva, backup previo y revisión obligatoria. Downgrade conserva tabla/historial cifrado; no elimina datos. La adopción create_all valida forma/tipos/nullable/unicidad. El integrador debe aplicar migración antes de activar nuevas rutas/jobs. No se configura la clave de cifrado ni se copia un token real desde esta PR.

QA pendiente antes de afirmar E2E: cuenta audit con consulta real autorizada, comprobar import con informe IBKR vigente y scheduler activo, confirmar almacenamiento cifrado y unlink, evaluar latencia end-to-end y límites Vercel en requests de hasta 90 segundos. Tests locales y previews sintéticos no sustituyen esa validación.

## Investigación 27 octubre 2026

- Oficial Flex: https://www.interactivebrokers.com/docs/web-api/flex-web-service/introduction
- Token manual y cuentas vinculadas: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/enable-and-create-access-token.md
- Query manual: https://www.interactivebrokers.com/docs/web-api/flex-web-service/client-portal-configuration/create-a-flex-query
- OAuth2 no disponible a estructuras individuales: https://www.interactivebrokers.com/docs/web-api/authentication/oauth-2/register.md
- Terceros OAuth1.0a requieren alta/aprobación: https://ibkrcampus.com/docs/web-api/authentication/oauth-1a/third-party-oauth/registration-process.md
- Servicios reporting aprobados: https://ibkrguides.com/clientportal/performanceandstatements/third-party-reports.htm
- Ejemplo preset tercero: https://www.sharesight.com/partners/interactive-brokers/
- OSS evaluado: https://github.com/csingley/ibflex (Python MIT), https://github.com/0xmichalis/ibkr-flex-mcp (Flex read-only), https://github.com/kevinburke/ibclientportal (Go), https://github.com/agusalex/ghostfolio-ibkr-sync . Todos conservan token + Query ID/configuración previa. Se reutiliza el código Flex ya existente en GerarAI en vez de añadir otro runtime.

MyInvestor: no se ha encontrado API pública de cartera personal de inversión verificada. Existe PSD2 de cuenta corriente (no implica holdings): https://market.apis-i.redsys.es/psd2/xs2a/nodos/myinvestorbanco . Repos MIT https://github.com/xivira/miai-api y https://github.com/SergioMorchon/your-investor usan login/API privada; el primero incluye órdenes, SMS/dispositivo, no token read-only garantizado. No incorporados. Export oficial: PDF posiciones/extracto y Excel efectivo: https://myinvestor.es/ayuda/preguntas-frecuentes/cuentas/ . No se confunde Excel de efectivo con cartera completa. Captura-import es trabajo independiente.
