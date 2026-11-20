"""Quiz of Thrones content library. Run one Uvicorn process; SQLite persists jobs."""
import base64
import hashlib
import hmac
import json
import ipaddress
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field, field_validator
from PIL import Image

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('PANEL_DATA', ROOT / 'data')).resolve()
TEMPLATE = Path(os.environ.get('PANEL_TEMPLATE', ROOT / 'template')).resolve()
FFMPEG = os.environ.get('QUIZ_FFMPEG') or shutil.which('ffmpeg') or r'C:\Program Files\KMPlayer 64X\LAVFilters64\ffmpeg.exe'
MAX_FILE = 512 * 1024 * 1024
stop_worker = threading.Event()
action_lock = threading.Lock()


def auth_config():
    # Two fixed tool accounts; legacy single-user configuration no longer applies.
    return {'users': ['user1', 'user2'], 'salt': b'quiz-studio-two-users-v1'.hex(),
            'iterations': 210000, 'hash': 'b15d388185c05e4b8fa786b5b5b33a376377187f293a3a180f1aee513891959d'}


def password_matches(config, user, password):
    if not config or user not in config.get('users', [config.get('username')]):
        return False
    if 'plain' in config:
        return hmac.compare_digest(password.encode(), config['plain'].encode())
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(config['salt']), config['iterations']).hex()
    return hmac.compare_digest(digest, config['hash'])


@contextmanager
def db():
    conn = sqlite3.connect(DATA / 'panel.sqlite3', timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    DATA.mkdir(parents=True, exist_ok=True)
    (DATA / 'media').mkdir(exist_ok=True)
    (DATA / 'work').mkdir(exist_ok=True)
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT '',
            caption TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ready',
            intended_mode TEXT NOT NULL DEFAULT 'trial', published_url TEXT NOT NULL DEFAULT '',
            created REAL NOT NULL, published REAL, size INTEGER NOT NULL,
            duration REAL NOT NULL, sha256 TEXT NOT NULL UNIQUE, episode TEXT,
            shared_at REAL, share_count INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'queued',
            payload TEXT NOT NULL, title TEXT NOT NULL, progress INTEGER NOT NULL DEFAULT 0,
            created REAL NOT NULL, error TEXT NOT NULL DEFAULT '', video_id TEXT);
        CREATE INDEX IF NOT EXISTS videos_created ON videos(created DESC);
        CREATE INDEX IF NOT EXISTS jobs_state ON jobs(state,created);
        ''')


def media_dir(ident):
    if not re.fullmatch('[a-f0-9]{32}', ident):
        raise HTTPException(404, 'ویدیو پیدا نشد.')
    return DATA / 'media' / ident


def probe(path):
    result = subprocess.run([FFMPEG, '-hide_banner', '-protocol_whitelist', 'file,pipe', '-f', 'mov', '-i', str(path)], capture_output=True, timeout=30)
    text = result.stderr.decode('utf-8', errors='replace')
    duration = re.search(r'Duration: (\d+):(\d+):([\d.]+)', text)
    if not duration or 'Video:' not in text:
        raise ValueError('فایل، ویدیوی قابل‌خواندن نیست.')
    h, m, s = map(float, duration.groups())
    return h * 3600 + m * 60 + s


def ingest(video, cover, title, category, caption, episode=None, mode='trial'):
    with video.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    with db() as c:
        prior = c.execute('SELECT id FROM videos WHERE sha256=?', (digest,)).fetchone()
    if prior:
        return prior['id'], False
    duration = probe(video)
    ident = uuid.uuid4().hex
    folder = media_dir(ident)
    folder.mkdir()
    try:
        shutil.copyfile(video, folder / 'video.mp4')
        if cover:
            with Image.open(cover) as im:
                if im.width * im.height > 25000000:
                    raise ValueError('اندازهٔ تصویر کاور بیش از حد است.')
                im.convert('RGB').save(folder / 'cover.jpg', quality=92)
        else:
            subprocess.run([FFMPEG, '-v', 'error', '-y', '-protocol_whitelist', 'file,pipe', '-f', 'mov', '-i', str(video), '-frames:v', '1',
                            str(folder / 'cover.jpg')], check=True, timeout=30, capture_output=True)
        with db() as c:
            c.execute('''INSERT INTO videos(id,title,category,caption,intended_mode,created,size,duration,sha256,episode)
                         VALUES(?,?,?,?,?,?,?,?,?,?)''',
                      (ident, title, category, caption, mode, time.time(), video.stat().st_size,
                       duration, digest, json.dumps(episode, ensure_ascii=False) if episode else None))
    except BaseException:
        shutil.rmtree(folder)
        raise
    return ident, True


def public_video(row):
    d = dict(row)
    d.pop('sha256', None)
    d.pop('episode', None)
    d['video_url'] = '/media/' + d['id'] + '/video.mp4'
    d['cover_url'] = '/media/' + d['id'] + '/cover.jpg'
    return d


class Question(BaseModel):
    text: str = Field(min_length=2, max_length=240)
    options: list[str] = Field(min_length=4, max_length=4)
    answer_index: int = Field(ge=0, le=3)
    source_url: str = Field(default='', max_length=1000)

    @field_validator('options')
    @classmethod
    def valid_options(cls, values):
        values = [x.strip() for x in values]
        if len(set(values)) != 4 or any(not x or len(x) > 80 for x in values):
            raise ValueError('چهار گزینهٔ متفاوت و غیرخالی لازم است.')
        return values


class Episode(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    category: str = Field(default='فوتبال', max_length=80)
    caption: str = Field(default='', max_length=2200)
    intended_mode: str = 'trial'
    questions: list[Question] = Field(min_length=3, max_length=3)

    @field_validator('intended_mode')
    @classmethod
    def mode(cls, value):
        if value not in ('trial', 'public'):
            raise ValueError('Invalid mode')
        return value


class Batch(BaseModel):
    episodes: list[Episode] = Field(min_length=1, max_length=300)


class Edit(BaseModel):
    title: str = Field(min_length=2, max_length=160)
    category: str = Field(max_length=80)
    caption: str = Field(max_length=2200)
    intended_mode: str
    status: str
    published_url: str = Field(default='', max_length=1000)

    @field_validator('status')
    @classmethod
    def status_valid(cls, value):
        if value not in ('ready', 'trial', 'published', 'archived'):
            raise ValueError('Invalid status')
        return value

    @field_validator('intended_mode')
    @classmethod
    def mode_valid(cls, value):
        if value not in ('trial', 'public'):
            raise ValueError('Invalid mode')
        return value

    @field_validator('published_url')
    @classmethod
    def link_valid(cls, value):
        if value and (urlsplit(value).scheme != 'https' or urlsplit(value).hostname not in ('instagram.com', 'www.instagram.com')):
            raise ValueError('لینک باید متعلق به instagram.com باشد.')
        return value


def enqueue(kind, title, payload):
    ident = uuid.uuid4().hex
    with db() as c:
        c.execute('INSERT INTO jobs(id,kind,title,payload,created) VALUES(?,?,?,?,?)',
                  (ident, kind, title, json.dumps(payload, ensure_ascii=False), time.time()))
    return ident


def run_render(job):
    payload = json.loads(job['payload'])
    ident = job['id']
    work = DATA / 'work' / ident
    if work.exists():
        shutil.rmtree(work)  # Only this job's disposable render workspace.
    work.mkdir()
    shutil.copy2(TEMPLATE / 'render.py', work / 'render.py')
    shutil.copytree(TEMPLATE / 'assets', work / 'assets')
    theme = json.loads((TEMPLATE / 'theme.json').read_text(encoding='utf-8-sig'))
    theme['latin_font'] = 'assets/fonts/DejaVuSans.ttf'
    (work / 'theme.json').write_text(json.dumps(theme, ensure_ascii=False), encoding='utf-8')
    episode = {'id': ident, 'category': payload['category'], 'hook': payload['title'],
               'questions': payload['questions'], 'hashtags': ['کوییز', 'بازی_فکری']}
    ep = work / 'episode.json'
    ep.write_text(json.dumps(episode, ensure_ascii=False), encoding='utf-8')
    env = os.environ.copy()
    env['QUIZ_FFMPEG'] = FFMPEG
    env['PYTHONIOENCODING'] = 'utf-8'
    started = time.monotonic()
    with (work / 'worker.log').open('w', encoding='utf-8') as logfile:
        process = subprocess.Popen([sys.executable, str(work / 'render.py'), str(ep)], cwd=work,
                                   env=env, stdout=logfile, stderr=subprocess.STDOUT)
        while process.poll() is None:
            if time.monotonic() - started > 3600:
                process.kill()
                process.wait()
                raise ValueError('رندر بیش از یک ساعت طول کشید؛ منابع سرور را بررسی کنید.')
            text = (work / 'worker.log').read_text(encoding='utf-8', errors='replace')
            frames = re.findall(r'Rendered ([\d.]+)/39', text)
            if frames:
                with db() as c:
                    c.execute('UPDATE jobs SET progress=? WHERE id=?', (min(98, round(float(frames[-1]) / 39 * 100)), ident))
            time.sleep(1)
        if process.returncode:
            log = (work / 'worker.log').read_text(encoding='utf-8', errors='replace')
            safe = log[-500:] if 'Text is too long' in log else 'رندر انجام نشد؛ متن سؤال‌ها، فونت و FFmpeg را بررسی کنید.'
            raise ValueError(safe)
    rendered = work / 'renders' / ident
    caption = payload['caption'] or (rendered / 'caption.txt').read_text(encoding='utf-8-sig')
    video_id, _ = ingest(rendered / 'video.mp4', rendered / 'cover.png', payload['title'],
                         payload['category'], caption, episode, payload['intended_mode'])
    shutil.rmtree(work)
    return video_id


def run_sync():
    if not os.environ.get('QUIZ_API_KEY'):
        raise ValueError('کلید بانک سؤال روی سرور تنظیم نشده است.')
    # Client enforces HTTPS and same-origin redirects. Secrets are never sent to browsers.
    import importlib.util
    spec = importlib.util.spec_from_file_location('panel_quiz_api', TEMPLATE / 'quiz_api.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    bankroot = DATA / 'bank'
    bankroot.mkdir(exist_ok=True)
    module.ROOT = bankroot
    module.sync()


def worker():
    with db() as c:
        c.execute("UPDATE jobs SET state='queued', progress=0 WHERE state='running'")
    while not stop_worker.is_set():
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            job = c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created LIMIT 1").fetchone()
            if job:
                c.execute("UPDATE jobs SET state='running' WHERE id=?", (job['id'],))
        if not job:
            stop_worker.wait(1)
            continue
        try:
            video_id = run_render(job) if job['kind'] == 'render' else run_sync()
            with db() as c:
                c.execute("UPDATE jobs SET state='done',progress=100,video_id=? WHERE id=?", (video_id, job['id']))
        except Exception as exc:
            error = str(exc) if isinstance(exc, ValueError) else 'عملیات انجام نشد؛ منابع سرور و فایل‌ها را بررسی کنید.'
            with db() as c:
                c.execute("UPDATE jobs SET state='failed',error=? WHERE id=?", (error[:600], job['id']))


@asynccontextmanager
async def lifespan(app):
    if not auth_config() and os.environ.get('PANEL_DEV') != '1':
        raise RuntimeError('PANEL_PASSWORD is required. Set PANEL_DEV=1 only for loopback development.')
    init_db()
    stop_worker.clear()
    if os.environ.get('PANEL_PREVIEW_READONLY') != '1':
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
    yield
    stop_worker.set()


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def guard(request: Request, call_next):
    config = auth_config()
    lan_preview = os.environ.get('PANEL_DEV') == '1' and os.environ.get('PANEL_PREVIEW_READONLY') == '1'
    if request.url.path != '/health':
        if config:
            raw = request.headers.get('authorization', '')
            try:
                scheme, encoded = raw.split(' ', 1)
                if scheme.lower() != 'basic':
                    raise ValueError()
                user, supplied = base64.b64decode(encoded, validate=True).decode().split(':', 1)
                good = password_matches(config, user, supplied)
            except (ValueError, UnicodeError):
                good = False
            if not good:
                return Response(status_code=401, headers={'WWW-Authenticate': 'Basic realm="Quiz Studio", charset="UTF-8"'})
            request.state.username = user
        elif lan_preview:
            try:
                if not ipaddress.ip_address(request.client.host).is_private:
                    return Response(status_code=403)
            except ValueError:
                return Response(status_code=403)
        elif os.environ.get('PANEL_DEV') != '1' or request.client.host not in ('127.0.0.1', '::1', 'testclient'):
            return Response(status_code=403)
        if lan_preview and request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return JSONResponse({'detail': 'این آدرس فقط برای پیش‌نمایش شبکهٔ داخلی است؛ تغییرات غیرفعال‌اند.'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            origin = request.headers.get('origin', '')
            expected = os.environ.get('PANEL_ORIGIN') or str(request.base_url).rstrip('/')
            if origin != expected:
                return JSONResponse({'detail': 'درخواست از مبدأ مجاز نیست.'}, status_code=403)
    result = await call_next(request)
    result.headers['X-Content-Type-Options'] = 'nosniff'
    result.headers['Referrer-Policy'] = 'same-origin'
    result.headers['Permissions-Policy'] = 'web-share=(self), clipboard-write=(self)'
    result.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    result.headers['Cache-Control'] = 'private, no-store'
    return result


@app.get('/health')
def health():
    return {'ok': True}


@app.get('/api/info')
def info():
    return {'render_available': (TEMPLATE / 'render.py').exists(), 'bank_sync_available': bool(os.environ.get('QUIZ_API_KEY')),
            'max_upload_mb': MAX_FILE // 1048576, 'max_batch': 300}


@app.get('/api/me')
def me(request: Request):
    return {'username': request.state.username}


def read_actions():
    path = DATA / 'download-actions.json'
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


@app.post('/api/videos/{ident}/actions/{action}')
def record_action(ident: str, action: str, request: Request):
    if action not in ('video', 'cover', 'caption'):
        raise HTTPException(400, 'اقدام نامعتبر است.')
    get_video(ident)
    with action_lock:
        actions = read_actions()
        flags = actions.setdefault(request.state.username, {}).setdefault(ident, {})
        flags.setdefault(action, time.time())
        # Commit the tiny file atomically, then update the existing video status.
        path = DATA / 'download-actions.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(actions, ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, path)
        complete = all(name in flags for name in ('video', 'cover', 'caption'))
        if complete:
            with db() as c:
                c.execute("UPDATE videos SET status='published', published=COALESCE(published,?) WHERE id=?", (time.time(), ident))
    return {'actions': list(flags), 'complete': complete, 'video': get_video(ident)}


@app.get('/api/videos')
def videos(request: Request, q: str = '', status: str = '', category: str = '', page: int = 1, limit: int = 30):
    page, limit = max(1, page), min(100, max(1, limit))
    where, args = ['1=1'], []
    if q:
        where.append('(title LIKE ? OR caption LIKE ?)')
        args.extend(['%' + q[:200] + '%'] * 2)
    if status == 'queued':
        where.append("status='ready'")
    elif status == 'published':
        where.append("status IN ('published','trial')")
    elif status:
        where.append('status=?'); args.append(status)
    else:
        where.append("status!='archived'")
    if category:
        where.append('category=?'); args.append(category)
    sql = ' AND '.join(where)
    with db() as c:
        total = c.execute('SELECT COUNT(*) FROM videos WHERE ' + sql, args).fetchone()[0]
        order = 'COALESCE(published,created) DESC, created DESC' if status == 'published' else 'created DESC'
        rows = c.execute('SELECT * FROM videos WHERE ' + sql + ' ORDER BY ' + order + ' LIMIT ? OFFSET ?', args + [limit, (page - 1) * limit]).fetchall()
        cats = [x[0] for x in c.execute('SELECT DISTINCT category FROM videos ORDER BY category')]
        counts = {x[0]: x[1] for x in c.execute('SELECT status,COUNT(*) FROM videos GROUP BY status')}
    with action_lock:
        actions = read_actions().get(request.state.username, {})
    items = [dict(public_video(x), actions=list(actions.get(x['id'], {}))) for x in rows]
    return {'items': items, 'total': total, 'categories': cats, 'counts': counts, 'page': page}


@app.get('/api/videos/{ident}')
def get_video(ident: str):
    with db() as c:
        row = c.execute('SELECT * FROM videos WHERE id=?', (ident,)).fetchone()
    if not row:
        raise HTTPException(404, 'ویدیو پیدا نشد.')
    return public_video(row)


@app.patch('/api/videos/{ident}')
def edit_video(ident: str, edit: Edit):
    get_video(ident)
    published = time.time() if edit.status in ('published', 'trial') else None
    with db() as c:
        c.execute('''UPDATE videos SET title=?,category=?,caption=?,intended_mode=?,status=?,published_url=?,
                     published=CASE WHEN status=? THEN published ELSE ? END WHERE id=?''',
                  (edit.title, edit.category, edit.caption, edit.intended_mode, edit.status,
                   edit.published_url, edit.status, published, ident))
    return get_video(ident)


@app.post('/api/videos/{ident}/shared')
def shared(ident: str):
    get_video(ident)
    with db() as c:
        c.execute('UPDATE videos SET shared_at=?,share_count=share_count+1 WHERE id=?', (time.time(), ident))
    return {'ok': True}  # Never marks an Instagram publication automatically.


async def save_upload(upload, path, maximum):
    size = 0
    try:
        with path.open('wb') as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > maximum:
                    raise HTTPException(413, 'فایل بزرگ‌تر از حد مجاز است.')
                out.write(chunk)
        if not size:
            raise HTTPException(400, 'فایل خالی است.')
    finally:
        await upload.close()


@app.post('/api/upload')
async def upload(video: UploadFile = File(...), cover: UploadFile | None = File(None),
                 title: str = Form(''), category: str = Form(''), caption: str = Form('')):
    if len(caption) > 2200 or len(title) > 160 or len(category) > 80:
        raise HTTPException(400, 'متن بیش از حد طولانی است.')
    work = DATA / 'work' / uuid.uuid4().hex
    work.mkdir()
    try:
        vp = work / 'upload.mp4'
        await save_upload(video, vp, MAX_FILE)
        cp = None
        if cover:
            cp = work / 'cover'
            await save_upload(cover, cp, 15 * 1048576)
        ident, created = await __import__('starlette.concurrency', fromlist=['run_in_threadpool']).run_in_threadpool(
            ingest, vp, cp, title.strip() or Path(video.filename or 'ویدیوی جدید').stem[:160], category, caption)
        return {'video': get_video(ident), 'created': created}
    except (ValueError, subprocess.SubprocessError, OSError):
        raise HTTPException(400, 'ویدیو یا کاور قابل خواندن نیست.') from None
    finally:
        shutil.rmtree(work)


@app.get('/media/{ident}/{filename}')
def media(ident: str, filename: str, download: int = 0):
    if filename not in ('video.mp4', 'cover.jpg'):
        raise HTTPException(404)
    path = media_dir(ident) / filename
    if not path.is_file():
        raise HTTPException(404)
    kind = 'video/mp4' if filename.endswith('.mp4') else 'image/jpeg'
    # FileResponse supports byte ranges for mobile playback and resuming downloads.
    return FileResponse(path, media_type=kind, filename=(ident + '-' + filename) if download else None)


@app.post('/api/render')
def render(batch: Batch):
    if not (TEMPLATE / 'render.py').exists():
        raise HTTPException(409, 'قالب رندر روی سرور نصب نشده است.')
    created = time.time()
    rows = [(uuid.uuid4().hex, 'render', x.title, json.dumps(x.model_dump(), ensure_ascii=False), created + i * .000001)
            for i, x in enumerate(batch.episodes)]
    with db() as c:
        c.executemany('INSERT INTO jobs(id,kind,title,payload,created) VALUES(?,?,?,?,?)', rows)
    return {'jobs': [x[0] for x in rows]}


@app.get('/api/jobs')
def jobs():
    with db() as c:
        return {'items': [dict(x) for x in c.execute('SELECT id,kind,title,state,progress,created,error,video_id FROM jobs ORDER BY created DESC LIMIT 350')]}


@app.post('/api/jobs/{ident}/retry')
def retry_job(ident: str):
    with db() as c:
        count = c.execute("UPDATE jobs SET state='queued',error='',progress=0 WHERE id=? AND state='failed'", (ident,)).rowcount
    if not count:
        raise HTTPException(409, 'فقط عملیات ناموفق قابل تلاش مجدد است.')
    return {'ok': True}


@app.get('/api/questions')
def questions(q: str = '', category: str = '', page: int = 1):
    bank = DATA / 'bank' / 'question-bank' / 'questions.json'
    if not bank.exists():
        bank = TEMPLATE / 'question-bank' / 'questions.json'
    if not bank.exists():
        return {'items': [], 'total': 0}
    items = json.loads(bank.read_text(encoding='utf-8-sig'))['items']
    def norm(s):
        return s.replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', ' ')
    query = norm(q.strip())
    items = [x for x in items if (not query or query in norm(x['text'])) and
             (not category or category in x.get('categories', []) or category == x.get('category'))]
    start = (max(1, page) - 1) * 30
    return {'items': [{'id': x['id'], 'text': x['text'], 'options': x['options'], 'answer_index': x['correctIndex']} for x in items[start:start + 30]], 'total': len(items)}


@app.post('/api/bank/sync')
def sync_bank():
    if not os.environ.get('QUIZ_API_KEY'):
        raise HTTPException(409, 'کلید API هنوز روی سرور تنظیم نشده است.')
    with db() as c:
        active = c.execute("SELECT id FROM jobs WHERE kind='sync' AND state IN ('queued','running')").fetchone()
    return {'job': active['id'] if active else enqueue('sync', 'همگام‌سازی بانک سؤال', {})}


@app.get('/')
def index():
    return FileResponse(ROOT / 'static' / 'index.html', media_type='text/html')


@app.get('/{filename}')
def assets(filename: str):
    allowed = {'app.js': 'text/javascript', 'library.js': 'text/javascript', 'style.css': 'text/css', 'manifest.webmanifest': 'application/manifest+json',
               'sw.js': 'text/javascript', 'icon.svg': 'image/svg+xml', 'icon-192.png': 'image/png',
               'icon-512.png': 'image/png', 'Yekan.ttf': 'font/ttf'}
    if filename not in allowed or not (ROOT / 'static' / filename).is_file():
        raise HTTPException(404)
    return FileResponse(ROOT / 'static' / filename, media_type=allowed[filename])
