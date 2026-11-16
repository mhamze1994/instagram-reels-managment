#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo.'; exit 1; fi
# This command is only for the dedicated, default Nginx server described in README.
nginx -t
CURRENT="$(nginx -T 2>&1)"
if printf '%s\n' "$CURRENT" | grep -Eq '^[[:space:]]*ssl_certificate|^[[:space:]]*listen.*443'; then
  echo 'Existing TLS configuration found. Refusing to replace it; configure the proxy manually.'; exit 1
fi
if printf '%s\n' "$CURRENT" | grep -E '^[[:space:]]*server_name[[:space:]]' | grep -Ev 'server_name[[:space:]]+(_|localhost|"")[[:space:]]*;' >/dev/null; then
  echo 'Existing named website found. Refusing to replace it; configure the proxy manually.'; exit 1
fi
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="/etc/nginx/nginx.conf.quiz-backup-$STAMP"
cp -p /etc/nginx/nginx.conf "$BACKUP"
CANDIDATE=/etc/nginx/nginx.conf.quiz-candidate
cat > "$CANDIDATE" <<'NGINX'
worker_processes auto;
pid /run/nginx.pid;
events { worker_connections 1024; }
http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    server {
        listen 80 default_server;
        server_name _;
        client_max_body_size 530m;
        client_body_timeout 300s;
        location / {
            proxy_pass http://127.0.0.1:8091;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_request_buffering off;
            proxy_buffering off;
            proxy_read_timeout 300s;
            proxy_send_timeout 300s;
        }
    }
}
NGINX
nginx -t -c "$CANDIDATE"
cp "$CANDIDATE" /etc/nginx/nginx.conf
if ! nginx -t || ! systemctl reload nginx; then
  cp -p "$BACKUP" /etc/nginx/nginx.conf
  nginx -t && systemctl reload nginx
  echo 'Configuration rolled back.'; exit 1
fi
echo "Panel available on port 80. Nginx backup: $BACKUP"
