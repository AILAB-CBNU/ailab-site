"""A portable build must never copy a live server's credentials or uploads."""
import importlib.util
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts import build_people_addon as people_build
from scripts import build_discord_addon as discord_build
from scripts import build_seminar_addon as seminar_build
from scripts import build_lab_addon as lab_build
from scripts import build_briefing_addon as briefing_build

SPEC = importlib.util.spec_from_file_location('portable_build', Path(__file__).resolve().parents[1] / 'scripts/build_windows_portable.py')
build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(build)


class PortablePrivacyTests(unittest.TestCase):
    def test_briefing_package_excludes_api_keys_and_personal_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = {'site/index.html': '<h1>Public</h1>'}
            public.update({name: '# allowed source' for name in briefing_build.INCLUDE_FILES})
            private = {'.env.local': 'PRIVATE_OPENAI_KEY',
                       'discord-sync-state/briefing-config.json': 'PRIVATE_CONFIG',
                       'discord-sync-state/briefings/ledger.json': 'PRIVATE_PERSONAL_TASKS',
                       'logs/discord-sync.log': 'PRIVATE_LOG'}
            for name, content in (public | private).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            output = root / 'briefing.zip'
            briefing_build.build_bundle(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(public))
                for name in archive.namelist():
                    self.assertNotIn(b'PRIVATE_', archive.read(name))

    def test_lab_addon_includes_seed_but_excludes_server_catalog_and_photos(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = {'site/index.html': '<h1>Public</h1>', 'site/gallery.html': 'Gallery',
                      'site/data/projects.json': '[]'}
            public.update({name: '# allowed source' for name in lab_build.INCLUDE_FILES})
            private = {'seminar-data/catalog/projects.json': 'PRIVATE_PROJECTS',
                       'seminar-data/catalog/gallery.json': 'PRIVATE_GALLERY',
                       'seminar-data/gallery/photos/local.png': 'PRIVATE_PHOTO',
                       'site/data/private.json': 'PRIVATE_JSON',
                       'site/seminar-data/gallery/photos/local.png': 'PRIVATE_NESTED_PHOTO'}
            for name, content in (public | private).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)
            output = root / 'update.zip'
            lab_build.build_bundle(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(public))
                for name in archive.namelist():
                    self.assertNotIn(b'PRIVATE_', archive.read(name))

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

    def test_discord_addon_contains_gateway_vendor_without_private_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            public = {
                'site/index.html': '<h1>Public</h1>',
                'site/seminars.html': '<h1>Seminars</h1>',
                'site/js/seminars.js': '// client code',
            }
            public.update({name: '# required source or license' for name in discord_build.INCLUDE_FILES})
            private = {
                'discord-sync-state/config.json': 'PRIVATE_BOT_TOKEN',
                'discord-sync-state/forms/123.json': 'PRIVATE_FORM_STATE',
                'discord-sync-state/checkpoint.json': 'PRIVATE_CHECKPOINT',
                'discord_sync/config.json': 'PRIVATE_UNLISTED_CONFIG',
                'discord_sync/vendor/websocket/unlisted.py': 'PRIVATE_UNLISTED_MODULE',
                'discord_sync/vendor/websocket/__pycache__/_core.pyc': 'PRIVATE_CACHE',
                'discord_sync/vendor/websocket/local.key': 'PRIVATE_KEY',
                'seminar-data/index.json': 'PRIVATE_SEMINAR_METADATA',
                'seminar-data/items/private.pdf': 'PRIVATE_UPLOAD',
                'seminar-data/people/photos/private.png': 'PRIVATE_PROFILE_PHOTO',
                'seminar-inbox/pending.json': 'PRIVATE_PENDING_UPLOAD',
                'seminar_service/config/presenter-map.json': 'PRIVATE_MAPPING',
                'site/discord-sync-state/forms/private.js': 'PRIVATE_NESTED_FORM',
                'site/config/token.js': 'PRIVATE_NESTED_CONFIG',
                'site/__pycache__/private.pyc': 'PRIVATE_SITE_CACHE',
                'runtime/python/python.exe': 'PRIVATE_RUNTIME',
                '.env': 'PRIVATE_ENV',
            }
            for name, content in (public | private).items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
            output = root / 'dist/discord-update.zip'
            discord_build.build_bundle(root, output)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(set(archive.namelist()), set(public))
                self.assertIn('discord_sync/gateway.py', archive.namelist())
                self.assertIn('discord_sync/vendor/websocket/_core.py', archive.namelist())
                self.assertIn('discord_sync/vendor/LICENSE.websocket-client', archive.namelist())
                self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))
                for name in archive.namelist():
                    self.assertNotIn(b'PRIVATE_', archive.read(name), name)

    def test_discord_addon_rejects_symlinked_vendor_file_or_parent(self):
        for linked_parent in (False, True):
            with self.subTest(linked_parent=linked_parent), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for name in discord_build.INCLUDE_FILES + ('site/index.html',):
                    path = root / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text('public', encoding='utf-8')
                private = root / 'discord-sync-state/config.json'
                private.parent.mkdir()
                private.write_text('PRIVATE_BOT_TOKEN', encoding='utf-8')
                linked = root / 'discord_sync/vendor/websocket/_core.py'
                if linked_parent:
                    vendor = root / 'discord_sync/vendor'
                    moved = root / 'discord-sync-state/vendor'
                    vendor.rename(moved)
                    vendor.symlink_to(moved, target_is_directory=True)
                else:
                    linked.unlink()
                    linked.symlink_to(private)
                with self.assertRaisesRegex(ValueError, 'Symbolic links'):
                    discord_build.build_bundle(root, root / 'dist/discord-update.zip')

    def test_all_addons_share_complete_discord_runtime_allowlist(self):
        required = set(seminar_build.DISCORD_RUNTIME_FILES)
        for addon in (seminar_build, people_build, discord_build):
            with self.subTest(builder=addon.__name__):
                self.assertTrue(required.issubset(addon.INCLUDE_FILES))
                self.assertIn('docs/discord-form-update-20260922.md', addon.INCLUDE_FILES)
                self.assertEqual(len(addon.INCLUDE_FILES), len(set(addon.INCLUDE_FILES)))


if __name__ == '__main__':
    unittest.main()
