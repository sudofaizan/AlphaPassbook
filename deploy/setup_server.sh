#!/bin/bash
set -euo pipefail

APP_DIR="/home/ec2-user/alphapassbook"

sudo dnf install -y python3-pip nginx openssl

mkdir -p "$APP_DIR"
tar xzf /home/ec2-user/alphapassbook.tar.gz -C "$APP_DIR"

cd "$APP_DIR"
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt

sudo tee /etc/systemd/system/alphapassbook.service > /dev/null << 'UNIT'
[Unit]
Description=AlphaPassbook Booking Dashboard
After=network.target

[Service]
User=ec2-user
WorkingDirectory=/home/ec2-user/alphapassbook
ExecStart=/home/ec2-user/alphapassbook/.venv/bin/uvicorn booking_server:app --host 127.0.0.1 --port 8080
Restart=always
RestartSec=3
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
UNIT

sudo mkdir -p /etc/nginx/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/alphapassbook.key \
  -out /etc/nginx/ssl/alphapassbook.crt \
  -subj "/CN=alphapassbook" 2>/dev/null

sudo tee /etc/nginx/conf.d/alphapassbook.conf > /dev/null << 'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name _;

    ssl_certificate     /etc/nginx/ssl/alphapassbook.crt;
    ssl_certificate_key /etc/nginx/ssl/alphapassbook.key;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 86400;
    }
}
NGINX

sudo rm -f /etc/nginx/conf.d/default.conf 2>/dev/null || true
sudo nginx -t
sudo systemctl daemon-reload
sudo systemctl enable alphapassbook nginx
sudo systemctl restart alphapassbook nginx

echo "DEPLOY_OK"
curl -s -o /dev/null -w "HTTP:%{http_code}" http://127.0.0.1/
