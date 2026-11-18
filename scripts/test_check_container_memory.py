"""Behavior tests: check-container-memory alerta solo con lo medido por docker.

El binario docker se sustituye por un mock (mismo patron que
test_pg_daily_backup.py): las fixtures de memoria y estado van por entorno.
v2 (tras auditoria): un docker que falla es ERROR visible, nunca OK; un
porcentaje ilegible es ERROR, no un 0; Restarting/RestartCount se leen de
inspect.

Run from repo root:
    python -m unittest scripts.test_check_container_memory -v
"""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'ops' / 'check-container-memory.sh'

MOCK = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
cmd = args[0] if args else ''
if cmd in ('stats', 'ps', 'inspect'):
    if os.environ.get('MOCK_' + cmd.upper() + '_FAIL'):
        print('mock: docker ' + cmd + ' caido', file=sys.stderr)
        sys.exit(1)
    print(os.environ.get('MOCK_' + cmd.upper(), ''))
    sys.exit(0)
sys.exit(2)
'''


class ContainerMemoryTests(unittest.TestCase):
    def run_case(self, stats='', inspect='', ps='c1\nc2', script_args=(), **env_over):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        binpath = Path(tmp.name) / 'bin'
        binpath.mkdir()
        mock = binpath / 'docker'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                   MOCK_STATS=stats, MOCK_INSPECT=inspect, MOCK_PS=ps)
        env.update(env_over)
        return subprocess.run(['bash', str(SCRIPT), *script_args], env=env,
                              capture_output=True, text=True)

    def test_todo_bajo_umbral_es_ok(self):
        r = self.run_case(stats='cavaai-postgres;42.10%\ncavaai-worker;60.00%\n',
                          inspect='cavaai-postgres false false 0\ncavaai-worker false false 2\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OK: cavaai-postgres al 42%', r.stdout)
        self.assertIn('2 contenedores vigilados', r.stdout)

    def test_sobre_umbral_alerta_con_lo_medido(self):
        r = self.run_case(stats='cavaai-worker;97.55%\n',
                          inspect='cavaai-worker false false 0\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA: cavaai-worker al 97%', r.stdout)

    def test_umbral_configurable(self):
        stats = 'cavaai-worker;80.00%\n'
        self.assertEqual(
            self.run_case(stats=stats, inspect='cavaai-worker false false 0\n').returncode, 0)
        r = self.run_case(stats=stats, inspect='cavaai-worker false false 0\n',
                          script_args=('70',))
        self.assertEqual(r.returncode, 1)

    def test_oomkilled_alerta_aunque_la_memoria_actual_sea_baja(self):
        # La marca es lo que el daemon declara en el estado del contenedor.
        r = self.run_case(stats='cavaai-worker;10.00%\n',
                          inspect='cavaai-worker true false 3\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn('OOMKilled=true', r.stdout)

    def test_restarting_alerta_reinicio_en_curso(self):
        # v2: Restarting=true (reinicio en este instante) con RestartCount
        # de contexto; el mensaje no afirma un bucle (ajuste del auditor).
        r = self.run_case(stats='cavaai-worker;10.00%\n',
                          inspect='cavaai-worker false true 7\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn('se esta reiniciando en este instante', r.stdout)
        self.assertIn('7', r.stdout)

    def test_stats_fallido_es_error_visible_no_ok(self):
        # v2 (repro del auditor): docker caido en todo ya no termina exit 0.
        r = self.run_case(MOCK_STATS_FAIL='1', MOCK_PS_FAIL='1')
        self.assertEqual(r.returncode, 1)
        self.assertIn('ERROR', r.stdout)
        self.assertIn('no se pudo medir', r.stdout)
        self.assertNotIn('OK:', r.stdout)

    def test_ps_fallido_es_error_visible(self):
        r = self.run_case(stats='cavaai-worker;10.00%\n', MOCK_PS_FAIL='1')
        self.assertEqual(r.returncode, 1)
        self.assertIn('docker ps fallo', r.stdout)

    def test_inspect_fallido_es_error_visible(self):
        r = self.run_case(stats='cavaai-worker;10.00%\n', MOCK_INSPECT_FAIL='1')
        self.assertEqual(r.returncode, 1)
        self.assertIn('docker inspect fallo', r.stdout)

    def test_porcentaje_ilegible_es_error_no_cero(self):
        # v2 (repro del auditor): antes se convertia en 0 en silencio y salia OK.
        r = self.run_case(stats='cavaai-worker;--%\n',
                          inspect='cavaai-worker false false 0\n')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no se pudo interpretar', r.stdout)

    def test_filtro_ignora_contenedores_ajenos(self):
        r = self.run_case(stats='otro-bot;99.00%\ncavaai-worker;10.00%\n',
                          inspect='otro-bot false true 9\ncavaai-worker false false 0\n')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn('otro-bot', r.stdout)

    def test_filtro_regex_personalizado(self):
        r = self.run_case(stats='otro-bot;99.00%\n', inspect='otro-bot false false 0\n',
                          CONTAINER_FILTER='.*')
        self.assertEqual(r.returncode, 1)
        self.assertIn('otro-bot al 99%', r.stdout)
        r = self.run_case(stats='otro-bot;99.00%\n', inspect='otro-bot false false 0\n',
                          CONTAINER_FILTER='^bot-')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_umbral_no_numerico_es_uso_incorrecto(self):
        r = self.run_case(script_args=('abc',))
        self.assertEqual(r.returncode, 2)

    def test_sin_docker_en_path_alerta(self):
        bash = shutil.which('bash')
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        # PATH sin docker: se invoca bash por ruta absoluta para aislar la prueba.
        r = subprocess.run([bash, str(SCRIPT)],
                           env={'PATH': str(tmp.name)}, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('no hay docker', r.stdout)


if __name__ == '__main__':
    unittest.main()
