"""Backup verificado de los tres pilares de GerarAI (Postgres, MinIO, Qdrant).

Modulos:
  * `_kit`         primitivas fail-closed, manifiesto y pins de herramientas.
  * `backup_all`   orquestador: un manifiesto comun para los tres pilares.
  * `backup_postgres` / `backup_minio` / `backup_qdrant`  un pilar cada uno.
  * `disaster_drill`  ciclo backup -> destruir -> restore -> verificar, aislado.
  * `RUNBOOK.md`   como recuperar desde cero, en orden y con tiempos.
  * `README.md`    decisiones, requisitos y como ejecutar.

Los scripts se ejecutan desde `data-engine/`:
    python -m scripts.backup.backup_all --out-dir backups
"""
