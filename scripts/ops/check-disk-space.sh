#!/usr/bin/env bash
# Alerta de disco de la VM (propuesta: encajar en cron del host + aviso).
#
# Contexto (medido 5-nov-2026): el disco llego al 90% sin que nadie lo viera
# (15-21 GB libres). Este chequeo sale con codigo 1 si el uso supera el
# umbral (85% por defecto) e imprime la linea para que un cron la mande por
# el canal de alertas. No borra nada.
#
# Uso: ./scripts/ops/check-disk-space.sh [UMBRAL_PCT]   (defecto 85)
# Cron sugerido (host): */30 * * * * /ruta/check-disk-space.sh || avisar
set -euo pipefail

UMBRAL="${1:-85}"
case "${UMBRAL}" in ''|*[!0-9]*) echo "El umbral debe ser un numero (p. ej. 85)"; exit 2;; esac

USO=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')
LIBRE=$(df -h / | awk 'NR==2 {print $4}')
if [ "${USO}" -ge "${UMBRAL}" ]; then
  echo "[disk] ALERTA: / al ${USO}% (umbral ${UMBRAL}%), libres ${LIBRE}. Candidatos: volumenes de verificacion huerfanos, bloat postgres, imagenes dangling."
  exit 1
fi
echo "[disk] OK: / al ${USO}% (umbral ${UMBRAL}%), libres ${LIBRE}"
