"""Restore verificado de los tres pilares de GerarAI, a destino limpio.

Modulos:
  * `restore_postgres`  recrea la base y aplica `pg_restore --exit-on-error`.
  * `restore_minio`     recrea el bucket y sube cada objeto por clave.
  * `restore_qdrant`    borra las colecciones y sube cada `.snapshot` por la API.
  * `verify_restore`    LAS SEIS comprobaciones; si alguna no se puede ejecutar,
    el resultado es FALLO con motivo (fail-closed), nunca "omitido".

Se ejecutan desde `data-engine/`:
    python -m scripts.restore.verify_restore --manifest backups/<id> --app-base-url ...
"""
