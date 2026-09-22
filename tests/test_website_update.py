import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

SPEC = importlib.util.spec_from_file_location('website_update', Path(__file__).resolve().parents[1] / 'server/update_website.py')
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)
SHA = 'a' * 40


def archive(extra=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w') as z:
        for name in updater.REQUIRED:
            z.writestr(f'ailab-site-{SHA}/site/{name}', 'new ' + name)
        z.writestr(f'ailab-site-{SHA}/server/website_only.py', 'do not deploy')
        z.writestr(f'ailab-site-{SHA}/seminar-data/admin-auth.json', 'do not deploy')
        if extra:
            z.writestr(f'ailab-site-{SHA}/site/{extra}', 'escape')
    return buffer.getvalue()


class WebsiteUpdateTests(unittest.TestCase):
    def root(self, name):
        root = Path(name)
        for file, value in [('site/index.html','old'), ('site/obsolete.html','old'), ('server/website_only.py','server'), ('seminar-data/admin-auth.json','secret'),('.env','token')]:
            p=root/file;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(value)
        return root

    def fetch(self, url):
        return json.dumps({'sha':SHA}).encode() if '/commits/main' in url else archive()

    def test_updates_only_site_retains_backup_and_skips_same_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp)
            self.assertTrue(updater.update(root,self.fetch))
            self.assertEqual((root/'site/index.html').read_text(),'new index.html')
            self.assertFalse((root/'site/obsolete.html').exists())
            self.assertEqual((root/'seminar-data/admin-auth.json').read_text(),'secret')
            self.assertEqual((root/'server/website_only.py').read_text(),'server')
            self.assertEqual((root/'.env').read_text(),'token')
            backup=next((root/'website-update-state').glob('backup-*'))
            self.assertEqual((backup/'index.html').read_text(),'old')
            self.assertFalse(updater.update(root,self.fetch))

    def test_network_failure_preserves_live_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp)
            def fail(url):raise OSError('offline')
            with self.assertRaises(OSError):updater.update(root,fail)
            self.assertEqual((root/'site/index.html').read_text(),'old')

    def test_rejects_path_traversal_and_incomplete_archive(self):
        for extra in ['../../outside','nested\\escape','file:stream']:
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ValueError):updater.unpack_site(archive(extra),Path(tmp),SHA)
        with tempfile.TemporaryDirectory() as tmp:
            data=io.BytesIO()
            with zipfile.ZipFile(data,'w') as z:z.writestr(f'ailab-site-{SHA}/site/index.html','incomplete')
            with self.assertRaises(ValueError):updater.unpack_site(data.getvalue(),Path(tmp),SHA)

    def test_failed_swap_rolls_back(self):
        original=Path.rename
        def rename(path, destination):
            if path.parent.name.startswith('staging-'):raise PermissionError('locked')
            return original(path,destination)
        with tempfile.TemporaryDirectory() as tmp:
            root=self.root(tmp)
            with patch.object(Path,'rename',rename):
                with self.assertRaises(PermissionError):updater.update(root,self.fetch)
            self.assertEqual((root/'site/index.html').read_text(),'old')
            self.assertFalse((root/'website-update-state/deployed-commit.txt').exists())


if __name__ == '__main__':unittest.main()
