# Runbook del piloto MinIO -> Garage (bucket `research`)

Runbook operativo del piloto de migracion. La estrategia y el por que estan en
[OBJECT_STORAGE_MIGRATION.md](OBJECT_STORAGE_MIGRATION.md); la copia la hace
`data-engine/scripts/storage/migrate_minio_to_garage.py`. Este documento solo
describe pasos: no ejecuta nada por si solo. Coste: 0 EUR (Garage es AGPL y
convive con MinIO en la misma VM).

## Prerrequisito: credenciales exportadas en la shell del host

Los comandos de abajo interpolan `$MINIO_ROOT_USER`, `$MINIO_ROOT_PASSWORD`,
`$GARAGE_ACCESS_KEY` y `$GARAGE_SECRET_KEY` **en la shell del host, antes de
`docker compose exec/run`**. Docker compose tampoco lee `.env.production` por
su cuenta (solo lee `.env` y no usamos `--env-file`): toda la interpolacion
`${...}` del compose sale del entorno de la shell. Sin este paso, las
credenciales llegan vacias y el script sale con codigo 2.

```bash
# Una vez por sesion de shell, desde la raiz del checkout de produccion:
set -a
. ./.env.production
set +a

# Preflight: falla en el acto si alguna variable esta vacia o sin definir.
: "${MINIO_ROOT_USER:?falta MINIO_ROOT_USER en .env.production}" \
  "${MINIO_ROOT_PASSWORD:?falta MINIO_ROOT_PASSWORD en .env.production}" \
  "${GARAGE_ACCESS_KEY:?falta GARAGE_ACCESS_KEY en .env.production}" \
  "${GARAGE_SECRET_KEY:?falta GARAGE_SECRET_KEY en .env.production}"

# Los informes se guardan fuera del contenedor efimero (ver pasos 1 y 3).
mkdir -p "$HOME/reports-migracion"
```

**Editar `.env.production` no actualiza las variables ya exportadas** en la
shell. Tras cualquier edicion (en concreto al descomentar o comentar las
`OBJECT_STORAGE_*` en los pasos 3 y 5), hay que volver a ejecutar el
`set -a; . ./.env.production; set +a` antes del siguiente comando, o el compose
seguira interpolando los valores antiguos. Si en la sesion quedaran
`OBJECT_STORAGE_*` exportadas de una prueba anterior mientras la app debe
seguir en MinIO (pasos 1 y 2), hay que quitarlas con `unset
OBJECT_STORAGE_ENDPOINT OBJECT_STORAGE_ACCESS_KEY OBJECT_STORAGE_SECRET_KEY
OBJECT_STORAGE_REGION`.

Todos los comandos usan el proyecto `-p cavaai`, el mismo con el que esta
desplegada la app; mezclar proyectos haria que `stop`/`ps` no vieran los
contenedores reales.

## Principios (no negociables)

- **MinIO sigue vivo en todo el piloto.** No se para, no se borra, no se
  retira. Es la copia de seguridad del corte.
- **No se borra ninguna clave.** Ni en MinIO ni en Garage, en ningun paso,
  incluido el rollback. Ojo con lo que esto NO garantiza: el script puede
  **sobrescribir** una clave de destino con el contenido del origen (dejar el
  destino igual que el origen es justamente lo que hace una copia), y Garage
  no tiene versionado de objetos, asi que si una clave ya existia en destino
  con otro contenido, esa version anterior del destino se pierde. La app trata
  las claves como inmutables (nunca reescribe una clave existente), asi que en
  la practica no deberia ocurrir; la garantia "no se pierde nada" vale para el
  uso real de la app, no en abstracto.
- **Toda copia va verificada con sha256**: el script relee cada objeto en
  destino y lo compara con el origen. Un paso con errores no se da por hecho.
  La comparacion de hashes es **interna a cada ejecucion**: se hace en memoria
  y no queda persistida.
- **Los informes se conservan** (`--report`, siempre fuera del contenedor
  efimero; ver pasos 1 y 3). El informe es un JSON con las listas de claves
  (`copied`, `skipped`, `missing`, `mismatch`, `errors`), el contador
  `bytes_copied` y `ok`: **no contiene hashes ni un inventario de bytes por
  objeto**. En `--dry-run`, `bytes_copied` sale 0 porque no se escribe nada; lo
  util del dry-run es la lista de claves pendientes en `copied`. Son la
  evidencia de que el piloto fue fiel, y hay que re-medir antes del corte (las
  cifras de abajo son una foto del inicio, no un estado garantizado).

## Inventario de partida (foto del inicio del piloto)

- Bucket `research`: **5.200 objetos, 2.834.890.359 bytes (~2,83 GB)**; el
  objeto mayor ocupa ~12,9 MB.
- Fuente y fecha: medicion de solo lectura contra el MinIO de produccion el
  **2026-10-17 (~00:21 CEST)**, sin copiar ni tocar Garage. Son cifras de ese
  momento, no un contrato: el `--dry-run` del paso 1 lista en cada ejecucion
  lo que queda pendiente y el delta del paso 3 cierra cualquier diferencia.

## Paso 1 - Copia inicial idempotente (sin activar el endpoint)

La app sigue apuntando a MinIO: las `OBJECT_STORAGE_*` de `.env.production`
siguen comentadas. Garage aun no recibe trafico de la aplicacion.

```bash
# Primero en seco: no escribe nada, solo informa (bytes_copied saldra 0).
docker compose -p cavaai -f docker-compose.prod.yml exec \
  -e "SRC_ACCESS_KEY=$MINIO_ROOT_USER" -e "SRC_SECRET_KEY=$MINIO_ROOT_PASSWORD" \
  -e "DST_ACCESS_KEY=$GARAGE_ACCESS_KEY" -e "DST_SECRET_KEY=$GARAGE_SECRET_KEY" backend \
  python -m scripts.storage.migrate_minio_to_garage \
    --src-endpoint minio:9000 --dst-endpoint garage:3900 --dst-region garage \
    --bucket research --dry-run --report /tmp/migracion-dryrun.json

# Copia real. Idempotente: se puede repetir hasta que el informe salga limpio.
docker compose -p cavaai -f docker-compose.prod.yml exec \
  -e "SRC_ACCESS_KEY=$MINIO_ROOT_USER" -e "SRC_SECRET_KEY=$MINIO_ROOT_PASSWORD" \
  -e "DST_ACCESS_KEY=$GARAGE_ACCESS_KEY" -e "DST_SECRET_KEY=$GARAGE_SECRET_KEY" backend \
  python -m scripts.storage.migrate_minio_to_garage \
    --src-endpoint minio:9000 --dst-endpoint garage:3900 --dst-region garage \
    --bucket research --report /tmp/migracion-inicial.json

# El /tmp es del contenedor backend y muere con su recreate: sacar los
# informes al host nada mas terminar cada ejecucion.
docker cp cavaai-backend:/tmp/migracion-dryrun.json "$HOME/reports-migracion/"
docker cp cavaai-backend:/tmp/migracion-inicial.json "$HOME/reports-migracion/"
```

Cada objeto copiado se relee de Garage y se compara sha256 con MinIO. Codigo de
salida distinto de 0 = algo falta, difiere o no se puede leer: no seguir.

## Paso 2 - Ventana de mantenimiento: parada total de productores

Todo servicio que puede escribir en storage se para, para que no queden bytes
nuevos solo en MinIO con la base apuntando a Garage:

```bash
docker compose -p cavaai -f docker-compose.prod.yml stop \
  backend worker worker-thesis worker-kpis worker-knowledge \
  worker-alerts worker-gdelt scheduler \
  worker-official-closes worker-prices worker-externa \
  worker-finnhub worker-yahoo worker-dca-manual
```

Postgres, Redis, Qdrant, MinIO y Garage siguen arriba; la app no responde hasta
el paso 4. Confirmar con `docker compose -p cavaai -f docker-compose.prod.yml
ps` que **no queda ningun productor en pie**. No es literal que "solo quedan
los servicios de datos": **caddy tambien sigue arriba** (no escribe en
storage; dejarlo mantiene el TLS, aunque el backend parado no responde).

> **`worker-knowledge` estaba omitido en la lista original del piloto.** Hoy
> hereda `MINIO_*` del ancla `x-app-env` como el resto de servicios; se
> incluye en la parada por criterio conservador: durante la ventana su
> dependencia `backend` esta parada de todos modos, y pararlo cuesta cero y
> quita la duda. La lista de la fase 3 de OBJECT_STORAGE_MIGRATION.md quedo
> corregida en este mismo PR.

> **Mismo criterio para los seis workers de colas de datos**
> (`worker-official-closes`, `worker-prices`, `worker-externa`,
> `worker-finnhub`, `worker-yahoo`, `worker-dca-manual`): heredan `MINIO_*`
> del ancla `x-app-env` igual que el resto, asi que se detienen todos por
> criterio conservador. No se afirma que no escriban: un actor puede llegar
> al storage transitivamente (p. ej. `process_document` -> ingesta ->
> storage); la parada total es la garantia, no el analisis estatico.

## Paso 3 - Delta, verify-only y cambio de endpoint

Con los productores parados, el backend ya no sirve `exec`: se usa `run`. El
contenedor de `run --rm` se borra al terminar y su `/tmp` con el, asi que el
informe se escribe en un directorio del host montado con `--volume`; si no, la
evidencia desaparece al acabar el contenedor.

```bash
# Delta: lo escrito en MinIO desde la copia inicial.
docker compose -p cavaai -f docker-compose.prod.yml run --rm --no-deps \
  --volume "$HOME/reports-migracion:/reports" \
  -e "SRC_ACCESS_KEY=$MINIO_ROOT_USER" -e "SRC_SECRET_KEY=$MINIO_ROOT_PASSWORD" \
  -e "DST_ACCESS_KEY=$GARAGE_ACCESS_KEY" -e "DST_SECRET_KEY=$GARAGE_SECRET_KEY" backend \
  python -m scripts.storage.migrate_minio_to_garage \
    --src-endpoint minio:9000 --dst-endpoint garage:3900 --dst-region garage \
    --bucket research --report /reports/migracion-delta.json

# Verificacion final: tiene que dar ok=true, 0 faltantes, 0 diferencias, salida 0.
docker compose -p cavaai -f docker-compose.prod.yml run --rm --no-deps \
  --volume "$HOME/reports-migracion:/reports" \
  -e "SRC_ACCESS_KEY=$MINIO_ROOT_USER" -e "SRC_SECRET_KEY=$MINIO_ROOT_PASSWORD" \
  -e "DST_ACCESS_KEY=$GARAGE_ACCESS_KEY" -e "DST_SECRET_KEY=$GARAGE_SECRET_KEY" backend \
  python -m scripts.storage.migrate_minio_to_garage \
    --src-endpoint minio:9000 --dst-endpoint garage:3900 --dst-region garage \
    --bucket research --verify-only --report /reports/migracion-verify.json
```

Los informes quedan en `$HOME/reports-migracion/` del host.

- Si `--verify-only` **no** sale con 0 errores: no continuar. Levantar los
  servicios tal cual (siguen en MinIO, no se ha tocado `.env.production`) y
  revisar el informe.
- Si sale limpio: descomentar `OBJECT_STORAGE_ENDPOINT` / `OBJECT_STORAGE_ACCESS_KEY` /
  `OBJECT_STORAGE_SECRET_KEY` / `OBJECT_STORAGE_REGION` en `.env.production`
  apuntando a Garage y **recargar las variables exportadas** (`set -a; .
  ./.env.production; set +a`: editar el fichero no actualiza la shell; aqui
  el source si vale porque solo estamos poniendo valores nuevos, no quitando
  los de una exportacion anterior). Antes de recrear, confirmar el endpoint
  efectivo con el mismo preflight del paso 5, que ahora tiene que resolver el
  endpoint de Garage recien descomentado en TODOS los servicios de app:

```bash
docker compose -p cavaai -f docker-compose.prod.yml config \
  | grep -oE 'MINIO_ENDPOINT[=:][ ]?[^[:space:]]*' | sort | uniq -c
# Esperado: una sola variante con el endpoint de Garage (p. ej.
# "MINIO_ENDPOINT: garage:3900"; segun la version de compose el separador
# puede ser ":" o "="). Si sale minio:9000, el reload no se hizo o las
# OBJECT_STORAGE_* siguen comentadas: no recrear hasta que salga limpio.
```

  Con el preflight limpio, recrear:

```bash
docker compose -p cavaai -f docker-compose.prod.yml up -d --no-deps \
  backend worker worker-thesis worker-kpis worker-knowledge \
  worker-alerts worker-gdelt scheduler
```

Verificar `/health/ready` (sonda `minio` = ok; el nombre de la sonda es
historico, el backend habla S3 contra Garage).

## Paso 4 - Prueba funcional y backup desde Garage

1. **Tenant QA**: subir y leer un documento con la cuenta de pruebas
   ("Instinct Audit", marcada como test; nunca con tenants reales). Confirmar
   que el objeto aparece en Garage y no en MinIO.
2. **Backup contra Garage** con el versionado desactivado (Garage no tiene
   versionado de objetos): `--no-enable-versioning` en `backup_minio.py`, o
   `--minio-no-versioning` en `backup_all.py`, y nunca `--include-versions`.
   El manifiesto lo declara como "no gestionado". Hasta la fase de cierre, el
   campo `server_release` del manifiesto seguira diciendo MinIO: es conocido.

## Paso 5 - Rollback (si algo falla tras el corte)

El orden importa: tras el corte los productores escriben en **Garage**, asi que
hay que pararlos **antes** de la copia inversa y mantenerlos parados hasta
recrear la app contra MinIO. Copiar con productores vivos dejaria bytes nuevos
solo en Garage.

1. **Parada total de productores** (la misma lista del paso 2):

```bash
docker compose -p cavaai -f docker-compose.prod.yml stop \
  backend worker worker-thesis worker-kpis worker-knowledge \
  worker-alerts worker-gdelt scheduler
```

2. **Copia inversa verificada**: lo escrito en Garage desde el corte se copia
   de vuelta a MinIO con el mismo script, origen y destino invertidos. La
   region por defecto del script (`--dst-region garage`) solo vale para
   Garage: en la direccion inversa hay que declarar `--src-region garage` y
   `--dst-region ""` (vacia: el script la convierte en `None` y el SDK
   pregunta la region a MinIO, que la sirve; Garage en cambio necesita la
   region fija `garage`).

```bash
docker compose -p cavaai -f docker-compose.prod.yml run --rm --no-deps \
  --volume "$HOME/reports-migracion:/reports" \
  -e "SRC_ACCESS_KEY=$GARAGE_ACCESS_KEY" -e "SRC_SECRET_KEY=$GARAGE_SECRET_KEY" \
  -e "DST_ACCESS_KEY=$MINIO_ROOT_USER" -e "DST_SECRET_KEY=$MINIO_ROOT_PASSWORD" backend \
  python -m scripts.storage.migrate_minio_to_garage \
    --src-endpoint garage:3900 --src-region garage \
    --dst-endpoint minio:9000 --dst-region "" \
    --bucket research --report /reports/rollback-copia-inversa.json

# Misma exigencia que en la ida: verify-only con 0 errores antes de seguir.
docker compose -p cavaai -f docker-compose.prod.yml run --rm --no-deps \
  --volume "$HOME/reports-migracion:/reports" \
  -e "SRC_ACCESS_KEY=$GARAGE_ACCESS_KEY" -e "SRC_SECRET_KEY=$GARAGE_SECRET_KEY" \
  -e "DST_ACCESS_KEY=$MINIO_ROOT_USER" -e "DST_SECRET_KEY=$MINIO_ROOT_PASSWORD" backend \
  python -m scripts.storage.migrate_minio_to_garage \
    --src-endpoint garage:3900 --src-region garage \
    --dst-endpoint minio:9000 --dst-region "" \
    --bucket research --verify-only --report /reports/rollback-verify.json
```

   Recordar el matiz de sobrescritura de los principios: si algo hubiera
   escrito en Garage una clave ya existente con otro contenido, la copia
   inversa sobrescribe la version previa de MinIO (sin versionado en ninguno
   de los dos). Con la app real no deberia pasar, porque no reescribe claves.

3. Comentar de nuevo las `OBJECT_STORAGE_*` en `.env.production`. Ojo: el
   `set -a; . ./.env.production; set +a` habitual **no basta aqui**: el
   source solo pone o pisa variables, no borra las que el fichero ya no
   define. Como las 4 `OBJECT_STORAGE_*` quedaron exportadas con los valores
   de Garage al hacer el corte, compose las seguiria interpolando y la app
   **no** volveria a MinIO aunque el fichero este bien. Hay que quitarlas de
   la shell **antes** de recargar:

```bash
unset OBJECT_STORAGE_ENDPOINT OBJECT_STORAGE_ACCESS_KEY \
      OBJECT_STORAGE_SECRET_KEY OBJECT_STORAGE_REGION
set -a
. ./.env.production
set +a

# Preflight sin imprimir secretos (solo endpoints): compose aplica
# ${OBJECT_STORAGE_ENDPOINT:-minio:9000} solo si la variable no esta
# exportada, asi que TODOS los servicios de app tienen que resolver minio:9000.
docker compose -p cavaai -f docker-compose.prod.yml config \
  | grep -oE 'MINIO_ENDPOINT[=:][ ]?[^[:space:]]*' | sort | uniq -c
# Salida esperada: una sola variante terminada en minio:9000 (segun la
# version de compose, "MINIO_ENDPOINT: minio:9000" o "MINIO_ENDPOINT=minio:9000").
# Si aparece otra (p. ej. garage:3900), alguna OBJECT_STORAGE_* sigue
# exportada: repetir el unset + source y no recrear hasta que salga limpio.
```

   Con el preflight limpio, recrear los servicios con el `up -d --no-deps`
   del paso 3: la app vuelve a MinIO. MinIO quedo intacto como copia previa
   al corte: desde la parada del paso 2 no ha recibido escrituras, y lo
   escrito despues en Garage acaba de devolverse con la copia inversa del
   punto 2.
4. No se borra nada en Garage: queda como estaba para diagnosticar.

## Criterio de salida del piloto

- **>= 7 dias estables** en produccion sobre Garage (sin errores de storage en
  backend ni workers, backups diarios correctos).
- **Restore probado** desde un backup hecho contra Garage (taladro de
  restauracion como el de 2026-09-26, conteos contra el manifiesto).
- Solo entonces se plantea retirar MinIO, en un PR aparte (fase 5 de
  OBJECT_STORAGE_MIGRATION.md). El volumen `cavaai-prod-minio` no se borra en
  ese mismo paso.
