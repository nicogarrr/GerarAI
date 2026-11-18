"""Behavior tests: qdrant-snapshot solo guarda snapshots descargados y verificados.

El binario curl se sustituye por un mock (mismo patron que
test_pg_daily_backup.py): las colecciones y los fallos van por entorno.

Run from repo root:
    python -m unittest scripts.test_qdrant_snapshot -v
"""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parent / 'ops' / 'qdrant-snapshot.sh'

MOCK = '''#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
url = next((a for a in args if a.startswith('http')), '')
mode = os.environ.get('MOCK_MODE', 'ok')
if '-X' in args and 'DELETE' in args:
    deletes = os.environ.get('DELETES')
    if deletes:
        with open(deletes, 'a') as f:
            f.write(url + chr(10))
    sys.exit(22 if mode == 'delete_fails' else 0)
if '-X' in args and 'POST' in args:
    if mode == 'create_fails':
        sys.exit(22)
    coll = url.split('/collections/')[1].split('/')[0]
    print('{"result":{"name":"%s-2026.snap"}}' % coll)
    sys.exit(0)
if url.endswith('/snapshots'):
    print(os.environ.get('MOCK_SERVER_SNAPSHOTS', '{"result":[]}'))
    sys.exit(0)
if url.endswith('/collections'):
    if mode == 'api_down':
        sys.exit(7)
    print(os.environ.get('MOCK_COLLECTIONS',
        '{"result":{"collections":[{"name":"knowledge_rag_v2"},{"name":"docs"}]}}'))
    sys.exit(0)
if '/snapshots/' in url:
    if mode == 'download_fails' and 'docs' in url:
        sys.exit(22)
    out = args[args.index('-o') + 1]
    if mode == 'empty' and 'docs' in url:
        open(out, 'wb').close()
    else:
        with open(out, 'wb') as f:
            f.write(b'snapshot-bytes')
    sys.exit(0)
sys.exit(2)
'''


class QdrantSnapshotTests(unittest.TestCase):
    def run_case(self, mode='ok', keep='7', preset=None, server_snaps=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        binpath = root / 'bin'
        binpath.mkdir()
        mock = binpath / 'curl'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        out = root / 'out'
        deletes = root / 'deletes'
        if preset:
            out.mkdir()
            for name in preset:
                (out / name).write_bytes(b'viejo')
        env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                   MOCK_MODE=mode, OUT_DIR=str(out), KEEP=keep,
                   DELETES=str(deletes))
        if server_snaps is not None:
            import json
            env['MOCK_SERVER_SNAPSHOTS'] = json.dumps(
                {"result": [{"name": n} for n in server_snaps]})
        result = subprocess.run(['bash', str(SCRIPT)], env=env,
                                capture_output=True, text=True)
        deleted = deletes.read_text().splitlines() if deletes.exists() else []
        return result, out, deleted

    def test_ok_descarga_todas_y_rota(self):
        preset = [f'knowledge_rag_v2-2026010{i}.snapshot' for i in range(8)]
        r, out, deleted = self.run_case(keep='2', preset=preset)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        snaps = sorted(p.name for p in out.glob('knowledge_rag_v2-*.snapshot'))
        self.assertEqual(len(snaps), 2)  # retencion: el nuevo + el mas reciente
        self.assertTrue(any('2026' in s and '2026010' not in s for s in snaps))
        docs = list(out.glob('docs-*.snapshot'))
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].read_bytes(), b'snapshot-bytes')
        # El snapshot del servidor se borra tras descargarlo y verificarlo.
        self.assertEqual(len(deleted), 2)
        self.assertTrue(any('knowledge_rag_v2' in d for d in deleted))
        self.assertTrue(any('/docs/' in d for d in deleted))

    def test_descarga_fallida_no_borra_el_snapshot_del_servidor(self):
        r, out, deleted = self.run_case(mode='download_fails')
        self.assertEqual(r.returncode, 1)
        # docs fallo la descarga: su snapshot queda en el servidor.
        self.assertFalse(any('/docs/' in d for d in deleted))
        # knowledge_rag_v2 se descargo y verifico: el suyo si se borra.
        self.assertTrue(any('knowledge_rag_v2' in d for d in deleted))

    def test_borrado_servidor_fallido_es_error_pero_conserva_local(self):
        r, out, _ = self.run_case(mode='delete_fails')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no se pudo borrar el snapshot del servidor', r.stdout)
        self.assertEqual(len(list(out.glob('*.snapshot'))), 2)

    def test_retencion_tambien_en_el_servidor(self):
        viejos = [f'knowledge_rag_v2-2026-11-0{i}.snap' for i in range(5)]
        r, out, deleted = self.run_case(keep='2', server_snaps=viejos)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        # KEEP=2 en el servidor: se borran los 3 mas antiguos de cada coleccion
        # (el mock devuelve la misma lista para ambas; se mide la de knowledge).
        barridos = [d for d in deleted
                    if '/collections/knowledge_rag_v2/' in d and '2026-11-0' in d]
        self.assertEqual(len(barridos), 3)
        self.assertFalse(any('2026-11-03' in d or '2026-11-04' in d for d in barridos))

    def test_api_caida_no_toca_copias(self):
        r, out, _ = self.run_case(mode='api_down', preset=['knowledge_rag_v2-20260101.snapshot'])
        self.assertEqual(r.returncode, 1)
        self.assertIn('API no disponible', r.stdout)
        self.assertTrue((out / 'knowledge_rag_v2-20260101.snapshot').exists())

    def test_fallo_parcial_no_rota_nada(self):
        preset = [f'docs-2026010{i}.snapshot' for i in range(5)]
        r, out, _ = self.run_case(mode='download_fails', keep='1', preset=preset)
        self.assertEqual(r.returncode, 1)
        self.assertIn('ERROR descargando snapshot de docs', r.stdout)
        # Las 5 copias viejas de docs siguen ahi: un fallo nunca purga.
        self.assertEqual(len(list(out.glob('docs-2026*.snapshot'))), 5)
        # El .part del fallo no queda.
        self.assertEqual(list(out.glob('*.part')), [])

    def test_snapshot_vacio_es_error(self):
        r, out, _ = self.run_case(mode='empty')
        self.assertEqual(r.returncode, 1)
        self.assertIn('vacio', r.stdout)
        self.assertEqual(list(out.glob('*.part')), [])
        self.assertEqual(list(out.glob('docs-*.snapshot')), [])

    def test_sin_colecciones_es_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        binpath = Path(tmp.name) / 'bin'
        binpath.mkdir()
        mock = binpath / 'curl'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                   MOCK_COLLECTIONS='{"result":{"collections":[]}}',
                   OUT_DIR=str(Path(tmp.name) / 'out'))
        r = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertIn('ninguna coleccion', r.stdout)

    def test_keep_invalido_es_uso_incorrecto(self):
        r, _, _ = self.run_case(keep='abc')
        self.assertEqual(r.returncode, 2)
        r, _, _ = self.run_case(keep='0')
        self.assertEqual(r.returncode, 2)


if __name__ == '__main__':
    unittest.main()
