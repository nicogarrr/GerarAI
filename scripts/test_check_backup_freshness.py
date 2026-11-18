"""Behavior tests: check-backup-freshness alerta solo con lo medido y nunca toca nada.

Run from repo root:
    python -m unittest scripts.test_check_backup_freshness -v
"""
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

SCRIPT = Path(__file__).resolve().parent / 'ops' / 'check-backup-freshness.sh'

HORA = 3600


class FreshnessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.pg = self.root / 'pg'
        self.mongo = self.root / 'mongo'
        self.garage = self.root / 'garage'
        self.qdrant = self.root / 'qdrant'
        for d in (self.pg, self.mongo, self.garage, self.qdrant):
            d.mkdir()

    def _touch(self, path: Path, age_hours: float):
        path.write_bytes(b'artefacto')
        viejo = time.time() - age_hours * HORA
        os.utime(path, (viejo, viejo))

    def run_case(self, **env_over):
        env = dict(os.environ,
                   PG_DIR=str(self.pg), MONGO_DIR=str(self.mongo),
                   GARAGE_DIR=str(self.garage), QDRANT_DIR=str(self.qdrant))
        env.update(env_over)
        return subprocess.run(['bash', str(SCRIPT)], env=env,
                              capture_output=True, text=True)

    def _fresh_set(self):
        self._touch(self.pg / 'pg-daily-20261118T020000-1.sql.gz.verified', 5)
        self._touch(self.mongo / 'mongo-20261118-040000.archive.gz.age', 4)
        self._touch(self.garage / 'garage-20261118.tar.gz', 3)
        self._touch(self.qdrant / 'knowledge_rag_v2-20261118.snapshot', 2)

    def test_todo_fresco_es_ok(self):
        self._fresh_set()
        r = self.run_case()
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn('OK postgres', r.stdout)
        self.assertIn('OK mongo', r.stdout)
        self.assertIn('OK garage', r.stdout)
        self.assertIn('OK qdrant', r.stdout)

    def test_qdrant_viejo_alerta(self):
        self._fresh_set()
        self._touch(self.qdrant / 'knowledge_rag_v2-20261118.snapshot', 50)
        r = self.run_case()
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA qdrant', r.stdout)

    def test_qdrant_off_explicito_no_alerta(self):
        self._fresh_set()
        r = self.run_case(QDRANT_CHECK='off')
        self.assertEqual(r.returncode, 0)
        self.assertIn('QDRANT_CHECK=off', r.stdout)

    def test_pg_viejo_alerta_con_edad_medida(self):
        self._fresh_set()
        self._touch(self.pg / 'pg-daily-20261118T020000-1.sql.gz.verified', 49)
        r = self.run_case()
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA postgres', r.stdout)
        self.assertIn('49 h', r.stdout)
        self.assertIn('OK mongo', r.stdout)

    def test_dump_pg_sin_marca_verified_no_cuenta(self):
        # Un dump reciente SIN restaurar no es un backup: solo cuenta .verified.
        self._touch(self.pg / 'pg-daily-20261118T020000-1.sql.gz', 1)
        self._touch(self.mongo / 'mongo-20261118-040000.archive.gz.age', 4)
        self._touch(self.garage / 'garage-20261118.tar.gz', 3)
        r = self.run_case()
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA postgres', r.stdout)
        self.assertIn('ningun artefacto', r.stdout)

    def test_directorio_mongo_inexistente_alerta(self):
        self._fresh_set()
        r = self.run_case(MONGO_DIR=str(self.root / 'no-existe'))
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA mongo', r.stdout)

    def test_garage_sin_configurar_alerta(self):
        # El backup de Garage vive solo en la VM: sin GARAGE_DIR queda sin
        # vigilar y eso es exactamente lo que hay que avisar.
        self._touch(self.pg / 'pg-daily-20261118T020000-1.sql.gz.verified', 5)
        self._touch(self.mongo / 'mongo-20261118-040000.archive.gz.age', 4)
        env = dict(os.environ, PG_DIR=str(self.pg), MONGO_DIR=str(self.mongo),
                   QDRANT_DIR=str(self.qdrant))
        env.pop('GARAGE_DIR', None)
        r = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA garage', r.stdout)
        self.assertIn('GARAGE_DIR', r.stdout)

    def test_garage_off_explicito_no_alerta(self):
        self._fresh_set()
        r = self.run_case(GARAGE_CHECK='off')
        self.assertEqual(r.returncode, 0)
        self.assertIn('GARAGE_CHECK=off', r.stdout)

    def test_umbral_configurable(self):
        self._fresh_set()
        self._touch(self.mongo / 'mongo-20261118-040000.archive.gz.age', 30)
        r = self.run_case(MONGO_MAX_AGE_H='48')
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_case(MONGO_MAX_AGE_H='24')
        self.assertEqual(r.returncode, 1)
        self.assertIn('ALERTA mongo', r.stdout)

    def test_umbral_no_numerico_es_uso_incorrecto(self):
        r = self.run_case(PG_MAX_AGE_H='abc')
        self.assertEqual(r.returncode, 2)
        self.assertIn('PG_MAX_AGE_H', r.stdout)

    def test_solo_lectura(self):
        # El chequeo no crea, borra ni modifica nada.
        self._fresh_set()
        antes = {p: (p.stat().st_mtime_ns, p.read_bytes()) for d in
                 (self.pg, self.mongo, self.garage, self.qdrant) for p in d.iterdir()}
        r = self.run_case()
        self.assertEqual(r.returncode, 0)
        despues = {p: (p.stat().st_mtime_ns, p.read_bytes()) for d in
                   (self.pg, self.mongo, self.garage, self.qdrant) for p in d.iterdir()}
        self.assertEqual(antes, despues)


if __name__ == '__main__':
    unittest.main()
