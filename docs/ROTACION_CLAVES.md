# Rotación de claves filtradas (lista exacta)

> Documento para Nico. Aquí **no hay ningún valor de clave**: solo el proveedor,
> el nombre de la variable y dónde quedó en el historial. Los valores siguen
> legibles en GitHub para cualquiera (`git log -p`), porque el repositorio es
> público. Borrar un fichero no borra su historial.

**Qué protege de verdad: rotar.** Purgar el historial es opcional (sección 4),
no sustituye a la rotación y es decisión tuya. Este documento **no** reescribe
nada. Complementa a `docs/seguridad/rotacion-de-claves.md` (PR #2269, que
añade gitleaks a CI y pre-commit); aquí está la lista concreta y verificada.

## 0. Cómo se ha obtenido la lista

- Historial completo (5.954 commits, todas las ramas) escaneado con **gitleaks**
  (reglas por defecto) y además con una búsqueda propia de asignaciones
  `*_SECRET / *_TOKEN / *_PASSWORD / *_API_KEY` y de URLs con usuario y
  contraseña (`mongodb+srv://`, `postgresql://`, `redis://`…), porque gitleaks
  **no detectó** dos de ellas (el secreto de Better Auth y la URI de MongoDB).
- Árbol de trabajo actual de `main` (27-oct-2026): **ninguna clave real**. Los 17
  avisos de gitleaks son falsos positivos (secretos de prueba en `data-engine/tests`,
  claves de diccionario en `MarketRegime.tsx` y `source_hierarchy_service.py`,
  el marcador de `GARAGE_ACCESS_KEY` en `.env.production.example`).
- **No se ha comprobado** si cada clave antigua sigue activa (probarla sería usarla).
  Trátalas todas como comprometidas.

## 1. Claves que hay que rotar (9 credenciales, 11 valores)

| # | Proveedor | Variable | Valores distintos | Dónde aparece en el historial |
|---|---|---|---|---|
| 1 | **MongoDB Atlas** (usuario y contraseña de la base de datos, cluster `JLCavaAI`) | `MONGODB_URI` | 1 | `INSTRUCCIONES_DESPLIEGUE.md` (commit `97cf1049`, 1-nov-2025) |
| 2 | **Better Auth** (firma las sesiones de login) | `BETTER_AUTH_SECRET` | 1 | `docker.env.example` (`e7e5597b`, 21-dic-2025) y `.env.bak` (`70098ea9`, 22-dic-2025) |
| 3 | **Google / Gemini** | `GEMINI_API_KEY` | **3** claves distintas | (a) `RESUMEN_FINAL.md` e `INSTRUCCIONES_DESPLIEGUE.md` (`574df4ec`, 1-nov-2025); (b) `docker.env.example` (`e7e5597b`); (c) `.env.bak` (`70098ea9`) |
| 4 | **Finnhub** | `FINNHUB_API_KEY` | 1 | `RESUMEN_FINAL.md` (`574df4ec`), `docker.env.example` (`e7e5597b`), `.env.bak` (`70098ea9`) |
| 5 | **Financial Modeling Prep** | `FMP_API_KEY` | 1 | `docker.env.example` (`e7e5597b`), `.env.bak` (`70098ea9`) |
| 6 | **Twelve Data** | `TWELVE_DATA_API_KEY` | 1 | ídem |
| 7 | **Alpha Vantage** | `ALPHA_VANTAGE_API_KEY` | 1 | ídem |
| 8 | **Polygon.io** (hoy Massive) | `POLYGON_API_KEY` | 1 | ídem |
| 9 | **Marketstack** | `MARKETSTACK_API_KEY` | 1 | ídem |

Prioridad: **1 y 2 primero** (dan acceso a datos y cuentas de usuarios), luego 3
(Gemini puede generar coste si la clave tiene facturación) y 4, después el resto.

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
5. Si ese cluster ya no se usa (era del nombre antiguo, CavaAI), lo más limpio
   es **borrar el usuario o el cluster** entero.

### 2. Better Auth (`BETTER_AUTH_SECRET`)
1. Genera uno nuevo: `openssl rand -base64 32`.
2. Ponlo en Vercel (y en tu `.env` local). **Efecto:** todas las sesiones abiertas
   se invalidan y hay que volver a iniciar sesión. Es lo esperado.
3. Si producción ya usaba otro valor distinto del filtrado, rótalo igualmente:
   no cuesta nada y elimina la duda.

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
- Seguimiento recomendado: añadir a `.gitleaks.toml` dos reglas propias para lo
  que gitleaks no vio aquí: URIs con contraseña (`mongodb(+srv)?://usuario:contraseña@`)
  y `BETTER_AUTH_SECRET=` con un valor que no sea un marcador.
- Los `.env*` reales nunca se versionan; solo los `*.example` con marcadores.
