#!/usr/bin/env bash
# Memoria de contenedores de la VM (complemento de check-disk-space.sh).
#
# Motivo (medido en prod): el 15-nov-2026 a las 03:40 un worker murio por OOM
# (limite 4 GiB) y se vio solo a posteriori; "Postgres hits memory limit
# often" tambien se observo a mano. Nada mide la memoria por contenedor.
# Este chequeo sale con codigo 1 si algun contenedor supera el umbral de
# memoria MEDIDA (docker stats, porcentaje sobre su limite), si algun
# contenedor lleva la marca OOMKilled o si se esta reiniciando en este
# instante (State.Restarting=true en docker inspect: acredita el reinicio
# actual, no un bucle probado), e imprime una linea por hallazgo para que un
# cron la mande por el canal de alertas. SOLO LEE: docker stats / docker ps /
# docker inspect. Nunca reinicia nada.
#
# Veracidad (v2, tras auditoria): un docker que FALLA no es un host sano. Si
# stats, ps o inspect no se pueden leer, o un porcentaje no se puede
# interpretar, el chequeo sale con ERROR (exit 1) diciendo que no pudo
# medir; nunca termina en OK sin haber medido.
#
# Uso: ./scripts/ops/check-container-memory.sh [UMBRAL_PCT]   (defecto 85)
#   CONTAINER_FILTER  regex de nombres a vigilar (sin definir: cavaai*/gerarai*;
#                     '.*' vigila todos los contenedores del host)
# Cron sugerido (host): */15 * * * * /ruta/check-container-memory.sh || avisar
set -euo pipefail

UMBRAL="${1:-85}"
case "${UMBRAL}" in ''|*[!0-9]*) echo "El umbral debe ser un numero (p. ej. 85)"; exit 2;; esac
command -v docker >/dev/null || { echo "[mem] ERROR: no hay docker en PATH (no se pudo medir)"; exit 1; }

# Un case no puede alternar patrones desde una variable (el | no se reparsea
# tras la expansion): el defecto va fijo en codigo y CONTAINER_FILTER es regex.
vigilado() {
  if [ -n "${CONTAINER_FILTER:-}" ]; then
    [[ "$1" =~ ${CONTAINER_FILTER} ]]
  else
    case "$1" in cavaai*|gerarai*) return 0;; *) return 1;; esac
  fi
}

fail=0
vigilados=0

# Porcentaje de memoria sobre el limite por contenedor en ejecucion.
# Formato pedido: "nombre;85.32%". Un fallo de lectura es ERROR, no OK.
if ! stats_out=$(docker stats --no-stream --format '{{.Name}};{{.MemPerc}}' 2>&1); then
  echo "[mem] ERROR: no se pudo medir la memoria (docker stats fallo): ${stats_out}"
  fail=1
  stats_out=""
fi
while IFS=';' read -r nombre pct_raw; do
  [ -n "${nombre}" ] || continue
  vigilado "${nombre}" || continue
  vigilados=$((vigilados + 1))
  pct="${pct_raw%\%}"; pct="${pct%.*}"
  case "${pct}" in
    ''|*[!0-9]*)
      # Un porcentaje ilegible no es un 0: es una medida fallida, visible.
      echo "[mem] ERROR: no se pudo interpretar la memoria medida de ${nombre} (docker stats devolvio '${pct_raw}')"
      fail=1
      continue
      ;;
  esac
  if [ "${pct}" -ge "${UMBRAL}" ]; then
    echo "[mem] ALERTA: ${nombre} al ${pct}% de su limite de memoria (umbral ${UMBRAL}%)"
    fail=1
  else
    echo "[mem] OK: ${nombre} al ${pct}% (umbral ${UMBRAL}%)"
  fi
done <<< "${stats_out}"

# Estado por contenedor via docker inspect: OOMKilled (lo que el daemon
# declara en el estado actual del contenedor; su persistencia tras un
# reinicio automatico NO esta medida en este carril, no se afirma),
# Restarting (reiniciandose en este instante; acredita el reinicio actual,
# no un bucle probado) y RestartCount (reinicios acumulados medidos; es un
# acumulado historico: se reporta como contexto, no se umbralea).
if ! ids=$(docker ps -aq 2>&1); then
  echo "[mem] ERROR: no se pudo medir la lista de contenedores (docker ps fallo): ${ids}"
  fail=1
  ids=""
fi
ooms=""
if [ -n "${ids}" ]; then
  if ! ooms=$(echo "${ids}" | xargs docker inspect --format '{{.Name}} {{.State.OOMKilled}} {{.State.Restarting}} {{.RestartCount}}' 2>&1); then
    echo "[mem] ERROR: no se pudo medir el estado de los contenedores (docker inspect fallo): ${ooms}"
    fail=1
    ooms=""
  fi
fi
while read -r nombre oom restarting restarts; do
  [ -n "${nombre}" ] || continue
  nombre="${nombre#/}"
  vigilado "${nombre}" || continue
  if [ "${oom}" = "true" ]; then
    echo "[mem] ALERTA: ${nombre} tiene OOMKilled=true (murio por memoria y la marca sigue ahi; reinicios acumulados medidos: ${restarts})"
    fail=1
  fi
  if [ "${restarting}" = "true" ]; then
    echo "[mem] ALERTA: ${nombre} se esta reiniciando en este instante (Restarting=true; RestartCount=${restarts}, historico acumulado)"
    fail=1
  fi
done <<< "${ooms}"

if [ "${fail}" -eq 0 ]; then
  echo "[mem] OK: ${vigilados} contenedores vigilados bajo el umbral, sin OOMKilled ni reinicios en curso"
fi
exit "${fail}"
