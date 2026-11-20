import base64
import json
import os
from pathlib import Path
import secrets
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app
from fastapi.testclient import TestClient


class PanelIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_data = app.DATA
        cls.temp = tempfile.TemporaryDirectory(prefix='api-tests-', dir=app.ROOT / 'data')
        app.DATA = Path(cls.temp.name)
        cls.password = 'quiz1332'
        cls.env = patch.dict(os.environ, {'PANEL_PASSWORD': cls.password, 'PANEL_USER': 'admin',
                                         'PANEL_ORIGIN': 'http://testserver', 'PANEL_PREVIEW_READONLY': '0'})
        cls.env.start()
        cls.worker = patch.object(app, 'worker', lambda: None)
        cls.original_worker = staticmethod(app.worker)
        cls.worker.start()
        cls.client_context = TestClient(app.app)
        cls.client = cls.client_context.__enter__()
        token = base64.b64encode(('user1:' + cls.password).encode()).decode()
        cls.auth = {'Authorization': 'Basic ' + token, 'Origin': 'http://testserver'}
        cls.video = app.ROOT.parent / 'reels-template/renders/football-nostalgia-2026-11-13/video.mp4'
        if not cls.video.exists():
            cls.video = Path(cls.temp.name) / 'fixture.mp4'
            subprocess.run([app.FFMPEG, '-v', 'error', '-y', '-f', 'lavfi', '-i', 'color=c=purple:s=180x320:d=1',
                            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(cls.video)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        cls.worker.stop()
        cls.env.stop()
        app.DATA = cls.previous_data
        cls.temp.cleanup()

    def test_auth_and_origin_protection(self):
        self.assertEqual(self.client.get('/').status_code, 401)
        self.assertEqual(self.client.get('/api/videos').status_code, 401)
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertEqual(self.client.get('/library.js', headers=self.auth).status_code, 200)
        bad = dict(self.auth, Origin='https://elsewhere.invalid')
        self.assertEqual(self.client.post('/api/bank/sync', headers=bad).status_code, 403)
        self.assertEqual(self.client.get('/.env', headers=self.auth).status_code, 404)

    def upload(self):
        with self.video.open('rb') as f:
            return self.client.post('/api/upload', headers=self.auth, files={'video': ('video.mp4', f, 'video/mp4')},
                                    data={'title': 'آزمون ویدیوی واقعی', 'caption': 'کپشن فارسی', 'category': 'فوتبال'})

    def test_real_upload_dedup_ranges_and_publication_tracking(self):
        first = self.upload()
        self.assertEqual(first.status_code, 200, first.text)
        video = first.json()['video']
        self.assertEqual(self.upload().json()['created'], False)
        self.assertEqual(self.client.get('/api/videos', headers=self.auth).json()['total'], 1)
        self.assertEqual(self.client.get(video['video_url']).status_code, 401)
        part = self.client.get(video['video_url'], headers={**self.auth, 'Range': 'bytes=0-99'})
        self.assertEqual(part.status_code, 206)
        self.assertEqual(len(part.content), 100)
        self.assertEqual(self.client.get(video['cover_url'], headers=self.auth).status_code, 200)
        self.client.post('/api/videos/' + video['id'] + '/shared', headers=self.auth)
        after = self.client.get('/api/videos/' + video['id'], headers=self.auth).json()
        self.assertEqual(after['status'], 'ready')
        self.assertEqual(after['share_count'], 1)
        data = {k: after[k] for k in ('title','category','caption','status','intended_mode','published_url')}
        data['status'] = 'trial'
        self.assertEqual(self.client.patch('/api/videos/' + video['id'], headers=self.auth, json=data).status_code, 200)
        self.assertEqual(self.client.get('/api/videos?status=trial', headers=self.auth).json()['total'], 1)
        data['published_url'] = 'javascript:alert(1)'
        self.assertEqual(self.client.patch('/api/videos/' + video['id'], headers=self.auth, json=data).status_code, 422)

    def test_two_accounts_actions_and_publication_order(self):
        user2 = {**self.auth, 'Authorization': 'Basic ' + base64.b64encode(b'user2:quiz1332').decode()}
        self.assertEqual(self.client.get('/api/me', headers=user2).json()['username'], 'user2')
        legacy = {**self.auth, 'Authorization': 'Basic ' + base64.b64encode(('admin:' + self.password).encode()).decode()}
        self.assertEqual(self.client.get('/api/me', headers=legacy).status_code, 401)
        a, b = secrets.token_hex(16), secrets.token_hex(16)
        with app.db() as c:
            for ident, created in [(a, 100), (b, 200)]:
                c.execute("INSERT INTO videos(id,title,category,caption,created,size,duration,sha256) VALUES(?,?,?,?,?,?,?,?)", (ident, 'workflow', 'workflow-test', 'caption', created, 100, 39, ident))
        def action(ident, name, headers=self.auth):
            response = self.client.post('/api/videos/' + ident + '/actions/' + name, headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            return response.json()
        self.assertFalse(action(a, 'video')['complete'])
        self.assertFalse(action(a, 'caption')['complete'])
        self.assertFalse(action(a, 'cover', user2)['complete'])
        queued = self.client.get('/api/videos?status=queued&category=workflow-test', headers=self.auth).json()
        self.assertEqual(queued['total'], 2)
        own = next(v for v in queued['items'] if v['id'] == a)
        self.assertEqual(set(own['actions']), {'video','caption'})
        with patch.object(app.time, 'time', return_value=500):
            result = action(a, 'cover')
        self.assertTrue(result['complete'])
        self.assertEqual(result['video']['status'], 'published')
        # Old response is a stable client snapshot until explicitly fetched again.
        self.assertEqual(queued['total'], 2)
        action(b, 'video'); action(b, 'caption')
        with patch.object(app.time, 'time', return_value=400): action(b, 'cover')
        with patch.object(app.time, 'time', return_value=900): action(a, 'video')
        published = self.client.get('/api/videos?status=published&category=workflow-test', headers=self.auth).json()
        self.assertEqual([v['id'] for v in published['items']], [a,b])
        self.assertEqual(published['items'][0]['published'], 500)
        self.assertEqual(self.client.get('/api/videos?status=queued&category=workflow-test', headers=self.auth).json()['total'], 0)
        self.assertEqual(self.client.post('/api/videos/'+a+'/actions/invalid', headers=self.auth).status_code, 400)

    def test_rejects_invalid_video_and_paths(self):
        response = self.client.post('/api/upload', headers=self.auth, files={'video': ('fake.mp4', b'not a video', 'video/mp4')})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.get('/media/invalid/video.mp4', headers=self.auth).status_code, 404)
        self.assertEqual(self.client.get('/media/' + 'a' * 32 + '/answers-private.txt', headers=self.auth).status_code, 404)

    def test_batch_300_limit_and_persistent_queue(self):
        sample = json.loads((app.ROOT / 'batch-example.json').read_text(encoding='utf-8'))['episodes'][0]
        response = self.client.post('/api/render', headers=self.auth, json={'episodes': [sample] * 300})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()['jobs']), 300)
        self.assertEqual(len(self.client.get('/api/jobs', headers=self.auth).json()['items']), 300)
        self.assertEqual(self.client.post('/api/render', headers=self.auth, json={'episodes': [sample] * 301}).status_code, 422)
        duplicate = json.loads(json.dumps(sample))
        duplicate['questions'][0]['options'] = ['یک'] * 4
        self.assertEqual(self.client.post('/api/render', headers=self.auth, json={'episodes': [duplicate]}).status_code, 422)

    def test_local_bank_snapshot(self):
        data = self.client.get('/api/questions?q=فردوسی', headers=self.auth).json()
        self.assertGreater(data['total'], 0)
        self.assertTrue(all(len(q['options']) == 4 for q in data['items']))

    def test_restart_recovers_interrupted_job(self):
        ident = 'b' * 32
        with app.db() as c:
            c.execute("INSERT INTO jobs(id,kind,title,payload,created,state) VALUES(?,?,?,?,?,?)",
                      (ident, 'render', 'restart test', '{}', 0, 'running'))
        app.stop_worker.clear()
        def finish(job):
            self.assertEqual(job['id'], ident)
            app.stop_worker.set()
            return None
        with patch.object(app, 'run_render', side_effect=finish):
            self.original_worker()
        with app.db() as c:
            self.assertEqual(c.execute('SELECT state FROM jobs WHERE id=?', (ident,)).fetchone()[0], 'done')


if __name__ == '__main__':
    unittest.main(verbosity=2)
