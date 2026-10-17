@echo off
REM =====================================================================
REM CavaAI - arranque en 1 click: infra + backend + frontend + navegador
REM =====================================================================
REM MODOS (primer parametro):
REM   arrancar_cavaai.bat          DEV por defecto:  `next dev -p 3000`
REM   arrancar_cavaai.bat /prod    PROD: `next build` una vez + `next start -p 3000`
REM   (tambien valen: prod, --prod, -prod)
REM ---------------------------------------------------------------------
REM QUE MODO USAR:
REM   - DEV (diario / programar): arranque rapido, compila cada pagina
REM     bajo demanda (~1 min la primera vez que abres cada pagina).
REM     Usa este modo salvo que necesites lo de abajo.
REM   - PROD (/prod): valida el modo produccion local. Hace `next build`
REM     una vez (~2 min 20 s medido 2026-09-21) y luego sirve con
REM     `next start`: navegacion mas rapida, errores de build reales
REM     (los que veria el despliegue). Usalo antes de desplegar o para
REM     probar rendimiento. Si el build falla, el .bat se detiene y NO
REM     arranca el frontend.
REM ---------------------------------------------------------------------
REM Docker SOLO levanta la infraestructura (postgres, mongodb, redis,
REM qdrant, minio). El backend (uvicorn) y el frontend (next) corren en
REM LOCAL: si Docker los levantara tambien, chocarian por los puertos
REM 8000/3000. `docker compose up` con servicios ya construidos no
REM necesita build: nada de --no-build (rompe en frio cuando la imagen
REM no existe).
REM =====================================================================
cd /d "%~dp0"
set "FRONT_MODE=DEV"
REM Valores por defecto de Postgres (el .bat no carga el .env): si el entorno
REM no define POSTGRES_USER/POSTGRES_DB, usa los del docker-compose.
if not defined POSTGRES_USER set "POSTGRES_USER=portfolio"
if not defined POSTGRES_DB set "POSTGRES_DB=cavaai_research"
if /i "%~1"=="/prod" set "FRONT_MODE=PROD"
if /i "%~1"=="prod" set "FRONT_MODE=PROD"
if /i "%~1"=="--prod" set "FRONT_MODE=PROD"
if /i "%~1"=="-prod" set "FRONT_MODE=PROD"
echo CavaAI - modo %FRONT_MODE%

echo [1/5] Levantando Docker (solo infra: postgres, mongodb, redis, qdrant, minio)...
docker compose up -d postgres mongodb redis qdrant minio
if errorlevel 1 (
  echo ERROR: docker compose fallo. Comprueba que Docker Desktop esta arrancado.
  pause
  exit /b 1
)

echo [2/5] Esperando a Postgres y Qdrant...
for /L %%i in (1,1,30) do (
  docker exec cavaai-postgres pg_isready -U %POSTGRES_USER% -d %POSTGRES_DB% >nul 2>&1 && goto postgres_ok
  timeout /t 2 /nobreak >nul
)
echo ERROR: Postgres no responde a pg_isready tras 60s; NO sigo: las migraciones y el backend fallarian.
echo Comprueba "docker compose ps postgres" y que POSTGRES_USER/POSTGRES_DB del entorno (o los valores por defecto) coinciden con el .env.
pause
exit /b 1
:postgres_ok
for /L %%i in (1,1,30) do (
  curl -sf http://localhost:6333/healthz >nul 2>&1 && goto qdrant_ok
  timeout /t 2 /nobreak >nul
)
echo AVISO: Qdrant no responde; sigo sin busqueda semantica.
:qdrant_ok

echo [3/5] Liberando puertos 8000 y 3000 (solo node.exe y python.exe huerfanos de CavaAI)...
call :free_port 8000
call :free_port 3000

echo [4/5] Migraciones de base de datos...
cd data-engine
.\.venv\Scripts\python.exe -m alembic upgrade head
if errorlevel 1 (
  echo ERROR: las migraciones de Alembic fallaron. NO arranco el backend.
  echo Revisa que Postgres esta sano y que DATABASE_URL del .env apunta a el.
  cd ..
  pause
  exit /b 1
)
start "CavaAI backend" .\.venv\Scripts\python.exe -m uvicorn main:app --host 127.0.0.1 --port 8000
cd ..

if /i "%FRONT_MODE%"=="PROD" goto frontend_prod
:frontend_dev
echo [5/5] Frontend DEV (next dev)...
start "CavaAI frontend" node_modules\.bin\next dev -p 3000
echo Esperando al frontend (primera vez compila ~1 min)...
goto wait_web
:frontend_prod
echo [5/5] Frontend PROD: build una vez (~2 min) + next start...
call node_modules\.bin\next build
if errorlevel 1 (
  echo ERROR: `next build` fallo; revisa los errores de arriba. Frontend NO arrancado.
  pause
  exit /b 1
)
start "CavaAI frontend (prod)" node_modules\.bin\next start -p 3000
echo Esperando al frontend prod (arranca en ~2 s tras el build)...
:wait_web
for /L %%i in (1,1,30) do (
  curl -sf http://localhost:3000/ >nul 2>&1 && goto web_ok
  timeout /t 4 /nobreak >nul
)
:web_ok
start http://localhost:3000/
echo Listo (%FRONT_MODE%): http://localhost:3000/
pause
goto :eof

REM ---------------------------------------------------------------------
REM :free_port <puerto> - mata SOLO node.exe / python.exe en LISTENING sobre
REM el puerto (evita matar procesos ajenos como IDEs, Docker o antivirus).
REM ---------------------------------------------------------------------
:free_port
set "PORT=%~1"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%PORT% .*LISTENING"') do (
  for /f "tokens=1" %%n in ('tasklist /FI "PID eq %%p" /FO TABLE /NH 2^>nul') do (
    echo %%n | findstr /i /c:"node.exe" /c:"python.exe" >nul && (
      echo   Liberando puerto %PORT% ^(%%n PID %%p^)...
      taskkill /F /PID %%p >nul 2>&1
    ) || echo   Puerto %PORT% ocupado por %%n ^(PID %%p^): no lo toco, revisalo manualmente.
  )
)
exit /b 0
