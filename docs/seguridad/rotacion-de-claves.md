# Rotación de claves filtradas en el historial de Git

**Estado actualizado (29-oct-2026):** el documento original no acreditaba
la exposicion de todos los proveedores enumerados. El inventario y sus limites
estan en [ROTACION_CLAVES.md](../ROTACION_CLAVES.md#0-estado-comprobado-y-limites-29-oct-2026-1648-cet).
No contiene valores de secretos.

## 1. Verificar antes de rotar

- Confirmar que existe un valor real expuesto y distinguirlo del secreto activo.
- Inventariar consumidores antes de cambiar o revocar nada.
- Crear y probar un reemplazo en todos los consumidores antes de revocar el
  anterior. No invalidar sesiones ni borrar usuarios o clusters por rutina.
- Recoger y guardar secretos en el gestor de secretos, nunca en chat o logs.
- Registrar fecha, alcance y resultado. Una variable eliminada no prueba la
  revocacion del proveedor; una configuracion actual no prueba cada despliegue.

La comparacion privada del 29-oct no encontro coincidencias entre el secreto
Better Auth de Production en Vercel y tres asignaciones historicas revisadas.
Marketstack no esta en las variables actuales de Vercel; falta acreditar su
revocacion. La consola Atlas requiere login. No se rotaron credenciales en esta
revision. Los detalles y limites estan en el inventario enlazado.

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
