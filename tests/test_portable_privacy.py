"""A portable build must never copy a live server's credentials or uploads."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('portable_build', Path(__file__).resolve().parents[1] / 'scripts/build_windows_portable.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class PortablePrivacyTests(unittest.TestCase):
    def test_live_state_is_replaced_by_fresh_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                'site/index.html': '<h1>Public</h1>',
                'seminar_service/app.py': '# code',
                'seminar_service/config/presenter-map.example.json': '{}',
                'seminar_service/config/presenter-map.json': 'PRIVATE_USER_MAPPING',
                'seminar_service/config/extra.json': 'PRIVATE_CONFIG',
                'seminar-data/admin-auth.json': 'PRIVATE_ADMIN_HASH',
                'seminar-data/index.json': 'PRIVATE_SEMINAR_METADATA',
                'seminar-data/items/notes.pdf': 'PRIVATE_ATTACHMENT',
                'seminar-inbox/pending.json': 'PRIVATE_PENDING_UPLOAD',
                'seminar-inbox/README.md': '# inbox',
                'discord-sync-state/config.json': 'PRIVATE_BOT_TOKEN',
                '.env': 'PRIVATE_ENV',
                'server/local.pem': 'PRIVATE_KEY',
            }
            for name, content in files.items():
                p = root / name
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content)
            def fake_download(path):
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('placeholder.txt', 'runtime')
            output = root / 'dist/test.zip'
            with patch.multiple(build, ROOT=root, OUTPUT=output, INCLUDE_FILES=()), patch.object(build, 'download_runtime', fake_download), patch.object(build, 'download_caddy', fake_download):
                build.main()
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(archive.read(build.PREFIX + '/seminar-data/index.json'), b'[]\n')
                self.assertIn(build.PREFIX + '/site/index.html', archive.namelist())
                for name in archive.namelist():
                    self.assertNotIn(b'PRIVATE_', archive.read(name), name)


if __name__ == '__main__':
    unittest.main()
