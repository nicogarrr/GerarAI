"""Behavior tests: check-scheduler-heartbeat alerta solo con latido medido.

El `docker` real se sustituye por un doble en PATH que sirve, por job, el
contenido de un fichero del directorio MOCK_DIR (o nada si no existe: job
sin latido). Asi cada caso controla la edad exacta del latido.

Run from repo root:
    python -m unittest scripts.test_check_scheduler_heartbeat -v
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parent / 'ops' / 'check-scheduler-heartbeat.sh'

FAKE_DOCKER = """#!/usr/bin/env bash
[ "${MOCK_REDIS_DOWN:-0}" = "1" ] && exit 1
key="${@: -1}"
job="${key##*:}"
f="${MOCK_DIR}/${job}"
[ -f "${f}" ] && cat "${f}"
exit 0
"""

JOBS = ("source_health_watchdog", "queue_watchdog",
        "db_connection_watchdog", "source_freshness_watchdog")


class SchedulerHeartbeatTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        self.beats = self.root / 'beats'
        self.beats.mkdir()
        docker = self.bin / 'docker'
        docker.write_text(FAKE_DOCKER)
        docker.chmod(0o755)

    def _beat(self, job: str, age_seconds: float | None, *, raw: str | None = None):
        if raw is None:
            ts = time.strftime('%Y-%m-%dT%H:%M:%S+00:00',
                               time.gmtime(time.time() - age_seconds))
            raw = ts
        (self.beats / job).write_text(raw)

    def _fresh_all(self):
        for job in JOBS:
            self._beat(job, 60)

    def run_case(self, *args, redis_down: bool = False):
        env = dict(os.environ,
                   PATH=f"{self.bin}:{os.environ['PATH']}",
                   MOCK_DIR=str(self.beats),
                   MOCK_REDIS_DOWN='1' if redis_down else '0')
        return subprocess.run(['bash', str(SCRIPT), *args], env=env,
                              capture_output=True, text=True)

    def test_todo_fresco_es_ok(self):
        self._fresh_all()
        r = self.run_case()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for job in JOBS:
            self.assertIn(f'OK {job}', r.stdout)
        self.assertIn('4 jobs con latido fresco', r.stdout)

    def test_sin_latido_alerta_nombrando_el_job(self):
        self._fresh_all()
        (self.beats / 'queue_watchdog').unlink()
        r = self.run_case()
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA queue_watchdog: sin latido', r.stdout)
        self.assertIn('OK source_health_watchdog', r.stdout)  # el resto sigue OK

    def test_latido_viejo_alerta_con_edad_medida(self):
        self._fresh_all()
        self._beat('db_connection_watchdog', 5000)  # margen 1200
        r = self.run_case()
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA db_connection_watchdog', r.stdout)
        self.assertIn('margen 1200s', r.stdout)

    def test_latido_ilegible_alerta(self):
        self._fresh_all()
        self._beat('source_freshness_watchdog', None, raw='no-es-una-fecha')
        r = self.run_case()
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA source_freshness_watchdog: latido ilegible', r.stdout)

    def test_redis_caido_alerta_no_verificable(self):
        self._fresh_all()
        r = self.run_case(redis_down=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('no se pudo leer Redis', r.stdout)

    def test_nombre_o_margen_invalido_es_error_de_uso(self):
        r = self.run_case('job malo:1200')
        self.assertEqual(r.returncode, 2)
        r = self.run_case('queue_watchdog:abc')
        self.assertEqual(r.returncode, 2)

    def test_argumentos_sustituyen_la_lista_por_defecto(self):
        # Solo se vigila lo pedido: sin ficheros del resto, un job fresco
        # pasado por argumento basta para OK.
        self._beat('market_refresh', 100)
        r = self.run_case('market_refresh:900')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('1 jobs con latido fresco', r.stdout)


if __name__ == '__main__':
    unittest.main()
