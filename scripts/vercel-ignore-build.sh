#!/usr/bin/env bash
# Ignored Build Step de Vercel (vercel.json -> "ignoreCommand").
#
# Contrato de Vercel: exit 0 = NO construir (deploy cancelado), exit 1 = construir.
#
# Por que existe: el plan de Vercel tiene un cupo diario de despliegues. Solo
# main despliega (git.deploymentEnabled, #902), pero el 2026-10-27 entraron
# ~140 merges en main y cada uno lanzo un despliegue de produccion: desde #2381
# todos acabaron en "Deployment rate limited — retry in 24 hours" y produccion
# se quedo congelada. La mayoria de esos merges solo tocaban el backend
# (data-engine/), docs o tests, que no cambian nada de lo que sirve Vercel.
#
# Regla: se construye si cambio CUALQUIER fichero fuera de la lista de rutas
# que no afectan al frontend, comparando con el ultimo despliegue correcto
# (VERCEL_GIT_PREVIOUS_SHA). Asi un merge solo-backend que llega despues de un
# merge de frontend cuyo despliegue fallo NO se salta ese frontend: el diff es
# contra el ultimo despliegue que salio bien, no contra el commit anterior.
# Ante cualquier duda (sin SHA previo, SHA no disponible en el clon, error de
# git) se construye: fallar abierto es desplegar de mas, nunca dejar de desplegar.
set -u

prev="${VERCEL_GIT_PREVIOUS_SHA:-}"
head="${VERCEL_GIT_COMMIT_SHA:-HEAD}"

if [ -z "$prev" ]; then
  echo "vercel-ignore: sin VERCEL_GIT_PREVIOUS_SHA -> se construye"
  exit 1
fi
if ! git cat-file -e "${prev}^{commit}" 2>/dev/null; then
  # El clon de Vercel es superficial: si el despliegue anterior queda fuera,
  # se intenta traerlo; si no se puede, se construye.
  git fetch --quiet --depth=200 origin "$prev" 2>/dev/null || true
  if ! git cat-file -e "${prev}^{commit}" 2>/dev/null; then
    echo "vercel-ignore: ${prev} no esta en el clon -> se construye"
    exit 1
  fi
fi

# Rutas que no forman parte del build de Next.js.
changed=$(git diff --name-only "$prev" "$head" -- . \
  ':(exclude)data-engine/**' \
  ':(exclude)docs/**' \
  ':(exclude)qa-e2e/**' \
  ':(exclude)e2e/**' \
  ':(exclude).github/**' \
  ':(exclude)*.md' \
  ':(exclude)scripts/*.test.ts' \
  ':(exclude)scripts/*.test.mjs' 2>/dev/null)
status=$?
if [ $status -ne 0 ]; then
  echo "vercel-ignore: git diff fallo -> se construye"
  exit 1
fi
if [ -z "$changed" ]; then
  echo "vercel-ignore: desde ${prev:0:8} solo cambio backend/docs/tests -> no se despliega"
  exit 0
fi
echo "vercel-ignore: cambios de frontend desde ${prev:0:8}:"
echo "$changed" | head -20
exit 1
