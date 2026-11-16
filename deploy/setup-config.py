import getpass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

origin = input('Panel origin (e.g. http://SERVER-IP): ').strip().rstrip('/')
parsed = urlsplit(origin)
if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.path or parsed.query or parsed.username or parsed.password:
    raise SystemExit('Use the server origin, with no path or credentials.')
password = getpass.getpass('Choose panel password (12+ characters): ')
if len(password) < 12 or '\n' in password or '\r' in password:
    raise SystemExit('Password needs 12+ characters and no newlines.')
if getpass.getpass('Repeat password: ') != password:
    raise SystemExit('Passwords do not match.')
salt = os.urandom(24)
import hashlib
verifier = {'username': 'quiz', 'salt': salt.hex(), 'iterations': 210000,
            'hash': hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 210000).hex()}
auth = Path('/opt/quiz-studio/auth-defaults.json')
fd = os.open(auth, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
with os.fdopen(fd, 'w') as f:
    json.dump(verifier, f)
import shutil
shutil.chown(auth, user='root', group='quizstudio')
values = {'PANEL_USER': 'quiz', 'PANEL_ORIGIN': origin,
          'PANEL_DATA': '/var/lib/quiz-studio', 'PANEL_TEMPLATE': '/opt/quiz-studio/template',
          'QUIZ_FFMPEG': '/usr/bin/ffmpeg'}
path = Path('/opt/quiz-studio/.env')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    for key, value in values.items():
        f.write(key + '=' + json.dumps(value, ensure_ascii=True) + '\n')
print('Configuration saved. Username: quiz. Password was not printed or stored in plaintext.')
