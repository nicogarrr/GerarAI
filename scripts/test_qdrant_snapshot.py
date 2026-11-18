"""Behavior tests: qdrant-snapshot solo borra del servidor lo que tiene copia
local verificada de ESE snapshot.

El binario curl se sustituye por un mock (mismo patron que
test_pg_daily_backup.py): colecciones, snapshots del servidor y fallos van
por entorno. v2 (tras auditoria): el barrido de retencion no borra nada sin
copia local verificada (fichero + .servername + .sha256 que verifica hoy), se
salta colecciones cuya descarga fallo, valida nombres remotos antes de
interpolarlos en URLs y un listado malformado no autoriza borrados.

Run from repo root:
    python -m unittest scripts.test_qdrant_snapshot -v
"""
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
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
    if mode == 'bad_name':
        print('{"result":{"name":"bad name.snapshot"}}')
    else:
        print('{"result":{"name":"%s-2026-11-18T08-00-00.snapshot"}}' % coll)
    sys.exit(0)
if url.endswith('/snapshots'):
    # Listado por coleccion: ficheros <coll>.txt con un nombre por linea.
    if mode == 'bad_list':
        sys.stdout.write('{"result": no-json')
        sys.exit(0)
    coll = url.split('/collections/')[1].split('/')[0]
    listdir = os.environ.get('MOCK_SNAPLIST_DIR')
    names = []
    if listdir:
        p = os.path.join(listdir, coll + '.txt')
        if os.path.exists(p):
            names = [n for n in open(p).read().splitlines() if n]
    extra = os.environ.get('MOCK_SNAPLIST_EXTRA')  # nombre crudo, sin validar
    if extra:
        names.append(extra)
    print('{"result": [%s]}' % ','.join('{"name": "%s"}' % n for n in names))
    sys.exit(0)
if url.endswith('/collections'):
    if mode == 'api_down':
        sys.exit(7)
    if mode == 'bad_collections':
        # Una coleccion valida y luego un objeto sin 'name' (repro del
        # auditor: el parser lanza pero la primera ya salio).
        print('{"result":{"collections":[{"name":"knowledge_rag_v2"},{"sin_name":true}]}}')
        sys.exit(0)
    print(os.environ.get('MOCK_COLLECTIONS',
        '{"result":{"collections":[{"name":"knowledge_rag_v2"},{"name":"docs"}]}}'))
    sys.exit(0)
if '/snapshots/' in url:
    if mode == 'download_fails' and 'docs' in url:
        sys.exit(22)
    out = args[args.index('-o') + 1]
    if mode == 'empty' and 'docs' in url:
        open(out, 'wb').close()
    elif mode == 'bad_tar' and 'docs' in url:
        with open(out, 'wb') as f:
            f.write(b'esto no es un tar')
    else:
        with open(os.environ['MOCK_SNAPSHOT_FILE'], 'rb') as src, open(out, 'wb') as dst:
            dst.write(src.read())
    sys.exit(0)
sys.exit(2)
'''


def make_tar(path: Path) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w') as tf:
        data = b'contenido del snapshot'
        info = tarfile.TarInfo('snapshot.json')
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    payload = buf.getvalue()
    path.write_bytes(payload)
    return payload


class QdrantSnapshotTests(unittest.TestCase):
    def run_case(self, mode='ok', keep='7', preset=None, snaplists=None,
                 extra_name=None):
        """preset: nombres de ficheros viejos en OUT_DIR. snaplists:
        {coleccion: [nombres en el servidor]}. Devuelve (result, out, deleted)."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        binpath = root / 'bin'
        binpath.mkdir()
        mock = binpath / 'curl'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        snapfile = root / 'snap.tar'
        make_tar(snapfile)
        out = root / 'out'
        deletes = root / 'deletes'
        if preset:
            out.mkdir()
            for name in preset:
                (out / name).write_bytes(snapfile.read_bytes())
        env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                   MOCK_MODE=mode, OUT_DIR=str(out), KEEP=keep,
                   DELETES=str(deletes), MOCK_SNAPSHOT_FILE=str(snapfile))
        if snaplists is not None:
            listdir = root / 'lists'
            listdir.mkdir()
            for coll, names in snaplists.items():
                (listdir / (coll + '.txt')).write_text('\n'.join(names) + '\n')
            env['MOCK_SNAPLIST_DIR'] = str(listdir)
        if extra_name is not None:
            env['MOCK_SNAPLIST_EXTRA'] = extra_name
        result = subprocess.run(['bash', str(SCRIPT)], env=env,
                                capture_output=True, text=True)
        deleted = deletes.read_text().splitlines() if deletes.exists() else []
        return result, out, deleted

    @staticmethod
    def sidecars(out: Path, snapfile_name: str, server_name: str):
        """Marca un preset como copia verificada de un snapshot del servidor."""
        f = out / snapfile_name
        import hashlib
        digest = hashlib.sha256(f.read_bytes()).hexdigest()
        (out / (snapfile_name + '.sha256')).write_text('%s  %s\n' % (digest, snapfile_name))
        (out / (snapfile_name + '.servername')).write_text(server_name)

    # --- flujo feliz ---

    def test_ok_descarga_verifica_y_rota(self):
        preset = [f'knowledge_rag_v2-2026010{i}.snapshot' for i in range(8)]
        r, out, deleted = self.run_case(keep='2', preset=preset)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        snaps = sorted(p.name for p in out.glob('knowledge_rag_v2-*.snapshot')
                       if not p.name.endswith(('.sha256', '.servername')))
        self.assertEqual(len(snaps), 2)  # retencion local: el nuevo + el mas reciente
        self.assertTrue(any('2026' in s and '2026010' not in s for s in snaps))
        docs = [p for p in out.glob('docs-*.snapshot') if p.suffix == '.snapshot']
        self.assertEqual(len(docs), 1)
        # La copia local es tar listable y lleva huella y nombre de servidor.
        self.assertTrue((out / (docs[0].name + '.sha256')).exists())
        self.assertEqual((out / (docs[0].name + '.servername')).read_text(),
                         'docs-2026-11-18T08-00-00.snapshot')
        self.assertIn('sha256', r.stdout)
        # El snapshot del dia se borra del servidor tras verificar la copia.
        self.assertEqual(len(deleted), 2)

    def test_descarga_fallida_no_borra_nada_de_esa_coleccion(self):
        """v2 (repro del auditor): docs falla y tiene 3 remotos con KEEP=1:
        el barrido NO borra ningun snapshot de docs."""
        r, out, deleted = self.run_case(
            mode='download_fails', keep='1',
            snaplists={'docs': ['docs-2026-01-01T00-00-00.snapshot',
                                'docs-2026-01-02T00-00-00.snapshot',
                                'docs-2026-01-03T00-00-00.snapshot'],
                       'knowledge_rag_v2': []})
        self.assertEqual(r.returncode, 1)
        self.assertIn('retencion de docs pospuesta', r.stdout)
        self.assertFalse(any('/docs/' in d for d in deleted))
        # knowledge_rag_v2 si se descargo y verifico: el suyo del dia se borra.
        self.assertTrue(any('knowledge_rag_v2' in d for d in deleted))

    def test_borrado_servidor_fallido_es_error_pero_conserva_local(self):
        r, out, _ = self.run_case(mode='delete_fails')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no se pudo borrar el snapshot del servidor', r.stdout)
        self.assertEqual(len([p for p in out.glob('*.snapshot')]), 2)

    # --- regla: sin copia local verificada de ESE snapshot no se borra ---

    def test_barrido_exige_copia_local_verificada(self):
        """Snapshot remoto antiguo SIN copia local: no se borra, visible."""
        r, out, deleted = self.run_case(
            keep='1',
            snaplists={'knowledge_rag_v2': ['knowledge_rag_v2-2026-01-01T00-00-00.snapshot',
                                            'knowledge_rag_v2-2026-01-02T00-00-00.snapshot'],
                       'docs': []})
        self.assertEqual(r.returncode, 1)
        self.assertIn('NO tiene copia local verificada', r.stdout)
        self.assertFalse(any('2026-01-01' in d for d in deleted))

    def test_barrido_con_sidecars_validos_borra(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        binpath = root / 'bin'
        binpath.mkdir()
        (binpath / 'curl').write_text(MOCK)
        (binpath / 'curl').chmod(0o755)
        snapfile = root / 'snap.tar'
        make_tar(snapfile)
        out = root / 'out'
        out.mkdir()
        # Copia local verificada del snapshot remoto viejo.
        local = out / 'knowledge_rag_v2-20260101.snapshot'
        local.write_bytes(snapfile.read_bytes())
        self.sidecars(out, local.name, 'knowledge_rag_v2-2026-01-01T00-00-00.snapshot')
        listdir = root / 'lists'
        listdir.mkdir()
        (listdir / 'knowledge_rag_v2.txt').write_text(
            'knowledge_rag_v2-2026-01-01T00-00-00.snapshot\n'
            'knowledge_rag_v2-2026-01-02T00-00-00.snapshot\n')
        (listdir / 'docs.txt').write_text('')
        deletes = root / 'deletes'
        env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                   MOCK_MODE='ok', OUT_DIR=str(out), KEEP='1',
                   DELETES=str(deletes), MOCK_SNAPSHOT_FILE=str(snapfile),
                   MOCK_SNAPLIST_DIR=str(listdir))
        r = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        deleted = deletes.read_text().splitlines()
        self.assertTrue(any('2026-01-01' in d for d in deleted))
        self.assertIn('copia local verificada', r.stdout)

    def test_sha256_corrupto_no_autoriza_borrado(self):
        """La huella registrada ya no casa con el fichero: no hay copia
        verificada HOY, asi que el remoto no se borra."""
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        binpath = root / 'bin'
        binpath.mkdir()
        (binpath / 'curl').write_text(MOCK)
        (binpath / 'curl').chmod(0o755)
        snapfile = root / 'snap.tar'
        make_tar(snapfile)
        out = root / 'out'
        out.mkdir()
        local = out / 'knowledge_rag_v2-20260101.snapshot'
        local.write_bytes(snapfile.read_bytes())
        self.sidecars(out, local.name, 'knowledge_rag_v2-2026-01-01T00-00-00.snapshot')
        local.write_bytes(b'corrupto')  # el contenido cambio tras registrar la huella
        listdir = root / 'lists'
        listdir.mkdir()
        (listdir / 'knowledge_rag_v2.txt').write_text(
            'knowledge_rag_v2-2026-01-01T00-00-00.snapshot\n'
            'knowledge_rag_v2-2026-01-02T00-00-00.snapshot\n')
        (listdir / 'docs.txt').write_text('')
        deletes = root / 'deletes'
        env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                   MOCK_MODE='ok', OUT_DIR=str(out), KEEP='1',
                   DELETES=str(deletes), MOCK_SNAPSHOT_FILE=str(snapfile),
                   MOCK_SNAPLIST_DIR=str(listdir))
        r = subprocess.run(['bash', str(SCRIPT)], env=env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)
        self.assertFalse(deletes.exists() and any('2026-01-01' in d for d in deletes.read_text().splitlines()))

    # --- validacion ---

    def test_snapshot_no_tar_es_error_y_no_borra(self):
        """v2: la verificacion ya no es solo tamano>0: un tar ilegible no es
        copia valida, y el snapshot del servidor no se borra."""
        r, out, deleted = self.run_case(mode='bad_tar')
        self.assertEqual(r.returncode, 1)
        self.assertIn('no es un tar listable', r.stdout)
        self.assertFalse(any('/docs/' in d for d in deleted))
        self.assertEqual([p for p in out.glob('*.part')], [])
        self.assertEqual([p for p in out.glob('docs-*.snapshot')], [])

    def test_nombre_creado_invalido_no_se_descarga_ni_borra(self):
        r, out, deleted = self.run_case(mode='bad_name')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nombre de snapshot invalido', r.stdout)
        self.assertEqual(deleted, [])
        self.assertEqual([p for p in out.glob('*.snapshot')], [])

    def test_listado_malformado_no_borra_nada(self):
        """v2 (repro del auditor): el listado se valida ANTES de formar la
        lista de borrado; un listado ilegible es ERROR y no borra."""
        r, out, deleted = self.run_case(
            mode='bad_list', keep='1',
            snaplists={'knowledge_rag_v2': ['knowledge_rag_v2-2026-01-01T00-00-00.snapshot']})
        self.assertEqual(r.returncode, 1)
        self.assertIn('ilegible o con nombres invalidos', r.stdout)
        # Solo los borrados del dia (tras descarga verificada), ninguno del barrido.
        self.assertFalse(any('2026-01-01' in d for d in deleted))

    def test_nombre_remoto_invalido_en_listado_no_se_borra(self):
        """Un nombre con espacios/barras nunca se interpola en una URL."""
        r, out, deleted = self.run_case(
            keep='1', snaplists={'knowledge_rag_v2': [], 'docs': []},
            extra_name='bad name.snapshot')
        self.assertEqual(r.returncode, 1)
        self.assertIn('nombres invalidos', r.stdout)
        self.assertFalse(any('bad' in d for d in deleted))

    # --- comportamiento heredado ---

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
        viejos = [p for p in out.glob('docs-2026*.snapshot')]
        self.assertEqual(len(viejos), 5)  # un fallo nunca purga copias buenas
        self.assertEqual(list(out.glob('*.part')), [])

    def test_snapshot_vacio_es_error(self):
        r, out, _ = self.run_case(mode='empty')
        self.assertEqual(r.returncode, 1)
        self.assertIn('vacio', r.stdout)
        self.assertEqual(list(out.glob('*.part')), [])
        self.assertEqual([p for p in out.glob('docs-*.snapshot')], [])

    def test_listado_de_colecciones_parcial_no_toca_nada(self):
        """v3 (repro del auditor): una coleccion valida + una sin name.

        En v2 el parser lanzaba pero mapfile conservaba la primera: se
        descargaba y borraba su snapshot y salia OK con inventario parcial.
        """
        r, out, deleted = self.run_case(mode='bad_collections')
        self.assertEqual(r.returncode, 1)
        self.assertIn('ilegible o con nombres invalidos', r.stdout)
        self.assertEqual(deleted, [])
        self.assertEqual([p for p in out.glob('*.snapshot')], [])
        self.assertNotIn('OK:', r.stdout)

    def test_sin_colecciones_es_error(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        binpath = Path(tmp.name) / 'bin'
        binpath.mkdir()
        mock = binpath / 'curl'
        mock.write_text(MOCK)
        mock.chmod(0o755)
        snapfile = Path(tmp.name) / 'snap.tar'
        make_tar(snapfile)
        env = dict(os.environ, PATH=str(binpath) + ':' + os.environ['PATH'],
                   MOCK_COLLECTIONS='{"result":{"collections":[]}}',
                   MOCK_SNAPSHOT_FILE=str(snapfile),
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
