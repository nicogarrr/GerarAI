# Rotación de claves filtradas en el historial de Git

**Estado:** el repositorio es público y el historial de Git (commits de
noviembre–diciembre de 2025) contiene claves de API con aspecto real en
ficheros que hoy ya no existen en `main` (`.env.bak`, `docker.env.example`,
`RESUMEN_FINAL.md`, `INSTRUCCIONES_DESPLIEGUE.md`). Borrar el fichero no las
borra: cualquiera puede leerlas con `git log -p` o en GitHub.

**Lo que de verdad protege es rotar.**

## 0. Estado verificado (2026-10-28)

Verificacion de las claves del historial contra cada proveedor (trufflehog
--only-verified + llamadas de solo lectura):

| Clave | Estado 2026-10-28 | Accion |
|---|---|---|
| Marketstack (`b384...8b41`, en `.env.bak` y `docker.env.example`, commits dic 2025) | **SIGUE ACTIVA** (autentica contra la API) | **Rotar YA**: marketstack.com → Dashboard → Reset API access key |
| Gemini ×3 (`AIzaSyD_…`, `AIzaSyB49…`, `AIzaSyCqw…`) | Muertas (HTTP 400) | Ninguna |
| MongoDB Atlas (`mongodb+srv://…@jlcavaai.sj0wk0l.mongodb.net`, INSTRUCCIONES_DESPLIEGUE.md) | Password muerta (bad auth); el cluster sigue existiendo | Revisar usuarios y logs de acceso de Atlas por precaucion |
| Finnhub, FMP, Twelve Data, Alpha Vantage, Polygon | No se encontraron claves suyas en el historial (trufflehog + gitleaks, todos los refs) | Ninguna por ahora |
 Purgar el historial es opcional y no
sustituye a la rotación (cualquier clon o fork anterior conserva las claves).

## 1. Rotar cada proveedor (hoy)

Para cada uno: genera una clave nueva, sustitúyela en todos los entornos y
**revoca la antigua**. No se ha comprobado si las claves antiguas siguen activas;
trátalas como comprometidas igualmente.

| Proveedor | Dónde se rota (a alto nivel) | Variable(s) en GerarAI |
|---|---|---|
| Finnhub | finnhub.io → Dashboard → API key → regenerar | `FINNHUB_API_KEY` |
| Financial Modeling Prep | site.financialmodelingprep.com → Dashboard → API Keys → regenerar | `FMP_API_KEY` |
| Twelve Data | twelvedata.com → Account → API Keys → regenerar/revocar | `TWELVE_DATA_API_KEY` (o equivalente en tu `.env`) |
| Alpha Vantage | No hay panel: solicita una clave nueva en alphavantage.co/support y deja de usar la antigua | `ALPHA_VANTAGE_API_KEY` (o equivalente) |
| Polygon (Massive) | polygon.io → Dashboard → Keys → crear nueva y borrar la antigua | `POLYGON_API_KEY` (o equivalente) |
| Marketstack | marketstack.com → Dashboard → Reset API access key | `MARKETSTACK_API_KEY` (o equivalente) |
| Google (Gemini / Cloud) | console.cloud.google.com → APIs y servicios → Credenciales (o aistudio.google.com → API keys) → borrar la clave y crear otra **con restricciones** de API | `GEMINI_API_KEY` / `GOOGLE_API_KEY` (según tu `.env`) |

Los nombres de variable exactos están en `.env.production.example` y
`docker.env.example`; si alguna variable ya no se usa, basta con revocar la clave.

## 2. Actualizar los entornos

1. `.env` / `docker.env` locales (nunca se versionan).
2. **Vercel** → Project → Settings → Environment Variables (Production y Preview) → *Redeploy*.
3. **Render** → servicio → Environment → guardar (redespliega solo).
4. Servidor propio (Oracle / docker compose): edita `docker.env` y
   `docker compose --env-file docker.env up -d` para recargar.
5. Comprueba en los logs del data-engine que los conectores responden.

## 3. Evitar que vuelva a pasar

- CI ejecuta **gitleaks** sobre los commits nuevos de cada PR y push a `main`
  (`.github/workflows/gitleaks.yml`, configuración en `.gitleaks.toml`).
- En local: `pip install pre-commit && pre-commit install` activa el hook de
  gitleaks (`.pre-commit-config.yaml`), que bloquea el commit antes de que la
  clave salga de tu máquina.
- En GitHub: Settings → Code security → activa *Secret scanning* y *Push protection*.

## 4. (Opcional) Purgar el historial con git filter-repo

**Decisión tuya.** Reescribe todo el historial: cambian los hashes de todos
los commits, se rompen forks, clones y PRs abiertas, y hay que hacer
`git push --force` a `main`. No elimina las copias que ya existan fuera
(forks, clones, cachés). Si se hace, que sea **después** de rotar.

```bash
# En un clon espejo nuevo, nunca en tu copia de trabajo
git clone --mirror https://github.com/nicogarrr/GerarAI.git
cd GerarAI.git
pip install git-filter-repo
# Opción A: eliminar los ficheros del historial
git filter-repo --invert-paths --path .env.bak --path RESUMEN_FINAL.md --path INSTRUCCIONES_DESPLIEGUE.md
# Opción B: sustituir valores concretos (un valor por línea en replacements.txt: CLAVE==>REDACTED)
git filter-repo --replace-text ../replacements.txt
git push --force --mirror
```

Después: pide a GitHub Support que purgue las vistas en caché de los commits
antiguos, y avisa a quien tenga clones para que los vuelva a clonar.
