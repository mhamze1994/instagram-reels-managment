#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo bash deploy/install-ubuntu.sh'; exit 1; fi
source /etc/os-release
if [ "$ID" != ubuntu ] || [ "$VERSION_ID" != 24.04 ]; then
  echo 'This installer targets Ubuntu 24.04 LTS. Review manually for other systems.'; exit 1
fi
SOURCE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ "$SOURCE_DIR" = /opt/quiz-studio ]; then echo 'Extract the release somewhere else, e.g. /tmp/quiz-release.'; exit 1; fi
apt-get update
apt-get install -y python3 python3-venv ffmpeg fonts-dejavu-core
id quizstudio >/dev/null 2>&1 || useradd --system --home /var/lib/quiz-studio --shell /usr/sbin/nologin quizstudio
install -d -o quizstudio -g quizstudio -m 700 /var/lib/quiz-studio
install -d -m 755 /opt/quiz-studio
for file in app.py manage.py requirements.txt; do install -m 644 "$SOURCE_DIR/$file" /opt/quiz-studio/; done
cp -R "$SOURCE_DIR/static" /opt/quiz-studio/
cp -R "$SOURCE_DIR/template" /opt/quiz-studio/
cp /usr/share/fonts/truetype/dejavu/DejaVuSans.ttf /opt/quiz-studio/template/assets/fonts/DejaVuSans.ttf
python3 -m venv /opt/quiz-studio/.venv
/opt/quiz-studio/.venv/bin/python -m pip install -r /opt/quiz-studio/requirements.txt
if [ ! -f /opt/quiz-studio/.env ]; then
  python3 "$SOURCE_DIR/deploy/setup-config.py"
fi
chmod 600 /opt/quiz-studio/.env
install -m 644 "$SOURCE_DIR/deploy/quiz-studio.service" /etc/systemd/system/quiz-studio.service
systemctl daemon-reload
systemctl enable --now quiz-studio
systemctl restart quiz-studio
echo 'Service installed at 127.0.0.1:8091. Next: configure your HTTPS Nginx subdomain.'
echo 'Nginx was NOT modified. Use deploy/nginx.conf.example inside its HTTPS server block.'
echo 'Status: systemctl status quiz-studio'
if [ "${1:-}" = --configure-nginx ]; then
  bash "$SOURCE_DIR/deploy/configure-nginx.sh"
fi
