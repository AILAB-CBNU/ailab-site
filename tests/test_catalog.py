import base64
import json
import unittest
from unittest.mock import patch

from seminar_service import app
from tests import test_people_profiles as fixtures

png = fixtures.png


class CatalogTests(unittest.TestCase):
    setUp = fixtures.PeopleProfilesTests.setUp
    tearDown = fixtures.PeopleProfilesTests.tearDown
    write_roster = fixtures.PeopleProfilesTests.write_roster
    request = fixtures.PeopleProfilesTests.request

    def project(self):
        return {"title": {"ko": "시계열 연구", "en": "Time series"}, "year": 2026,
                "status": "active", "period": "2026–2028", "funder": {"ko": "연구재단"},
                "description": {"ko": "연구 설명"}, "source": "https://example.org/project"}

    def gallery(self):
        return {"title": {"ko": "연구실 세미나"}, "date": "2026-09-23",
                "description": {"ko": "함께한 순간"},
                "image": base64.b64encode(png(metadata=True)).decode()}

    def test_projects_seed_edit_revision_and_server_persistence(self):
        seed = dict(self.project(), id="legacy-test", revision=1)
        (app.SITE_DIR / "data").mkdir()
        (app.SITE_DIR / "data/projects.json").write_text(json.dumps([seed]))
        self.assertEqual(self.request('/api/projects', authenticated=False)[1], [seed])
        status, created, _ = self.request('/api/admin/projects', 'POST', self.project())
        self.assertEqual(status, 201)
        self.assertEqual(len(self.request('/api/projects')[1]), 2)
        update = dict(created, status='completed')
        status, saved, _ = self.request('/api/admin/projects/'+created['id'], 'PUT', update)
        self.assertEqual(status, 200)
        self.assertEqual(saved['revision'], 2)
        self.assertEqual(self.request('/api/admin/projects/'+created['id'], 'PUT', update)[0], 409)
        self.assertEqual(self.request('/api/admin/projects/'+created['id'], 'DELETE', {'revision':1})[0],409)
        self.assertEqual(self.request('/api/admin/projects/'+created['id'], 'DELETE', {'revision':2})[0],200)
        self.assertEqual(self.request('/api/admin/projects/legacy-test', 'DELETE', {'revision':1})[0],200)
        self.assertEqual(self.request('/api/projects')[1], [])
        # Redeploying seed data cannot resurrect records deleted by the admin.
        self.assertTrue((app.DATA_DIR/'catalog/projects.json').is_file())
        self.assertEqual(self.request('/api/projects')[1], [])

    def test_writes_require_login_origin_and_validate_status_date_url(self):
        for kind, payload in [('projects',self.project()),('gallery',self.gallery())]:
            path='/api/admin/'+kind
            self.assertEqual(self.request(path,'POST',payload,authenticated=False)[0],401)
            self.assertEqual(self.request(path,'POST',payload,origin='https://evil.example')[0],403)
        for change in [{'year':True},{'year':2300},{'status':'invented'}, {'source':'javascript:alert(1)'},
                       {'source':'https://user:password@example.org'}, {'title':{}}]:
            self.assertEqual(self.request('/api/admin/projects','POST',dict(self.project(),**change))[0],400)
        for change in [{'date':'2026-02-30'},{'image':'bad base64'}, {'image':base64.b64encode(b'<svg/>').decode()}, {'title':{}}]:
            self.assertEqual(self.request('/api/admin/gallery','POST',dict(self.gallery(),**change))[0],400)
        missing=self.gallery();missing.pop('image')
        self.assertEqual(self.request('/api/admin/gallery','POST',missing)[0],400)

    def install_research_refresh(self, rows, before, after, addition):
        (app.SITE_DIR / 'data').mkdir(exist_ok=True)
        app._atomic_json(app.SITE_DIR / 'data/projects-refresh-20261002.json', {
            'version': 1, 'updates': [{'before': before, 'after': after}], 'additions': [addition]})
        app._atomic_json(app.DATA_DIR / 'catalog/projects.json', rows)

    def test_research_refresh_updates_unchanged_records_once_and_preserves_deletions(self):
        before = dict(self.project(), id='current', revision=4)
        after = dict(before, description={'ko': '최신 연구 내용'}, revision=5)
        addition = dict(self.project(), id='completed-2022', status='completed', revision=1)
        self.install_research_refresh([before], before, after, addition)
        self.assertEqual(self.request('/api/projects')[1], [after, addition])
        self.assertEqual(self.request('/api/projects')[1], [after, addition])
        self.assertEqual(self.request('/api/admin/projects/completed-2022', 'DELETE', {'revision': 1})[0], 200)
        self.assertEqual(self.request('/api/projects')[1], [after])
        self.assertEqual(self.request('/api/admin/projects/current', 'DELETE', {'revision': 5})[0], 200)
        self.assertEqual(self.request('/api/projects')[1], [])

    def test_research_refresh_keeps_later_admin_edits_and_does_not_restore_missing_rows(self):
        before = dict(self.project(), id='current', revision=4)
        after = dict(before, description={'ko': '최신 연구 내용'}, revision=5)
        newer = dict(before, title={'ko': '관리자가 다시 수정한 과제'}, revision=5)
        addition = dict(self.project(), id='completed-2022', status='completed', revision=1)
        self.install_research_refresh([newer], before, after, addition)
        self.assertEqual(self.request('/api/projects')[1], [newer, addition])
        marker = app.DATA_DIR / 'catalog/research-defaults-20261002.applied.json'
        self.assertEqual(json.loads(marker.read_text())['preserved_admin_edits'], ['current'])
        marker.unlink()
        app._atomic_json(app.DATA_DIR / 'catalog/projects.json', [])
        self.assertEqual(self.request('/api/projects')[1], [addition])

    def test_research_refresh_recovers_after_marker_write_failure_without_duplicate_rows(self):
        before = dict(self.project(), id='current', revision=4)
        after = dict(before, description={'ko': '최신 연구 내용'}, revision=5)
        addition = dict(self.project(), id='completed-2022', status='completed', revision=1)
        self.install_research_refresh([before], before, after, addition)
        atomic = app._atomic_json
        def fail_marker(path, value):
            if path.name.endswith('.applied.json'):
                raise OSError('simulated marker failure')
            atomic(path, value)
        with patch.object(app, '_atomic_json', side_effect=fail_marker):
            with self.assertRaises(OSError):
                app._catalog_rows('projects')
        self.assertEqual(app._catalog_rows('projects'), [after, addition])

    def test_gallery_preserves_pixels_hides_replaced_and_deleted_files(self):
        status, row, _=self.request('/api/admin/gallery','POST',self.gallery())
        self.assertEqual(status,201)
        old=row['photo']
        self.assertEqual(self.request(old,'HEAD')[0:2],(200,b''))
        status, image, _=self.request(old,authenticated=False)
        self.assertEqual(status,200)
        self.assertNotIn(b'private camera metadata',image)
        self.assertEqual(app._normalize_people_png(image),image)
        self.assertFalse(any(app.SITE_DIR.rglob('*.png')))
        edit=dict(row,title={'en':'Updated title'})
        status, row, _=self.request('/api/admin/gallery/'+row['id'],'PUT',edit)
        self.assertEqual(status,200)
        self.assertEqual(row['photo'],old)
        edit=dict(row,image=base64.b64encode(png(red=70)).decode())
        status,row,_=self.request('/api/admin/gallery/'+row['id'],'PUT',edit)
        self.assertEqual(status,200)
        self.assertEqual(self.request(old)[0],404)
        self.assertEqual(self.request(row['photo'])[0],200)
        self.assertEqual(self.request('/api/admin/gallery/'+row['id'],'DELETE',{'revision':row['revision']})[0],200)
        self.assertEqual(self.request(row['photo'])[0],404)
        self.assertEqual(self.request('/api/gallery')[1],[])

    def test_gallery_failed_commit_does_not_publish_or_leak_new_file(self):
        with patch.object(app,'_atomic_json',side_effect=OSError('simulated disk failure')):
            self.assertEqual(self.request('/api/admin/gallery','POST',self.gallery())[0],500)
        self.assertEqual(self.request('/api/gallery')[1],[])
        self.assertEqual(list((app.DATA_DIR/'gallery/photos').glob('*.png')),[])
        self.assertEqual(self.request('/gallery-photos/'+'a'*32+'.png')[0],404)
        self.assertEqual(self.request('/gallery-photos/%2e%2e/admin-auth.json')[0],404)


if __name__ == '__main__':
    unittest.main()
