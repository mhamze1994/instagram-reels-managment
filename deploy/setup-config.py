import getpass
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

origin = input('Panel origin (e.g. http://SERVER-IP): ').strip().rstrip('/')
parsed = urlsplit(origin)
if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.path or parsed.query or parsed.username or parsed.password:
    raise SystemExit('Use the server origin, with no path or credentials.')
values = {'PANEL_ORIGIN': origin,
          'PANEL_DATA': '/var/lib/quiz-studio', 'PANEL_TEMPLATE': '/opt/quiz-studio/template',
          'QUIZ_FFMPEG': '/usr/bin/ffmpeg'}
path = Path('/opt/quiz-studio/.env')
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w') as f:
    for key, value in values.items():
        f.write(key + '=' + json.dumps(value, ensure_ascii=True) + '\n')
print('Configuration saved. Fixed accounts: user1 and user2.')
