# Runbook de recuperacion (disaster recovery) — GerarAI

Este runbook esta escrito para **quien no conoce el sistema**. Si estas leyendo
esto en mitad de un incidente, no necesitas contexto previo: los comandos estan
completos, en orden y con el tiempo esperado de cada uno.

Todo se ejecuta desde `data-engine/` (el directorio con `alembic.ini`).

```
cd /ruta/a/GerarAI/data-engine
```

Que se recupera:

| Pilar | Que es | Artefacto | Formato |
|---|---|---|---|
| Postgres | datos, esquema, `alembic_version` | `postgres/database.dump` | `pg_dump -Fc` (custom) |
| Postgres | roles del cluster | `postgres/globals.sql` | `pg_dumpall --globals-only` |
| MinIO | documentos originales (S3) | `minio/objects.tar.gz` | copia por **clave** |
| Qdrant | indice vectorial | `qdrant/<coleccion>.snapshot` | snapshot por API |

Reglas que no se negocian:

1. **Un restore sin verificar no es una recuperacion.** Los comandos de restore
   terminan con exito aunque no restauren nada util; por eso el paso 6 es
   obligatorio y falla cerrado.
2. **Destino limpio.** Postgres se recrea (DROP + CREATE DATABASE), el bucket se
   vacia y las colecciones de Qdrant se borran antes de subir. Es el caso real
   de desastre: no hay donde sobreescribir.
3. **Los conteos se comprueban ANTES de arrancar la aplicacion.** El arranque de
   la app inserta filas si `APP_ENV != production` (`ensure_company_master()` en
   `main.py`), asi que comparar despues daria falsos positivos.
4. **Nada de dumps planos.** Un `.sql` de `pg_dump -Fp` no es seleccionable, no
   se puede restaurar por partes y un corte a medias lo deja inutilizable.

---

## Resumen en 6 pasos

| # | Paso | Tiempo esperado (VM de produccion) | Riesgo |
|---|---|---|---|
| 0 | Tener un backup (o generarlo) | 2–15 min | — |
| 1 | Parar la app y decidir el alcance | 2 min | — |
| 2 | Copiar el backup a la maquina nueva | 5–30 min | — |
| 3 | Levantar Postgres | 1–3 min | — |
| 4 | Restaurar Postgres | 1–10 min | **destructivo** |
| 5 | Restaurar MinIO y Qdrant | 2–15 min | **destructivo** |
| 6 | Verificar (6 comprobaciones) | 1–5 min | — |
| 7 | Arrancar la app y validar en negocio | 5 min | — |

---

## Paso 0 — Tener un backup (2–15 min)

Si estas recuperando, casi seguro ya lo tienes. Si lo estas **generando** ahora:

```bash
# Un comando: los tres pilares y un manifiesto comun. No acepta dumps planos.
python -m scripts.backup.backup_all \
  --out-dir backups \
  --pg-mode docker --pg-container cavaai-postgres \
  --minio-endpoint 127.0.0.1:9000 --minio-bucket research \
  --qdrant-url http://127.0.0.1:6333
```

Imprime `backups/<backup_id>/` con `manifest.json`, `postgres/`, `minio/` y
`qdrant/`. `backup_id` es el timestamp UTC y `manifest.json` declara la revision
de Alembic, las versiones de las herramientas, los SHA-256 y los tamanos.

Un backup de Postgres **se niega a hacerse** si la base esta por detras del head
de Alembic (o si hay escrituras concurrentes durante el dump). No es un
inconveniente: son los dos casos en los que el dump restauraria algo que rompe
al arrancar.

Copia el directorio **completo** fuera de la maquina (R2 u otro host) antes de
considerarlo un backup: un backup en el mismo disco que se ha roto no es un
backup. `scripts/backup.sh` sube a Cloudflare R2 si se define `RCLONE_REMOTE`.

## Paso 1 — Parar la app y decidir el alcance (2 min)

En la maquina donde esta el backup (o en la nueva, si es un DR completo):

```bash
# 1.1 La app deja de escribir. Un backup con escrituras en curso puede tener
#     conteos que no casan con el dump (el backup lo detecta y falla).
docker compose -f docker-compose.prod.yml --env-file .env.production stop backend worker worker-thesis worker-kpis worker-alerts worker-gdelt worker-knowledge scheduler
```

**DECISION HUMANA — antes de continuar**, decide y anota:

- **Cual es el backup a restaurar.** Elige el `manifest.json` con el
  `backup_id` mas reciente que pase la verificacion de checksums (paso 2.1). No
  el mas reciente por fecha de fichero.
- **Que revision de codigo se despliega.** El `manifest.json` declara
  `alembic_head` (por ejemplo `0046_inferred_inputs`). Si el codigo que vas a
  arrancar esta **por detras** de ese head, el restore "funciona" y la app
  rompe en la primera peticion: restaura el backup y sube el codigo al commit
  del `git_commit` del manifiesto, o mas adelante.
- **Ventana de mantenimiento** y a quien se avisa. El frontend en Vercel
 _apuntara_ al backend caido: pausa el aviso o acepta el 502.
- **Si hay riesgo de volver atras.** Un restore sobre production NO es
  reversible salvo que hagas tu propio backup de los datos actuales ANTES del
  paso 4. Es strongly recomendable.

## Paso 2 — Copiar el backup y comprobar que esta integro (5–30 min)

```bash
# 2.1 El backup tiene que estar COMPLETO en la maquina destino.
BACKUP=/ruta/al/backup/20261002T101500Z
cd "$BACKUP"
ls -la                      # manifest.json + postgres/ + minio/ + qdrant/
```

```bash
# 2.2 Comprobar los SHA-256 ANTES de tocar nada. Un artefacto corrupto en disco
#     o en R2 se detecta aqui, no a mitad del restore.
python - <<'PY'
import json, hashlib, pathlib, sys
backup = pathlib.Path("/ruta/al/backup/20261002T101500Z")
manifest = json.loads((backup / "manifest.json").read_text())
print("backup_id:", manifest["backup_id"], "| head:", manifest["alembic_head"])
fallos = 0
for artefacto in manifest["artifacts"]:
    ruta = backup / artefacto["path"]
    if not ruta.is_file():
        print("AUSENTE:", artefacto["path"]); fallos += 1; continue
    digest = hashlib.sha256(ruta.read_bytes()).hexdigest()
    ok = digest == artefacto["sha256"] and ruta.stat().st_size == artefacto["bytes"]
    print(("OK   " if ok else "MAL  "), artefacto["path"], ruta.stat().st_size, "B")
    fallos += 0 if ok else 1
print("RESULTADO:", "todos los artefactos cuadran" if not fallos else f"{fallos} artefactos NO cuadran")
sys.exit(1 if fallos else 0)
PY
```

Si algo no cuadra: **para aqui**. El backup esta corrupto; recuperar otro.

```bash
# 2.3 Que revision de esquema espera el codigo de esta maquina?
python -m alembic heads
```

Debe imprimir exactamente el `alembic_head` del manifiesto. Si no coincide, es
el punto de decision humana del paso 1.

## Paso 3 — Levantar Postgres en el destino (1–3 min)

```bash
# 3.1 Solo Postgres: todavia no hay datos, nada que perder.
docker compose -f docker-compose.prod.yml --env-file .env.production up -d postgres
```

```bash
# 3.2 Esperar a que ACEPTE CONSULTAS, no solo a que `pg_isready` responda:
#     durante el initdb `pg_isready` da ok y despues el motor reinicia, que es
#     como un restore falla con "the database system is shutting down".
for i in $(seq 1 90); do
  docker compose -f docker-compose.prod.yml --env-file .env.production exec -T postgres \
    psql --username="${POSTGRES_USER:-portfolio}" --dbname=postgres -tAc 'SELECT 1' \
    | grep -q 1 && echo "Postgres operativo" && break
  sleep 2
done
```

## Paso 4 — Restaurar Postgres (1–10 min) — DESTRUCTIVO

```bash
# 4.1 Restaurar. DROP + CREATE DATABASE: destino limpio, no sobrescribe.
#     --confirm-restore es obligatorio a proposito (operacion destructiva).
python -m scripts.restore.restore_postgres \
  --manifest "$BACKUP" \
  --mode docker \
  --container cavaai-postgres \
  --user "${POSTGRES_USER:-portfolio}" \
  --confirm-restore
```

Que hace, en este orden:

1. Verifica el SHA-256 del dump y de los globals contra el manifiesto. Si no
   casan, **no toca la base**.
2. Aplica `postgres/globals.sql` (roles). En un cluster NUEVO sin este paso el
   backend falla con `role does not exist` en el primer arranque.
3. `DROP DATABASE ... WITH (FORCE)` + `CREATE DATABASE`: destino vacio.
4. `pg_restore --exit-on-error --no-owner --no-privileges`.
5. Cuenta las tablas en la base **destino** y falla si falta alguna.

**DECISION HUMANA:** el codigo de salida 0 aqui **no** significa que el restore
sea bueno. Si sale != 0, el paso 6 dira exactamente por que.

## Paso 5 — Restaurar MinIO y Qdrant (2–15 min) — DESTRUCTIVO

```bash
# 5.1 MinIO: bucket vacio + cada clave subida con su SHA-256 verificado.
python -m scripts.restore.restore_minio \
  --manifest "$BACKUP" \
  --endpoint 127.0.0.1:9000 \
  --access-key "${MINIO_ROOT_USER}" \
  --secret-key "${MINIO_ROOT_PASSWORD}" \
  --confirm-restore
```

```bash
# 5.2 Qdrant: borra las colecciones destino y sube cada .snapshot por la API.
#     Es lo UNICO que restaura el indice en otra maquina: copiar el directorio
#     /qdrant/storage solo funciona en la misma maquina.
python -m scripts.restore.restore_qdrant \
  --manifest "$BACKUP" \
  --url http://127.0.0.1:6333 \
  --confirm-restore
```

Orden importante: **MinIO antes que Qdrant** no es un capricho. Si reindexaras
Qdrant desde Postgres y el RAG escribiera documentos nuevos en MinIO, hacerlo al
reves deja objetos sin su vector. En un DR frio no hay escrituras, pero el orden
es el que evita tener que razonar sobre ello.

## Paso 6 — Verificar: 6 comprobaciones, fail-closed (1–5 min)

```bash
# 6.1 Fase de DATOS: sin la aplicacion. Countos, esquema, revision, objetos y vectores.
python -m scripts.restore.verify_restore \
  --manifest "$BACKUP" \
  --mode docker --pg-container cavaai-postgres --pg-user "${POSTGRES_USER:-portfolio}" \
  --minio-endpoint 127.0.0.1:9000 \
  --minio-access-key "${MINIO_ROOT_USER}" --minio-secret-key "${MINIO_ROOT_PASSWORD}" \
  --qdrant-url http://127.0.0.1:6333 \
  --phase data
```

| Comprobacion | Que prueba | Si falla |
|---|---|---|
| `a_esquema` | `pg_restore --list` y `information_schema` declaran todas las tablas del manifiesto | el dump no es el que creias o el restore se quedo a medias |
| `b_conteos` | `count(*)` de cada tabla **igual** al manifiesto, desviacion 0 | datos perdidos o duplicados |
| `c_alembic` | `alembic_version` restaurada = manifiesto = head del codigo | el esquema restaurado no corresponde a este codigo |
| `e_objetos` | cada clave de MinIO **legible** con su SHA-256, y sin sobrantes | el bucket no sirve lo que el backup declara |
| `f_vectores` | mismos puntos, mismas dimensiones y el punto de ejemplo con el mismo id | el indice no es el mismo |

```bash
# 6.2 Fase de APLICACION: arrancar contra la base restaurada y mirarla servir.
docker compose -f docker-compose.prod.yml --env-file .env.production up -d backend

python -m scripts.restore.verify_restore \
  --manifest "$BACKUP" \
  --mode docker --pg-container cavaai-postgres --pg-user "${POSTGRES_USER:-portfolio}" \
  --minio-endpoint 127.0.0.1:9000 \
  --minio-access-key "${MINIO_ROOT_USER}" --minio-secret-key "${MINIO_ROOT_PASSWORD}" \
  --qdrant-url http://127.0.0.1:6333 \
  --app-base-url http://127.0.0.1:8000 \
  --phase app
```

`d_aplicacion` exige, en este orden: `/health/ready` con `checks.database=ok`
(ademas `qdrant` y `minio` en `ok`), `/api/health` con `status=ok` y `schema=[]`
(sin esquema a medias), y `GET /api/companies` devolviendo un ticker que estaba
en el backup. Un `200` con lista vacia no prueba que sirva lo restaurado.

**Ninguna comprobacion se puede omitir.** Si un servicio esta caido, el informe
lo dice con el motivo y el comando sale con 1. Es la misma regla que el gate de
RAG de `ci.yml` ("RAG activation tests skipped -> exit 1"). Un informe con
`ok: false` **es** el resultado del restore.

## Paso 7 — Arrancar todo y validar en negocio (5 min)

```bash
docker compose -f docker-compose.prod.yml --env-file .env.production up -d
```

El informe del paso 6 queda en `$BACKUP/verify_report_data.json` y
`verify_report_app.json`. **Adjuntalo al parte de incidente.**

Comprobaciones de negocio, en este orden (5–10 min): abre una tesis y comprueba
que su documento original **se descarga** desde MinIO (no solo que la ficha
exista); lanza una busqueda semantica y comprueba que devuelve resultados del
tenant; comprueba que los conteos de cartera coinciden con el ultimo estado
conocido.

---

## Fallos frecuentes (con su causa real)

| Sintoma | Causa | Que hacer |
|---|---|---|
| `pg_restore: error: ... version mismatch` | el cliente es anterior al servidor (pin 17) | usar `--mode docker` (usa el cliente del contenedor, 17.x) |
| `role "portfolio" does not exist` | no se restauraron los globals | paso 4Automatico restaurarlos; en un cluster manual, `--no-globals` no debe usarse |
| `the database system is shutting down` | el restore empezó durante el initdb | repetir el paso 3.2 (espera a `SELECT 1`) |
| `pg_dumpall: missing "=" after ...` | se paso `--dbname=<base>` a `pg_dumpall`, que espera una cadena de conexion | el codigo ya lo evita (`PsqlTarget.cluster_wide()`) |
| b_conteos con desviacion | escrituras durante el backup, o el dump no es el del manifiesto | el backup detecta el drift y falla; reintentar en ventana sin escritura |
| c_alembic falla | el dump es anterior al head | desplegar el `git_commit` del manifiesto |
| d_aplicacion: `schema=[...]` | la app arranca con el esquema a medias | mirar el error en `/api/health`; suele ser una migracion no aplicada |
| RAG vacio tras el restore | se copio el volumen de Qdrant en vez de usar los snapshots | rehacer el paso 5.2 por API |
| MinIO "no sirve" documentos | el bucket se restauro en otro nombre o con otras credenciales | comprobar `minio.source_bucket` del manifiesto |

## Cuentas de versionado de MinIO (importante)

`backup_minio.py` **activa el versionado** del bucket en cada backup (idem,
idempotente) y el manifiesto declara si estaba activo:

```json
"versioning": "Enabled (activado por este backup)"
```

Sin versionado, una version sobrescrita desaparece de MinIO para siempre. Con
versionado:

- un objeto subido hace una hora y **no** sobrescrito se recupera del backup
  (el backup guarda la ultima version de cada clave);
- un objeto **sobreescrito** se recupera del bucket vivo con `mc cp --versions`
  o de un backup hecho con `--include-versions` (copia todas las versiones);
- **antes del primer backup con versionado**, las versiones anteriores a esa
  fecha no existen en ningun sitio. Es la unica ventana irrecuperable del
  sistema y por eso el runbook la menciona: no desactives el versionado.

## Cuando la app muta la base restaurada

Con `APP_ENV != production` (local, CI, test) el arranque de la aplicacion
**inserta filas**: `ensure_company_master()` mete las companies maestras y
`configure_model_aliases()` los alias de modelo. En el drill, `companies` pasa de
12 a 35 filas al arrancar la app.

Por eso los conteos se comprueban en el paso 6.1 **antes** de arrancar nada. En
produccion (`APP_ENV=production`) el arranque no inserta, pero el orden del
runbook es valido en ambos casos y no depende de esa sutileza.

## Como practicar antes de necesitarlo

```bash
# Drill completo, aislado, en contenedores y puertos propios. NO toca produccion.
python -m scripts.backup.disaster_drill
```

Hace backup -> **destruye** contenedores y volumenes -> restaura a destino
limpio -> ejecuta las 6 comprobaciones. Devuelve 0 solo si todas pasan. Es
exactamente el ciclo de este runbook, sin el riesgo.
