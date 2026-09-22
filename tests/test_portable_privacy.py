"""A portable build must never copy a live server's credentials or uploads."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_people_addon as people_build

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
                'seminar-data/people/profiles.json': 'PRIVATE_PROFILE_OVERRIDES',
                'seminar-data/people/photos/0123456789abcdef0123456789abcdef.png': 'PRIVATE_PROFILE_PHOTO',
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

    def test_people_addon_allowlist_excludes_profile_uploads_and_settings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            files = {
                'site/index.html': '<h1>Public</h1>',
                'site/assets/professor.png': 'PUBLIC_DEFAULT_PHOTO',
                'site/js/people.js': '// public client code',
                'seminar-data/people/profiles.json': 'PRIVATE_PROFILE_OVERRIDES',
                'seminar-data/people/photos/0123456789abcdef0123456789abcdef.png': 'PRIVATE_PROFILE_PHOTO',
                'seminar-data/admin-auth.json': 'PRIVATE_ADMIN_HASH',
                'discord-sync-state/config.json': 'PRIVATE_BOT_TOKEN',
                'seminar_service/config/presenter-map.json': 'PRIVATE_MAPPING',
                'site/seminar-data/people/photos/accidental.png': 'PRIVATE_NESTED_PHOTO',
                'site/config/private.png': 'PRIVATE_NESTED_CONFIG',
                'site/.env': 'PRIVATE_ENV',
                'runtime/python/local.dll': 'PRIVATE_RUNTIME_FILE',
            }
            files.update({name: '# allowed application file' for name in people_build.INCLUDE_FILES})
            for name, content in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            output = root / 'dist/people-update.zip'
            people_build.build_bundle(root, output)
            with zipfile.ZipFile(output) as archive:
                names = set(archive.namelist())
                self.assertEqual(names, set(people_build.INCLUDE_FILES) | {
                    'site/index.html', 'site/assets/professor.png', 'site/js/people.js',
                })
                for name in names:
                    self.assertNotIn(b'PRIVATE_', archive.read(name), name)

    def test_people_addon_rejects_symlink_to_runtime_photo(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site').mkdir()
            (root / 'site/index.html').write_text('public', encoding='utf-8')
            private = root / 'seminar-data/people/photos/private.png'
            private.parent.mkdir(parents=True)
            private.write_bytes(b'PRIVATE_PROFILE_PHOTO')
            (root / 'site/photo.png').symlink_to(private)
            with self.assertRaisesRegex(ValueError, 'Symbolic links'):
                people_build.build_bundle(root, root / 'dist/people-update.zip')


if __name__ == '__main__':
    unittest.main()
