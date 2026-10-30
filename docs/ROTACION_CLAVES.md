# Rotación de claves filtradas (lista exacta)

> Documento para Nico. Aquí **no hay ningún valor de clave**: solo el proveedor,
> el nombre de la variable y dónde quedó en el historial. Los valores siguen
> legibles en GitHub para cualquiera (`git log -p`), porque el repositorio es
> público. Borrar un fichero no borra su historial.

**Qué protege de verdad: rotar.** Purgar el historial es opcional (sección 4),
no sustituye a la rotación y es decisión tuya. Este documento **no** reescribe
nada. Complementa a `docs/seguridad/rotacion-de-claves.md` (PR #2269, que
añade gitleaks a CI y pre-commit); aqui se separan las comprobaciones actuales de las referencias historicas.

## 0. Estado comprobado y limites (29-oct-2026, 16:48 CET)

La lista anterior mezclaba posibles hallazgos historicos con credenciales
vigentes. **No es un inventario confirmado de nueve credenciales expuestas.**
No se deben rotar todas por rutina ni invalidar sesiones sin comprobar primero
el valor afectado, sus consumidores y el reemplazo.

| Elemento | Evidencia disponible | Que queda pendiente |
|---|---|---|
| Better Auth | Comparacion privada de tres asignaciones historicas de `docker.env.example` (`e7e5597b`) y `.env.bak` (`70098ea9`) con `BETTER_AUTH_SECRET` en la configuracion Production actual de Vercel: ninguna coincide. No se imprimieron valores ni se intentaron falsificar sesiones. | La configuracion de proyecto no acredita por si sola cada despliegue antiguo, Preview, copia local o consumidor externo. No se ha hecho rotacion en esta revision. |
| Marketstack | `MARKETSTACK_API_KEY` no figura en las variables actuales del proyecto Vercel. Quitar una variable no revoca la clave del proveedor. | Revocacion en el proveedor sin acreditar. No hay login utilizable disponible; el intento de abrir el panel termino en timeout. No se ha reseteado ninguna clave. |
| MongoDB Atlas | La consola redirige a login; no hay sesion de administrador accesible en la comprobacion de hoy. | No se ha revisado Database Access ni Activity Feed ni cambiado usuarios. Una URI de conexion no sustituye el acceso al panel. |
| Gemini y otros proveedores | El informe operativo del 28-oct indicaba tres claves historicas Gemini rechazadas y la contraseña historica Atlas rechazada; no encontro valores reales de Finnhub/FMP/Twelve Data/Alpha Vantage/Polygon en su barrido. | Es un informe previo, no una nueva prueba de validez ni un inventario exhaustivo reproducido el 29-oct. No presentar esos proveedores como exposiciones confirmadas sin recuperar evidencia concreta. |
| Barrido gitleaks del historial completo (30-oct-2026) | 10.825 commits con reglas por defecto + reglas propias, valores redactados y solo comparados en privado (forma, longitud, entropia; ninguno probado contra el proveedor). Valores con forma de clave real, no marcadores: **Gemini/Google** 3 claves distintas (`RESUMEN_FINAL.md` e `INSTRUCCIONES_DESPLIEGUE.md` en `574df4ec`; `docker.env.example` en `e7e5597b`; `.env.bak` en `70098ea9`); **MongoDB Atlas** contrasena de usuario en la URI del cluster (`INSTRUCCIONES_DESPLIEGUE.md`, `574df4ec` y `97cf1049`); **Finnhub** (`.env.bak`, `docker.env.example`, `RESUMEN_FINAL.md`), **FMP**, **Twelve Data**, **Alpha Vantage**, **Marketstack** y **Better Auth** (`.env.bak` `70098ea9`, `docker.env.example` `e7e5597b`). **Polygon** solo aparece como marcador. Ningun valor real sigue en el arbol actual de `main`. | Corrige la fila anterior: Finnhub, FMP, Twelve Data, Alpha Vantage y Marketstack si tienen valores no ficticios en el historial. Validez sin comprobar (probar una clave filtrada contra el proveedor no se hizo). |

No se han cambiado ni revocado credenciales en esta revision. Nunca guardar
valores en este documento, capturas, logs o mensajes. Los secretos nuevos se
recogen y guardan en el gestor de secretos.

## 1. Referencias historicas por revisar

Estas referencias sirven para localizar evidencia, no prueban que el valor
siga activo ni que todos los proveedores listados hayan tenido una clave real:

- MongoDB: `INSTRUCCIONES_DESPLIEGUE.md`, commit `97cf1049`.
- Better Auth: `docker.env.example`, `e7e5597b`; `.env.bak`, `70098ea9`.
- Gemini (3 claves): `RESUMEN_FINAL.md` / `INSTRUCCIONES_DESPLIEGUE.md`,
  `574df4ec`; `docker.env.example`, `e7e5597b`; `.env.bak`, `70098ea9`.
- Finnhub, FMP, Twelve Data, Alpha Vantage, Marketstack: `.env.bak`, `70098ea9`;
  `docker.env.example`, `e7e5597b` (Finnhub tambien en `RESUMEN_FINAL.md`, `574df4ec`).
- Polygon: solo marcadores; no hay clave que rotar.

Si se confirma una credencial expuesta activa, primero inventariar consumidores.
Crear y probar su reemplazo en ellos antes de revocar la anterior. Si ya esta
rechazada, registrar la evidencia y revisar el acceso del proveedor cuando sea
posible; no rotar otra credencial distinta solo por compartir nombre de variable.

**No hace falta rotar** (revisados, son valores ficticios o de desarrollo local):
`RESEARCH_AUTH_SECRET` de `ci.yml` y `playwright.config.ts` (secreto de tests de CI),
`MINIO_*` / `drillpassword` de `restore-drill.yml`, los `DATABASE_URL` y
`LANGFUSE_INIT_USER_PASSWORD` de `docker-compose.yml` (por defecto de desarrollo
local; cámbialos solo si algún día expones ese compose a internet), los
marcadores `genera-…` / `cambia…` de `.env.production.example` y `README.md`.

## 2. Pasos por proveedor

Regla común: **crea la nueva → cámbiala en todos los entornos (sección 3) →
redespliega → comprueba que funciona → revoca la antigua.**

### 1. MongoDB Atlas (`MONGODB_URI`)
1. cloud.mongodb.com → tu proyecto → *Security → Database Access*.
2. Edita el usuario que aparece en la URI filtrada → *Edit Password* → genera una
   contraseña nueva (o crea un usuario nuevo y **borra** el antiguo).
3. *Security → Network Access*: quita `0.0.0.0/0` si está; deja solo las IPs de
   Render/Vercel/tu servidor (o usa el acceso por integración de Vercel).
4. Revisa *Project → Activity Feed* / logs de acceso por si hubo conexiones raras.
5. No borres usuarios ni clusters por su nombre antiguo. Verifica consumidores,
   dependencias y backup; cualquier retirada requiere un plan propio.

### 2. Better Auth (`BETTER_AUTH_SECRET`)
1. Si se confirma que el secreto activo esta expuesto, genera y guarda uno nuevo en el gestor de secretos.
2. Ponlo en Vercel (y en tu `.env` local). **Efecto:** todas las sesiones abiertas
   se invalidan y hay que volver a iniciar sesión. Es lo esperado.
3. Si produccion usa otro valor, no invalides sesiones por rutina. Comprueba
   que el valor historico no sigue en despliegues accesibles u otros consumidores.

### 3. Google / Gemini (`GEMINI_API_KEY`, 3 claves)
1. aistudio.google.com → *API keys* (o console.cloud.google.com → *APIs y
   servicios → Credenciales*). Busca las tres claves antiguas: pueden estar en
   proyectos distintos.
2. Crea **una** clave nueva con restricción de API (solo *Generative Language API*)
   y, si es posible, sin facturación (el producto exige modelos de 0 €).
3. **Borra** las tres antiguas. Mira en *Facturación* que no haya consumo extraño.

### 4. Finnhub (`FINNHUB_API_KEY`)
finnhub.io → *Dashboard* → regenera la API key (la anterior deja de valer).
Se usa en Vercel (rutas de Next) **y** en Render (`render.yaml`).

### 5. Financial Modeling Prep (`FMP_API_KEY`)
site.financialmodelingprep.com → *Dashboard → API Keys* → regenerar.

### 6. Twelve Data (`TWELVE_DATA_API_KEY`)
twelvedata.com → *Account → API Keys* → regenerar o revocar.

### 7. Alpha Vantage (`ALPHA_VANTAGE_API_KEY`)
No hay panel para revocar: pide una clave nueva en alphavantage.co/support y deja
de usar la antigua (si quieres anularla, escribe a su soporte con la antigua).

### 8. Polygon.io / Massive (`POLYGON_API_KEY`)
Dashboard → *Keys* → crea una nueva y **borra** la antigua.

### 9. Marketstack (`MARKETSTACK_API_KEY`)
marketstack.com → *Dashboard* → *Reset API Access Key*.

Si alguna de 6–9 ya no se usa en la app, basta con revocarla y no poner ninguna nueva.

## 3. Dónde cambiar cada variable

| Variable | Vercel (frontend Next) | Render (data-engine) | Servidor propio / docker |
|---|---|---|---|
| `MONGODB_URI` | sí | — | `docker.env` |
| `BETTER_AUTH_SECRET` | sí | — | `docker.env` |
| `FINNHUB_API_KEY` | sí | sí (`render.yaml`) | `docker.env` |
| `ALPHA_VANTAGE_API_KEY` | sí, si la usas | — | `docker.env` |
| `GEMINI_API_KEY`, `FMP_API_KEY` | — | sí, si están configuradas | `docker.env` |

- **Vercel:** Project → *Settings → Environment Variables* (Production **y**
  Preview) → guardar → *Deployments → Redeploy* del último de `main`.
- **Render:** servicio → *Environment* → guardar (redespliega solo).
- **docker compose:** edita `docker.env` y `docker compose --env-file docker.env up -d`.
- Comprueba: login en la web (Better Auth + Mongo), una ficha con cotización
  (Finnhub) y los logs del data-engine sin errores 401/403 de proveedores.

## 4. (Opcional) Purgar el historial con `git filter-repo`

**Decisión tuya. Nadie la ha ejecutado.** Hazla, si la haces, **después** de rotar.

Consecuencias: cambian los hashes de todos los commits, hay que hacer
`git push --force` a `main`, se rompen los forks, los clones y las PRs abiertas
(habría que cerrarlas o rehacerlas), y las copias que ya existan fuera (forks,
clones, cachés de GitHub, archivos de terceros) **no** se borran. Por eso rotar
es lo que de verdad protege; purgar solo reduce la exposición futura.

```bash
# 1) Congela el repo: sin merges mientras dura (avisa al capitán de merges).
# 2) Clon espejo nuevo, nunca tu copia de trabajo
git clone --mirror https://github.com/nicogarrr/GerarAI.git GerarAI-purga.git
cd GerarAI-purga.git
pip install git-filter-repo

# 3a) Ficheros que ya no existen en main: fuera de todo el historial
git filter-repo --invert-paths \
  --path .env.bak --path RESUMEN_FINAL.md --path INSTRUCCIONES_DESPLIEGUE.md

# 3b) docker.env.example SÍ existe hoy: sustituye solo los valores.
#     Crea ../reemplazos.txt (fuera del repo, no lo subas) con una línea por
#     valor filtrado, en formato   VALOR_ANTIGUO==>REDACTED
#     (copia los valores de tus paneles o de `git show e7e5597b:docker.env.example`).
git filter-repo --replace-text ../reemplazos.txt

# 4) Verifica antes de publicar
gitleaks git . --redact --no-banner          # debe salir limpio
git log --all -p | grep -c 'mongodb+srv://' # revisa a mano lo que quede

# 5) Publica (reescritura total)
git push --force --mirror
```

Después:
- GitHub no deja reescribir `refs/pull/*`: esos commits antiguos siguen
  accesibles por hash. Pide a **GitHub Support** que purgue las vistas en caché
  y las referencias de PRs (formulario *Remove sensitive data*).
- Todos los clones (incluidos los de los agentes) deben volver a clonarse;
  un `git pull` normal reintroduciría el historial viejo.
- Activa en GitHub *Settings → Code security → Secret scanning* y *Push protection*.

## 5. Para que no vuelva a pasar

- PR #2269: gitleaks en CI (commits nuevos de cada PR y push a `main`) y en
  pre-commit (`pip install pre-commit && pre-commit install`).
- `.gitleaks.toml` trae dos reglas propias para lo que gitleaks no vio aquí:
  URIs de MongoDB con contraseña y `BETTER_AUTH_SECRET=` con un valor que no sea
  un marcador (test: `data-engine/tests/test_gitleaks_custom_rules.py`).
- Los `.env*` reales nunca se versionan; solo los `*.example` con marcadores.
