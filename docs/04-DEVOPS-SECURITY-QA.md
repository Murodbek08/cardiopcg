# CardioPCG AI — DevOps, xavfsizlik va QA spetsifikatsiyasi

Hujjat `00-ARCHITECTURE-DECISIONS.md` ga tayanadi. Maqsad: https://cardiopcgai.189.uz ni **umumiy (shared) production server**ga (164.68.111.41, Ubuntu) joylash va ishlatish. Serverda boshqa jonli loyihalar (tiiame, adshare, uzex-agent, migrantlar24 va boshqalar) ishlayapti — ularga hech qanday ta'sir bo'lmasligi shart.

Belgilar: `<...>` — to'ldiriladigan qiymat. Hujjatdagi barcha parol/kalitlar faqat placeholder; haqiqiy sirlar gitga YOZILMAYDI.

---

## 1. Step 0 — majburiy faqat-o'qish (read-only) razvedka

Hech narsa o'zgartirilmasdan oldin quyidagilar bajariladi va natija `deploy/RECON-<sana>.txt` ga (gitga EMAS, serverda `~/cardiopcg-recon/`) saqlanadi. Bu bosqichda `restart`, `reload`, `rm`, `prune`, `apt upgrade` kabi buyruqlar TAQIQLANGAN.

```bash
ssh deploy@164.68.111.41   # kalit bilan; root bilan ishlamaslik tavsiya etiladi
mkdir -p ~/cardiopcg-recon && cd ~/cardiopcg-recon

# 1) Tizim resurslari
uname -a; lsb_release -a
nproc; free -h; df -hT; df -ih
uptime; vmstat 1 5
docker system df

# 2) Mavjud konteynerlar va compose loyihalari
docker ps -a --format 'table {{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'
docker compose ls -a
docker network ls
docker volume ls
docker stats --no-stream

# 3) Band portlar (bo'sh 127.0.0.1 diapazonini tanlash uchun)
ss -ltnp
ss -ltn | awk 'NR>1{print $4}' | sed 's/.*://' | sort -n | uniq > used-ports.txt
# Tanlangan diapazon band emasligini tekshirish (misol: 18400-18499)
for p in $(seq 18400 18499); do grep -qx "$p" used-ports.txt && echo "BAND: $p"; done

# 4) nginx
sudo nginx -v
sudo nginx -T > nginx-full-dump.txt 2>&1        # faqat o'qish
ls -la /etc/nginx/sites-enabled/ /etc/nginx/conf.d/
grep -R "server_name" /etc/nginx/sites-enabled/ /etc/nginx/conf.d/
grep -R "cardiopcgai" /etc/nginx/ || echo "cardiopcgai hali yo'q"

# 5) certbot / sertifikatlar
sudo certbot certificates
systemctl list-timers | grep -i certbot

# 6) Xavfsizlik holati
sudo ufw status verbose
sudo systemctl status fail2ban --no-pager
sudo ss -ltnp | grep -E ':(22|80|443)\s'

# 7) Boshqa loyihalar joylashuvi va cron
ls -la /opt /srv /home/*/ 2>/dev/null | head -100
crontab -l; sudo ls /etc/cron.d/
dig +short cardiopcgai.189.uz     # Cloudflare IP qaytishi kutiladi
```

**Razvedka natijasidan qarorlar (qo'lda yozib qo'yiladi):**

| Savol | Mezon |
|---|---|
| Bo'sh port diapazoni | Ketma-ket 10 ta port band emas (tavsiya: 18400-18409) |
| RAM | Bo'sh (available) kamida 3 GB; bo'lmasa limitlar kamaytiriladi yoki Celery concurrency 1 |
| Disk | Bo'sh kamida 20 GB (audio + backup uchun); `df` 80% dan yuqori bo'lsa — to'xtab, egasi bilan kelishish |
| Compose project nomi | `cardiopcg` — `docker compose ls -a` da yo'qligi tasdiqlanadi |
| Port 80/443 | Faqat mavjud host nginx egallaydi; biz ularga tegmaymiz |
| certbot | Bor bo'lsa — mavjud avto-yangilanish saqlanadi; yo'q bo'lsa Cloudflare Origin Certificate (6.4-bo'lim) |

Agar razvedka kutilmagan holatni ko'rsatsa (RAM/disk yetishmasa, port to'qnashuvi, nginx `-T` xato bersa) — deploy to'xtatiladi va foydalanuvchiga xabar beriladi.

---

## 2. Izolyatsiya qoidalari (buzilmas)

1. **Unikal compose project nomi:** `name: cardiopcg` (compose faylida) va `COMPOSE_PROJECT_NAME=cardiopcg`. Konteyner nomlari `cardiopcg-<servis>`.
2. **O'z tarmog'i va volumelari:** `cardiopcg_net` (internal backend tarmog'i), volume nomlari `cardiopcg_pgdata`, `cardiopcg_redis`, `cardiopcg_minio`, `cardiopcg_uploads`. Boshqa loyiha tarmog'iga `external` ulanish YO'Q.
3. **Resurs limitlari:** har konteynerga `mem_limit`, `cpus`, `pids_limit`; `restart: unless-stopped`; log rotatsiyasi (`json-file`, `max-size: 10m`, `max-file: 3`).
4. **Port ochilishi:** faqat `127.0.0.1:<port>:<ichki>` shaklida. `0.0.0.0` yoki portsiz `ports: "5432:5432"` KATTA XATO. Postgres/Redis/MinIO hostga umuman publish qilinmaydi (faqat ichki tarmoq); MinIO console kerak bo'lsa — vaqtincha SSH tunnel.
5. **Nginx:** faqat bitta yangi fayl `/etc/nginx/sites-available/cardiopcgai.189.uz` yaratiladi; boshqa saytlar konfiguratsiyasi va `nginx.conf` ga TEGILMAYDI. Har o'zgarishdan oldin zaxira, keyin `nginx -t`, faqat muvaffaqiyatli bo'lsa `reload` (restart EMAS).
6. **Global buyruqlar taqiqi:** `docker system prune`, `docker volume prune`, `docker network prune`, `docker rm $(docker ps -aq)`, `docker compose down` (loyiha nomisiz), `systemctl restart nginx/docker`, `ufw reset`, `apt autoremove`, `kill -9` nomlarsiz — ishlatilmaydi. Faqat `docker compose -p cardiopcg ...` va `docker image prune --filter label=project=cardiopcg`.
7. **Konteyner/image yorlig'i:** barcha servislarda `labels: ["project=cardiopcg"]` — tozalash faqat shu yorliq bo'yicha.
8. **Zaxira nusxa qoidasi:** serverdagi har qanday umumiy faylni (nginx, ufw, cron) o'zgartirishdan oldin:
   ```bash
   sudo cp -a /etc/nginx /root/backup-nginx-$(date +%F-%H%M)
   ```
9. **Yangi umumiy xizmat o'rnatilmaydi** (Postgres/Redis host'ga apt orqali emas) — hammasi konteynerda.
10. **Resurs byudjeti (boshlang'ich):** api 1 CPU/1 GB, worker 1.5 CPU/1.5 GB, postgres 1 CPU/1 GB, redis 0.5 CPU/256 MB, minio 0.5 CPU/512 MB, frontend 0.25 CPU/128 MB. Jami ≈ 4.75 CPU/4.4 GB limit; haqiqiy iste'mol `docker stats` bilan kuzatiladi, razvedka natijasiga qarab moslashtiriladi.
11. **Server vaqt oynasi:** og'ir qurilish (`--build`) boshqa loyihalar eng kam yuklangan vaqtda yoki `nice -n 19` / `docker build --cpu-quota` bilan.

---

## 3. docker-compose.prod.yml skeleti

Fayl: `deploy/docker-compose.prod.yml`. Portlar (`18400-18409`) — razvedkadan keyin tasdiqlanadi.

```yaml
name: cardiopcg

x-common: &common
  restart: unless-stopped
  labels: ["project=cardiopcg"]
  logging:
    driver: json-file
    options: { max-size: "10m", max-file: "3" }
  security_opt: ["no-new-privileges:true"]
  networks: [cardiopcg_net]

services:
  postgres:
    <<: *common
    image: postgres:17-alpine
    container_name: cardiopcg-postgres
    environment:
      POSTGRES_DB: ${POSTGRES_DB}
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [cardiopcg_pgdata:/var/lib/postgresql/data]
    mem_limit: 1g
    cpus: 1.0
    pids_limit: 200
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 6
    # ports: YO'Q (faqat ichki tarmoq)

  redis:
    <<: *common
    image: redis:7-alpine
    container_name: cardiopcg-redis
    command: ["redis-server", "--requirepass", "${REDIS_PASSWORD}", "--appendonly", "yes", "--maxmemory", "200mb", "--maxmemory-policy", "noeviction"]
    volumes: [cardiopcg_redis:/data]
    mem_limit: 256m
    cpus: 0.5
    healthcheck:
      test: ["CMD", "redis-cli", "-a", "${REDIS_PASSWORD}", "ping"]
      interval: 10s
      timeout: 3s
      retries: 6

  minio:
    <<: *common
    image: minio/minio:<PINNED_TAG>
    container_name: cardiopcg-minio
    command: server /data --console-address ":9001"
    environment:
      MINIO_ROOT_USER: ${MINIO_ROOT_USER}
      MINIO_ROOT_PASSWORD: ${MINIO_ROOT_PASSWORD}
    volumes: [cardiopcg_minio:/data]
    mem_limit: 512m
    cpus: 0.5
    healthcheck:
      test: ["CMD", "mc", "ready", "local"]
      interval: 15s
      timeout: 5s
      retries: 5

  api:
    <<: *common
    build: { context: ../backend, dockerfile: Dockerfile, target: runtime }
    image: cardiopcg/api:${APP_VERSION:-latest}
    container_name: cardiopcg-api
    env_file: [.env]
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    ports: ["127.0.0.1:18400:8000"]
    read_only: true
    tmpfs: ["/tmp:size=256m"]
    mem_limit: 1g
    cpus: 1.0
    pids_limit: 300
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/healthz')"]
      interval: 15s
      timeout: 5s
      retries: 5
      start_period: 30s

  worker:
    <<: *common
    image: cardiopcg/api:${APP_VERSION:-latest}   # bir xil image, boshqa command
    container_name: cardiopcg-worker
    command: ["celery", "-A", "app.workers.celery_app", "worker", "-l", "info", "--concurrency=2", "--max-tasks-per-child=50"]
    env_file: [.env]
    depends_on:
      postgres: { condition: service_healthy }
      redis: { condition: service_healthy }
    read_only: true
    tmpfs: ["/tmp:size=512m"]
    mem_limit: 1536m
    cpus: 1.5
    pids_limit: 300

  frontend:
    <<: *common
    build: { context: ../frontend, dockerfile: Dockerfile }
    image: cardiopcg/frontend:${APP_VERSION:-latest}
    container_name: cardiopcg-frontend
    ports: ["127.0.0.1:18401:8080"]
    read_only: true
    tmpfs: ["/tmp", "/var/cache/nginx", "/var/run"]
    mem_limit: 128m
    cpus: 0.25

networks:
  cardiopcg_net:
    name: cardiopcg_net
    driver: bridge

volumes:
  cardiopcg_pgdata:
  cardiopcg_redis:
  cardiopcg_minio:
```

Eslatmalar:
- Host nginx `/api/`, `/ws/` ni `127.0.0.1:18400` ga, qolganini `127.0.0.1:18401` ga yo'naltiradi.
- Celery beat (davriy vazifalar: retention tozalash) kerak bo'lsa — alohida `beat` servisi, bir nusxa.
- `minio` bucket'lari (`pcg-audio`, `pcg-reports`) birinchi ishga tushishda `mc mb` bilan yaratiladi; bucket **private**, anonim kirish o'chirilgan; fayllar faqat qisqa muddatli presigned URL bilan beriladi.

---

## 4. Dockerfile'lar (multi-stage, non-root)

### 4.1 backend/Dockerfile
```dockerfile
# syntax=docker/dockerfile:1.7
FROM python:3.13-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY --from=ghcr.io/astral-sh/uv:<PINNED_TAG> /uv /bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends build-essential libsndfile1-dev \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev

FROM python:3.13-slim AS runtime
RUN apt-get update && apt-get install -y --no-install-recommends libsndfile1 ffmpeg curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r app --gid 10001 && useradd -r -g app --uid 10001 -d /app -s /usr/sbin/nologin app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLCONFIGDIR=/tmp/mpl NUMBA_CACHE_DIR=/tmp/numba
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "app.main:app", "-k", "uvicorn.workers.UvicornWorker", "-w", "2", "-b", "0.0.0.0:8000", "--timeout", "120", "--graceful-timeout", "30"]
```

### 4.2 frontend/Dockerfile
```dockerfile
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
ARG VITE_API_BASE=/api
ENV VITE_API_BASE=$VITE_API_BASE
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.27-alpine AS runtime
COPY deploy/frontend-nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
USER 101
```
`frontend-nginx.conf`: `listen 8080;`, `try_files $uri /index.html;` (SPA), `/assets/` uchun `Cache-Control: public, max-age=31536000, immutable`, `index.html` uchun `no-cache`.

Qo'shimcha: `.dockerignore` (`.git`, `.env*`, `node_modules`, `__pycache__`, `tests`, `docs`), image'lar `trivy image` bilan CI'da skanerlanadi (HIGH/CRITICAL — build fail).

---

## 5. .env.example (faqat placeholder)

Fayl: repo ildizida `.env.example`. Haqiqiy `.env` serverda `deploy/.env`, ruxsat `chmod 600`, egasi `deploy`. `.env` `.gitignore` da.

```dotenv
# ---------- Umumiy ----------
APP_ENV=production
APP_VERSION=<git-sha-yoki-teg>
PUBLIC_URL=https://cardiopcgai.189.uz
ALLOWED_ORIGINS=https://cardiopcgai.189.uz
LOG_LEVEL=info
TZ=Asia/Tashkent

# ---------- PostgreSQL ----------
POSTGRES_DB=cardiopcg
POSTGRES_USER=cardiopcg_app
POSTGRES_PASSWORD=<GENERATE_32_CHAR_RANDOM>
DATABASE_URL=postgresql+asyncpg://cardiopcg_app:<POSTGRES_PASSWORD>@postgres:5432/cardiopcg

# ---------- Redis ----------
REDIS_PASSWORD=<GENERATE_32_CHAR_RANDOM>
REDIS_URL=redis://:<REDIS_PASSWORD>@redis:6379/0
CELERY_BROKER_URL=redis://:<REDIS_PASSWORD>@redis:6379/1

# ---------- MinIO / S3 ----------
MINIO_ROOT_USER=<GENERATE_USER>
MINIO_ROOT_PASSWORD=<GENERATE_32_CHAR_RANDOM>
S3_ENDPOINT=http://minio:9000
S3_BUCKET_AUDIO=pcg-audio
S3_BUCKET_REPORTS=pcg-reports
S3_ACCESS_KEY=<MINIO_APP_ACCESS_KEY>
S3_SECRET_KEY=<MINIO_APP_SECRET_KEY>

# ---------- Auth ----------
JWT_SECRET=<GENERATE_64_CHAR_RANDOM>          # openssl rand -hex 32
JWT_ACCESS_TTL_MIN=15
JWT_REFRESH_TTL_DAYS=7
COOKIE_SECURE=true
COOKIE_SAMESITE=strict
FIELD_ENCRYPTION_KEY=<FERNET_KEY_BASE64>      # python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
PII_HASH_PEPPER=<GENERATE_32_CHAR_RANDOM>

# ---------- DeepSeek ----------
DEEPSEEK_API_KEY=<SET_ON_SERVER_ONLY>
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_TIMEOUT_S=60
DEEPSEEK_DAILY_BUDGET_USD=<LIMIT>

# ---------- Cheklovlar ----------
MAX_UPLOAD_MB=50
RATE_LIMIT_LOGIN=5/minute
RATE_LIMIT_API=120/minute
RATE_LIMIT_AI=10/minute
RETENTION_AUDIO_DAYS=<SIYOSAT_BO'YICHA>
RETENTION_AUDIT_DAYS=<SIYOSAT_BO'YICHA>

# ---------- Kuzatuv (ixtiyoriy) ----------
SENTRY_DSN=
SENTRY_TRACES_SAMPLE_RATE=0.0
BACKUP_S3_ENDPOINT=<OFFSITE_S3_URL>
BACKUP_S3_BUCKET=<OFFSITE_BUCKET>
BACKUP_AGE_RECIPIENT=<age1...PUBLIC_KEY>
```

Qoidalar: tasodifiy qiymatlar `openssl rand -base64 32` bilan serverning o'zida yaratiladi; chatga, gitga, CI logiga yozilmaydi; `.env` fayli hech qachon `docker compose config` chiqishi bilan birga ulashilmaydi (u sirlarni ochib yuboradi).

---

## 6. Nginx vhost (Cloudflare ortida)

### 6.1 Cloudflare sozlamalari
- DNS: `cardiopcgai.189.uz` A → 164.68.111.41, **Proxied** (to'q sariq bulut).
- SSL/TLS rejimi: **Full (strict)** — Flexible TAQIQLANADI (tibbiy ma'lumot Cloudflare→origin orasida ochiq ketmasligi kerak).
- Always Use HTTPS: yoqilgan; Minimum TLS 1.2; TLS 1.3 yoqilgan; HSTS Cloudflare'da ham yoqiladi.
- WAF Managed Rules va Bot Fight Mode yoqiladi; `/api/auth/login` uchun Rate Limiting qoidasi (masalan 20 so'rov/daq/IP).
- Origin'ni himoyalash: ufw'da 443 ni faqat Cloudflare IP diapazonlariga ochish **boshqa saytlarga ta'sir qilishi mumkin** — shuning uchun global ufw o'zgartirilmaydi; o'rniga vhost darajasida `allow <CF ranges>; deny all;` (6.3) yoki Authenticated Origin Pulls (mTLS) ishlatiladi.

### 6.2 Sertifikat variantlari
- **A) certbot (tavsiya, agar serverda allaqachon bor bo'lsa):** Cloudflare proxy ortida HTTP-01 ishlaydi, agar 80-port `/.well-known/acme-challenge/` ochiq bo'lsa.
  ```bash
  sudo certbot certonly --webroot -w /var/www/certbot -d cardiopcgai.189.uz --dry-run
  sudo certbot certonly --webroot -w /var/www/certbot -d cardiopcgai.189.uz
  ```
  Mavjud avto-yangilanish taymeri o'zgartirilmaydi; `--deploy-hook "nginx -t && systemctl reload nginx"`.
- **B) Cloudflare Origin Certificate:** dashboard'da yaratiladi (15 yil), `/etc/ssl/cardiopcg/origin.pem` va `origin.key` (`chmod 600`, root). Faqat Cloudflare proxy orqali ishlaydi (to'g'ridan-to'g'ri kirishda brauzer ishonmaydi) — bizga shu yetadi.

### 6.3 /etc/nginx/sites-available/cardiopcgai.189.uz
```nginx
# Cloudflare real IP (diapazonlar: https://www.cloudflare.com/ips/ — oyiga bir tekshiriladi)
# Bu direktivalar umumiy nginx.conf'ga TEGMASLIK uchun shu server{} ichida emas, balki
# faqat shu vhost'ga tegishli qilinadi: agar http-darajada allaqachon set_real_ip_from bor bo'lsa, takrorlanmaydi.
upstream cardiopcg_api { server 127.0.0.1:18400; keepalive 16; }
upstream cardiopcg_web { server 127.0.0.1:18401; keepalive 8; }

map $http_upgrade $cardiopcg_conn_upgrade { default upgrade; '' close; }

server {
    listen 80;
    listen [::]:80;
    server_name cardiopcgai.189.uz;
    location /.well-known/acme-challenge/ { root /var/www/certbot; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl;
    http2 on;
    server_name cardiopcgai.189.uz;

    ssl_certificate     /etc/letsencrypt/live/cardiopcgai.189.uz/fullchain.pem;   # yoki /etc/ssl/cardiopcg/origin.pem
    ssl_certificate_key /etc/letsencrypt/live/cardiopcgai.189.uz/privkey.pem;     # yoki /etc/ssl/cardiopcg/origin.key
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:cardiopcg_ssl:10m;
    ssl_session_timeout 1d;

    # Cloudflare orqali haqiqiy mijoz IP (faqat CF diapazonlaridan kelgan so'rovlarga ishonamiz)
    include /etc/nginx/cardiopcg-cloudflare-realip.conf;   # set_real_ip_from ...; real_ip_header CF-Connecting-IP;

    access_log /var/log/nginx/cardiopcg.access.log;
    error_log  /var/log/nginx/cardiopcg.error.log warn;

    # Yuklash hajmi (PCG audio); API uchun, qolganlari kichik
    client_max_body_size 55m;
    client_body_timeout 60s;

    # gzip (audio/PNG siqilmaydi)
    gzip on;
    gzip_comp_level 5;
    gzip_min_length 1024;
    gzip_types text/css application/javascript application/json image/svg+xml text/plain;

    # Xavfsizlik sarlavhalari
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Permissions-Policy "camera=(), geolocation=(), microphone=(self)" always;
    add_header Cross-Origin-Opener-Policy "same-origin" always;
    add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self' wss://cardiopcgai.189.uz; font-src 'self'; object-src 'none'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'" always;

    server_tokens off;

    # API
    location /api/ {
        proxy_pass http://cardiopcg_api;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Connection "";
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        client_max_body_size 55m;
        add_header Cache-Control "no-store" always;
    }

    # WebSocket / SSE
    location /ws/ {
        proxy_pass http://cardiopcg_api;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $cardiopcg_conn_upgrade;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto https;
        proxy_read_timeout 3600s;
        proxy_buffering off;          # SSE uchun ham
    }

    # Ichki endpointlar tashqaridan yopiq
    location ~ ^/(metrics|docs|redoc|openapi\.json) { return 404; }

    # Frontend (SPA)
    location / {
        proxy_pass http://cardiopcg_web;
        proxy_set_header Host $host;
        client_max_body_size 1m;
    }
}
```

Eslatmalar:
- `cardiopcg-cloudflare-realip.conf` — alohida fayl; ichida Cloudflare IPv4/IPv6 diapazonlari uchun `set_real_ip_from`, `real_ip_header CF-Connecting-IP; real_ip_recursive on;`. Agar boshqa saytlar allaqachon http-darajada real_ip sozlagan bo'lsa, `nginx -T` dan tekshirib, takrorlanish/ziddiyat oldi olinadi.
- CSP ilk ishga tushirishda `Content-Security-Policy-Report-Only` rejimida sinaladi, keyin majburiy qilinadi. wavesurfer.js blob audio ishlatadi, shuning uchun `media-src blob:` bor.
- Swagger `/docs` production'da o'chirilgan (FastAPI `docs_url=None`).

### 6.4 Faollashtirish tartibi (xavfsiz)
```bash
sudo cp -a /etc/nginx /root/backup-nginx-$(date +%F-%H%M)
sudo cp cardiopcgai.189.uz /etc/nginx/sites-available/
sudo ln -s /etc/nginx/sites-available/cardiopcgai.189.uz /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx     # -t xato bersa: symlink'ni olib tashlab, reload QILMASLIK
curl -sI https://cardiopcgai.189.uz/ | head
```
`nginx -t` xato bersa darhol `sudo rm /etc/nginx/sites-enabled/cardiopcgai.189.uz` va qayta `nginx -t`.

---

## 7. SSH kalit asosidagi deploy jarayoni

Parol bilan SSH ishlatilmaydi; CI/operator uchun alohida `deploy` foydalanuvchi va ed25519 kalit (`~/.ssh/authorized_keys` da, mumkin bo'lsa `restrict` + `command=` cheklovi bilan). Server kodi: `/opt/cardiopcg/releases/<sha>/`, joriy: `/opt/cardiopcg/current` (symlink), umumiy: `/opt/cardiopcg/shared/.env`.

```bash
# Lokal mashina (yoki CI) — git archive | ssh tar
SHA=$(git rev-parse --short HEAD)
ssh deploy@164.68.111.41 "mkdir -p /opt/cardiopcg/releases/$SHA"
git archive --format=tar HEAD | ssh deploy@164.68.111.41 "tar -x -C /opt/cardiopcg/releases/$SHA"

# Serverda
ssh deploy@164.68.111.41 bash -s <<EOF
set -euo pipefail
cd /opt/cardiopcg/releases/$SHA
ln -sfn /opt/cardiopcg/shared/.env deploy/.env
export APP_VERSION=$SHA
docker compose -p cardiopcg -f deploy/docker-compose.prod.yml config -q
docker compose -p cardiopcg -f deploy/docker-compose.prod.yml build
# migratsiya (8-bo'lim) — eski API hali ishlab turibdi
docker compose -p cardiopcg -f deploy/docker-compose.prod.yml run --rm api alembic upgrade head
docker compose -p cardiopcg -f deploy/docker-compose.prod.yml up -d --build
ln -sfn /opt/cardiopcg/releases/$SHA /opt/cardiopcg/current
EOF
```

Deploy'dan keyin tekshiruv (smoke):
```bash
curl -fsS https://cardiopcgai.189.uz/api/healthz
curl -fsS https://cardiopcgai.189.uz/api/readyz     # DB + Redis + MinIO
docker compose -p cardiopcg ps
docker compose -p cardiopcg logs --tail=50 api worker
```

Qoidalar: faqat `-p cardiopcg`; `.env` repo bilan birga ko'chirilmaydi (`git archive` unda yo'q); oxirgi 5 ta release saqlanadi, eskilari `rm -rf` bilan faqat `/opt/cardiopcg/releases/` ichida tozalanadi; deploy paytida bitta vaqtda bitta jarayon (`flock /tmp/cardiopcg-deploy.lock`).

---

## 8. Zero-downtime, rollback va DB migratsiyalar

### 8.1 Deyarli to'xtovsiz yangilash
Bitta serverda to'liq blue/green og'ir, shuning uchun amaliy yondashuv:
1. Yangi image oldindan quriladi (eski konteynerlar ishlab turadi).
2. Migratsiya **orqaga mos (expand/contract)** yoziladi: avval ustun/jadval qo'shish (eski kod buzilmaydi), keyingi relizda eski ustunni olib tashlash.
3. `docker compose up -d` faqat o'zgargan servislarni qayta yaratadi; `healthcheck` o'tmaguncha nginx upstream'ga yuklanmaydi (qisqa uzilish 2–5 s, gunicorn `graceful-timeout` hisobiga cho'zilgan so'rovlar tugaydi).
4. Agar kerak bo'lsa: ikkinchi `api` nusxasi (`18402`) ko'tariladi, nginx upstream'da ikkalasi turadi, keyin eskisi o'chiriladi.
5. Celery worker `SIGTERM` da joriy vazifani tugatadi (`stop_grace_period: 120s`); vazifalar idempotent bo'ladi (`acks_late=True`).

### 8.2 Rollback
```bash
PREV=<oldingi-sha>
ssh deploy@164.68.111.41 bash -s <<EOF
set -euo pipefail
cd /opt/cardiopcg/releases/$PREV
export APP_VERSION=$PREV
docker compose -p cardiopcg -f deploy/docker-compose.prod.yml up -d      # oldingi image hali keshda
ln -sfn /opt/cardiopcg/releases/$PREV /opt/cardiopcg/current
EOF
```
- Image'lar `cardiopcg/api:<sha>` teglari bilan saqlanadi (oxirgi 5 ta), shuning uchun rollback qayta qurishsiz.
- DB rollback: migratsiyalarda `downgrade()` yoziladi, lekin production'da avvalo **orqaga mos** migratsiya qoidasiga tayaniladi; halokatli migratsiya (DROP/ALTER TYPE) oldidan majburiy `pg_dump` (9-bo'lim).
- Migratsiya va kod rollback tartibi: avval kod rollback (eski kod yangi sxema bilan ishlaydi), faqat zarur bo'lsa `alembic downgrade -1`.

### 8.3 Migratsiya qoidalari
- `alembic revision --autogenerate` natijasi qo'lda ko'rib chiqiladi; `NOT NULL` ustun qo'shishda default yoki 3 bosqich (nullable → to'ldirish → NOT NULL).
- Katta jadvalga indeks: `CREATE INDEX CONCURRENTLY` (alohida migratsiya, `autocommit_block`).
- DDL'ni production tranzaksiyasida sinab ko'rish TAQIQ; avval staging nusxada (`pg_dump` dan tiklangan vaqtinchalik DB, alohida konteyner, nomi `cardiopcg-migtest`, keyin o'chiriladi).
- Migratsiya `run --rm` bilan, lock timeout bilan: `SET lock_timeout='5s'`.
- Birinchi admin: `docker compose -p cardiopcg run --rm api python scripts/create_admin.py` (parol interaktiv so'raladi yoki bir martalik `ADMIN_BOOTSTRAP_PASSWORD` env, ishlatilgach `.env`dan o'chiriladi). Seed/demo parollar production'da YO'Q.

---

## 9. Zaxira nusxalar (backup)

**Nima zaxiralanadi:** PostgreSQL (asosiy), MinIO bucket'lari (audio/hisobotlar), `deploy/.env` (shifrlangan, alohida saqlanadi), nginx vhost fayli.

`/opt/cardiopcg/scripts/backup.sh`:
```bash
#!/usr/bin/env bash
set -euo pipefail
STAMP=$(date +%F-%H%M)
DIR=/opt/cardiopcg/backups
mkdir -p "$DIR"
# 1) Postgres: custom format (parallel restore mumkin)
docker exec cardiopcg-postgres pg_dump -U cardiopcg_app -d cardiopcg -Fc \
  | age -r "$BACKUP_AGE_RECIPIENT" > "$DIR/pg-$STAMP.dump.age"
# 2) MinIO (mc mirror yoki volume tar)
docker run --rm -v cardiopcg_minio:/data:ro -v "$DIR":/out alpine \
  tar -czf "/out/minio-$STAMP.tgz" -C /data .
age -r "$BACKUP_AGE_RECIPIENT" -o "$DIR/minio-$STAMP.tgz.age" "$DIR/minio-$STAMP.tgz" && rm "$DIR/minio-$STAMP.tgz"
# 3) Offsite (boshqa server yoki S3; shifrlangan holda)
rclone copy "$DIR/pg-$STAMP.dump.age" offsite:cardiopcg-backups/
# 4) Retention: lokal 7 kun, offsite 30 kun kunlik + 12 oylik
find "$DIR" -type f -mtime +7 -delete
```
Cron (faqat `deploy` foydalanuvchining crontab'i, boshqalarnikiga tegilmaydi):
```cron
15 3 * * * /opt/cardiopcg/scripts/backup.sh >> /var/log/cardiopcg-backup.log 2>&1
0 4 * * 0  /opt/cardiopcg/scripts/restore-test.sh >> /var/log/cardiopcg-restore-test.log 2>&1
```

**Retention:** lokal 7 kun, offsite 30 kunlik + 12 oylik (yoki tibbiy siyosatga ko'ra uzunroq). Zaxira fayllari `age` bilan shifrlanadi (maxfiy kalit serverda EMAS, egasida); bucket ommaviy bo'lmasligi shart.

**Restore testi (haftalik, avtomatik):** zaxira oxirgi nusxadan vaqtinchalik konteynerga tiklanadi va tekshiriladi:
```bash
docker run -d --name cardiopcg-restoretest --network none -e POSTGRES_PASSWORD=<TEMP> postgres:17-alpine
age -d -i <PRIVATE_KEY_FILE> pg-LATEST.dump.age | docker exec -i cardiopcg-restoretest pg_restore -U postgres -d postgres --create --no-owner
docker exec cardiopcg-restoretest psql -U postgres -d cardiopcg -c "SELECT count(*) FROM users; SELECT max(created_at) FROM examinations;"
docker rm -f cardiopcg-restoretest
```
Natija (qatorlar soni, oxirgi yozuv vaqti) logga yoziladi; nolga teng yoki xato — alert. Maqsadlar: **RPO ≤ 24 soat, RTO ≤ 2 soat** (keyin WAL arxivlash/`pgBackRest` bilan RPO kamaytiriladi).

---

## 10. Monitoring va logging

- **Healthcheck:** `/healthz` (jarayon tirik), `/readyz` (DB, Redis, MinIO, Celery ping). Docker healthcheck'lar 3-bo'limda.
- **Log:** structlog JSON (`timestamp`, `level`, `request_id`, `user_id` (hash), `route`, `latency_ms`). **PHI loglarga yozilmaydi** (ism, tug'ilgan sana, telefon, audio mazmuni, AI prompt matni — yo'q); faqat ichki ID'lar. `request_id` har so'rovda `X-Request-ID` sifatida beriladi.
- **Docker log rotatsiyasi:** 10 MB × 3 (3-bo'lim). Nginx loglari `logrotate` (vhost'ga xos fayllar: `cardiopcg.*.log`, haftalik, 8 hafta) — umumiy logrotate fayllariga tegmasdan alohida `/etc/logrotate.d/cardiopcg`.
- **Sentry (ixtiyoriy):** `SENTRY_DSN` bo'lsa yoqiladi; `send_default_pii=False`, `before_send` filtri PHI maydonlarini olib tashlaydi; traces sample 0 yoki past.
- **Uptime:** tashqi monitor (UptimeRobot/Better Stack) `https://cardiopcgai.189.uz/api/healthz` ni 1 daq oralig'ida tekshiradi; Telegram/email alert. Qo'shimcha: DB hajmi, disk to'lishi (`df` > 80% alert), konteyner qayta ishga tushish soni, Celery navbati uzunligi, DeepSeek xato ulushi va kunlik sarf.
- **Metrikalar:** `/metrics` (Prometheus, faqat ichki — nginx 404 beradi); keyin ixtiyoriy Grafana. Resurs kuzatuvi: `docker stats --no-stream` skriptli yig'ish.
- **Alert chegaralari:** 5xx > 2% (5 daq), p95 latency > 2 s, worker navbati > 50, backup 26 soatdan eski, sertifikat < 14 kun.

---

## 11. CI (GitHub Actions)

`.github/workflows/ci.yml` — har PR va `main` ga push'da. Deploy qo'lda yoki alohida, tasdiqlanadigan workflow (`environment: production`, required reviewer).

```yaml
name: ci
on: { pull_request: {}, push: { branches: [main] } }
jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres: { image: "postgres:17-alpine", env: { POSTGRES_PASSWORD: test, POSTGRES_DB: test }, ports: ["5432:5432"], options: >-
        --health-cmd "pg_isready" --health-interval 5s --health-retries 10 }
      redis: { image: "redis:7-alpine", ports: ["6379:6379"] }
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: cd backend && uv sync --frozen
      - run: cd backend && uv run ruff check . && uv run ruff format --check .
      - run: cd backend && uv run mypy app          # ixtiyoriy, bosqichma-bosqich
      - run: cd backend && uv run pytest -q --cov=app --cov-fail-under=80
        env: { DATABASE_URL: "postgresql+asyncpg://postgres:test@localhost:5432/test", REDIS_URL: "redis://localhost:6379/0" }
      - run: cd backend && uv run pip-audit
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm, cache-dependency-path: frontend/pnpm-lock.yaml }
      - run: cd frontend && pnpm install --frozen-lockfile
      - run: cd frontend && pnpm lint && pnpm typecheck && pnpm test --run && pnpm build
  e2e:
    needs: [backend, frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker compose -f deploy/docker-compose.ci.yml up -d --build --wait
      - run: cd frontend && pnpm exec playwright install --with-deps chromium && pnpm exec playwright test
  docker:
    needs: [backend, frontend]
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: docker build -t cardiopcg/api:ci backend && docker build -t cardiopcg/frontend:ci frontend
      - uses: aquasecurity/trivy-action@0.28.0
        with: { image-ref: "cardiopcg/api:ci", severity: "HIGH,CRITICAL", exit-code: "1" }
  secrets-scan:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: gitleaks/gitleaks-action@v2
```
GitHub Secrets: `DEPLOY_SSH_KEY`, `DEPLOY_HOST`, `DEPLOY_KNOWN_HOSTS` (host kaliti pin qilinadi, `StrictHostKeyChecking=yes`). Production `.env` qiymatlari GitHub'da saqlanmaydi. Branch himoyasi: `main` ga faqat CI yashil PR orqali; Dependabot/Renovate yoqilgan.

---

## 12. Tibbiy ma'lumot xavfsizligi (HIPAA-uslubidagi nazorat)

Rasmiy HIPAA/GDPR sertifikatsiyasi talab qilinmasa ham, shu printsiplar amalga oshiriladi; O'zbekiston "Shaxsga doir ma'lumotlar to'g'risida"gi qonun talablari alohida yuridik tekshiruvdan o'tkaziladi (ayniqsa ma'lumotlarni chet elga uzatish va mahalliy serverda saqlash talabi).

### 12.1 Shifrlash
- **In transit:** Cloudflare→origin TLS (Full strict), faqat TLS 1.2+; ichki tarmoqda DB/Redis/MinIO ga faqat konteynerlararo (hostga chiqmaydi). Rasmiy talab bo'lsa ichki Postgres uchun ham `sslmode=require`.
- **At rest:** diskni shifrlash (LUKS) hostda mumkin bo'lmasa — **ilova darajasidagi shifrlash**: sezgir ustunlar (FIO, telefon, tug'ilgan sana, shikoyat/izohlar) `FIELD_ENCRYPTION_KEY` (Fernet/AES-GCM) bilan SQLAlchemy `TypeDecorator` orqali; qidiruv kerak bo'lgan maydonlar uchun `HMAC(PII_HASH_PEPPER, value)` blind-index. MinIO'da server-side encryption (SSE-S3/KMS) yoqiladi. Zaxiralar `age` bilan shifrlanadi.
- Parollar: argon2id; refresh token DB'da faqat hash ko'rinishida; cookie `HttpOnly; Secure; SameSite=Strict`.

### 12.2 PII minimizatsiyasi
Faqat zarur ma'lumot yig'iladi (klinik maqsadga bog'liq bo'lmagan maydonlar so'ralmaydi). Bemor identifikatorlari (FIO, telefon, manzil, pasport) klinik ma'lumotdan alohida jadvalda; tahlil/AI qatlami faqat pseudonim `patient_ref` (UUID) bilan ishlaydi.

### 12.3 DeepSeek'ga yuborishdan oldin de-identifikatsiya (majburiy)
DeepSeek — uchinchi tomon (chet el) API, shu sababli unga **hech qachon** to'g'ridan-to'g'ri identifikatsiya qiluvchi ma'lumot yuborilmaydi:
1. `deidentify(payload)` xizmati allowlist asosida ishlaydi: faqat yosh (yil/diapazon, aniq tug'ilgan sana emas), jins, signal xususiyatlari (HR, S1/S2 intervallari, shovqin indekslari, spektral ko'rsatkichlar), kerakli klinik belgilar (qisqartirilgan) yuboriladi.
2. Erkin matnli maydonlar (shikoyat, shifokor izohi) regex + NER/qoida bilan tozalanadi (ism, telefon, manzil, ID, sana); ishonchsiz bo'lsa — yuborilmaydi.
3. Audio fayl va spektrogramma rasmi DeepSeek'ga yuborilmaydi; faqat hisoblangan raqamli xususiyatlar.
4. Yuborishdan oldin `assert_no_pii()` qo'riqchisi (patterns: telefon, `\d{14}` JShShIR, email, FIO bazadagi qiymatlar bilan solishtirish) — topilsa so'rov bekor, audit logga `ai_blocked_pii` yoziladi.
5. Natija qaytgach `patient_ref` orqali qayta bog'lanadi; javob shifokor tasdiqlamaguncha "yakuniy" ko'rinmaydi (00-hujjat tibbiy printsipi).
6. Kunlik byudjet/limit (`DEEPSEEK_DAILY_BUDGET_USD`), timeout, retry (≤2), `circuit breaker`; DeepSeek ishlamasa — signal tahlili natijalari AI izohisiz ko'rsatiladi.
7. Bemorning AI ishlatilishiga rozilik belgisi (`consent_ai_processing`) tekshiriladi; rozilik yo'q bo'lsa AI chaqirilmaydi.

### 12.4 Audit log
Append-only jadval `audit_log` (DB foydalanuvchisida UPDATE/DELETE huquqi olib tashlanadi; yoki xesh-zanjir): `ts`, `user_id`, `role`, `ip`, `action` (login, login_failed, view_patient, upload_audio, run_analysis, ai_call, approve_prescription, export, delete, role_change), `resource_type/id`, `result`, `request_id`. Bemor yozuvini ko'rish ham loglanadi (kim, qachon, nima). AI chaqiruvi: model, prompt hash, tokenlar, natija holati (matn emas yoki shifrlangan). Admin audit jurnalini ko'ra oladi, tahrirlay olmaydi.

### 12.5 Saqlash muddati va o'chirish
`RETENTION_*` siyosati: xom audio (masalan N oy/yil — tibbiy-huquqiy talabga ko'ra belgilanadi), tahlil natijalari klinik yozuv sifatida uzoqroq, audit log kamida 1–3 yil. Celery beat kunlik tozalash vazifasi; bemor o'chirish so'rovi — soft-delete + muddatidan keyin hard-delete (MinIO obyektlari ham). O'chirish amali auditga yoziladi. Zaxiralardagi ma'lumot siyosat muddatida tabiiy ravishda eskiradi.

### 12.6 Kirish nazorati va rate limit
RBAC har endpointda (admin/doctor/nurse); hamshira AI natijasini o'zgartira olmaydi (server tomonida majburlanadi); faqat o'z bemorlari/bo'limi (object-level authorization), IDOR testlari. Rate limit: login `5/min/IP+username`, 10 ta xatodan keyin vaqtinchalik blokirovka, API `120/min`, AI `10/min/user`, yuklash `20/soat/user` (Redis, `slowapi`/custom). Yuklangan fayl tekshiruvi: MIME + magic bytes, davomiylik/hajm cheklovi, `ffprobe` bilan validatsiya, fayl nomi qayta yoziladi (UUID), antivirus (`clamav`) ixtiyoriy. Parol siyosati: min 12 belgi, bo'sh sessiya vaqti (idle timeout) 30 daq, 2FA (TOTP) admin/doctor uchun tavsiya.

### 12.7 Server qattiqlashtirish (eslatma)
- **fail2ban:** `sshd` jail faol bo'lishi kerak (razvedkada tekshiriladi); yo'q bo'lsa o'rnatish **umumiy server uchun global o'zgarish** hisoblanadi — egasi bilan kelishib, zaxira bilan qilinadi. Nginx uchun `cardiopcg.access.log` bo'yicha alohida jail (`nginx-botsearch`/login 401 spami) faqat shu log fayl uchun; Cloudflare ortida IP `CF-Connecting-IP` bo'lgani uchun ban qoidasi Cloudflare API orqali (action `cloudflare`) yoki WAF rate limit bilan bajariladi, aks holda Cloudflare IP'lari ban bo'lib qoladi.
- SSH: `PasswordAuthentication no`, `PermitRootLogin no` — global o'zgarish, faqat kelishuv va zaxira bilan.
- Docker socket konteynerlarga ulanmaydi; konteynerlar non-root, `read_only`, `no-new-privileges`, `cap_drop: [ALL]` (mumkin bo'lganda).
- Avtomatik xavfsizlik yangilanishlari (`unattended-upgrades`) holati tekshiriladi; image'lar oyiga bir `--pull` bilan yangilanadi.

### 12.8 Sirlar aylanishi (rotation)
| Sir | Davr | Tartib |
|---|---|---|
| JWT_SECRET | 90 kun | ikki kalit bilan o'tish davri (`kid`), eski kalit 15 daqiqa (access TTL) kutiladi |
| DB/Redis/MinIO parollari | 180 kun yoki xodim ketganda | yangi parol → `.env` → `ALTER USER` → konteyner qayta yaratish |
| FIELD_ENCRYPTION_KEY | 12 oy | `MultiFernet` (yangi + eski), fon vazifa bilan qayta shifrlash, keyin eskisini o'chirish |
| DEEPSEEK_API_KEY | 90 kun yoki sizib chiqsa | provayder panelida yangi kalit → `.env` → `docker compose up -d api worker` |
| SSH deploy kaliti | 12 oy | yangi kalit qo'shish, eskisini olib tashlash |
| Cloudflare Origin sertifikat | 12–15 yil / ogohlantirish | muddatidan oldin yangilash |

Sizib chiqish (incident) holatida: kalitni darhol bekor qilish, aylantirish, audit logdan ta'sirlangan davrni aniqlash, foydalanuvchilarni qayta login qildirish (refresh tokenlarni bekor qilish). Incident javob rejasi va buzilish haqida xabar berish tartibi alohida hujjatlanadi.

---

## 13. Test strategiyasi

### 13.1 Unit/integratsiya (pytest)
- `pytest`, `pytest-asyncio`, `httpx.AsyncClient`, `testcontainers` yoki CI service'lari (haqiqiy Postgres/Redis; DB mock qilinmaydi).
- Qamrov maqsadi: umumiy ≥ 80%, auth/RBAC/de-identifikatsiya modullari ≥ 95%.
- Integratsiya senariylari: login → refresh rotation → logout; RBAC matritsasi (har rol × har endpoint, 403/200); object-level IDOR; audio yuklash → Celery → natija → WebSocket bildirishnoma; shifokor tasdiqlamaguncha bemorga ko'rinmaslik; audit logga yozilishi; rate limit 429; yuklash chegaralari (413, noto'g'ri MIME 415).
- Alembic: bo'sh DB'da `upgrade head`, `downgrade base`, sxema drift tekshiruvi (`alembic check`).

### 13.2 Signal qayta ishlash — golden fayllar
- `backend/tests/golden/` ichida qisqa (3–10 s) sintetik va ruxsat etilgan ochiq PCG namunalari (PhysioNet/CinC 2016, litsenziya tekshirilgan; haqiqiy bemor yozuvlari repoga QO'YILMAYDI) + kutilgan natija JSON (HR, S1/S2 pozitsiyalari, shovqin bahosi, spektral xususiyatlar).
- Test: deterministik pipeline bir xil kirishda bir xil chiqishni beradi; son qiymatlar `pytest.approx` bilan toleransda (HR ±2 bpm, S1/S2 vaqti ±20 ms, F1 ≥ chegara); regressiya aniqlansa test yiqiladi. Golden fayllar versiyalanadi, yangilash faqat ongli (`--update-golden` flag + ko'rib chiqish).
- Sintetik testlar: ma'lum chastotali sinus/impuls, nol/juda qisqa/klipped/shovqinli/turli sample-rate (4k/8k/44.1k), mono/stereo, buzilgan fayl — tizim aniq xato bilan javob beradi, yiqilmaydi. Property-based (`hypothesis`) — filtr barqarorligi, NaN yo'qligi.

### 13.3 Prompt eval to'plami (AI)
- `backend/tests/prompt_eval/cases.jsonl` — 50–100 ta de-identifikatsiyalangan klinik kirish (signal xususiyatlari + yosh/jins) va kutilgan xususiyatlar (rubrika): majburiy ogohlantirish matni bor, doza/qarshi ko'rsatma/allergiya tekshiruvi eslatilgan, "shifokor tasdiqlaydi" belgisi, noma'lumda "noaniq" deydi (gallyutsinatsiya yo'q), PII qaytarmaydi, strukturali JSON sxemaga mos.
- Avtomatik tekshiruvlar: JSON sxema validatsiyasi, taqiqlangan iboralar ro'yxati ("aniq tashxis", "dorini to'xtating"), majburiy iboralar; xavfli (adversarial) kirishlar — prompt injection izohda ("oldingi ko'rsatmalarni unut"), noto'g'ri/ziddiyatli ma'lumot.
- Ikkinchi LLM-hakam yoki shifokor ko'rigi (muntazam, namunaviy 20 ta) — ball chegarasi; prompt/model versiyasi o'zgarganda eval qayta yuritiladi va natijalar solishtiriladi. CI'da DeepSeek'ga haqiqiy chaqiruv bo'lmaydi (yozib olingan javoblar/mock); haqiqiy eval qo'lda yoki tunda byudjet bilan.

### 13.4 E2E (Playwright)
Asosiy oqimlar (chromium + mobil viewport): admin birinchi kirish va foydalanuvchi yaratish; doctor: bemor yaratish → audio yuklash → progress (WebSocket) → natija (to'lqin, spektrogramma, S1/S2) → AI izohi → tasdiqlash; nurse: ko'radi, AI natijasini tahrirlay olmaydi; noto'g'ri parol/blokirovka; sessiya tugashi va refresh; RBAC (nurse admin sahifaga kira olmaydi); yuklashda katta/noto'g'ri fayl xatosi; o'zbekcha matnlar va emoji yo'qligi. Skrinshot/trace xatolikda artefakt sifatida saqlanadi.

### 13.5 Yuklama sinovi (locust yoki k6)
- Stsenariy: login, bemorlar ro'yxati, audio yuklash (5–10 MB), natijani polling/WS, hisobot yuklash.
- Maqsadlar (boshlang'ich): 50 bir vaqtdagi foydalanuvchi, p95 < 800 ms (oddiy GET), yuklash+tahlil navbati bilan p95 tahlil tugash < 60 s (30 s PCG uchun), xato < 1%, worker xotirasi limitdan oshmaydi.
- **Umumiy server qoidasi:** yuklama sinovi production'ga qarshi faqat past intensivlikda va kelishilgan vaqt oynasida (kechasi), boshqa loyihalar yuklamasini kuzatib turgan holda (`docker stats`, `uptime`); CPU load boshqa loyihalarga ta'sir qilsa — darhol to'xtatiladi. To'liq stress sinov lokal/staging muhitda o'tkaziladi.
```bash
k6 run --vus 20 --duration 3m loadtest/smoke.js
# yoki
locust -f loadtest/locustfile.py --headless -u 50 -r 5 -t 5m --host https://cardiopcgai.189.uz
```

### 13.6 Xavfsizlik testlari
`bandit`, `pip-audit`, `pnpm audit`, `trivy`, `gitleaks` (CI); OWASP ZAP baseline (staging); qo'lda: JWT buzish, IDOR, fayl yuklash zararli kontent, SSRF, SQLi (ORM), XSS (CSP bilan), CORS.

---

## 14. Go-live tekshiruv ro'yxati

**Tayyorgarlik**
- [ ] Step-0 razvedka bajarilgan, natijalar saqlangan, bo'sh port diapazoni tasdiqlangan
- [ ] Resurs (RAM/disk/CPU) yetarli, limitlar moslashtirilgan
- [ ] `docker compose -p cardiopcg ... config -q` xatosiz; compose project nomi unikal
- [ ] `deploy/.env` serverda yaratilgan (`chmod 600`), barcha sirlar tasodifiy va noyob; gitda sir yo'q (`gitleaks` toza)
- [ ] Demo/seed parollar yo'q; birinchi admin `create_admin.py` bilan yaratilgan
- [ ] DEEPSEEK_API_KEY faqat serverda; de-identifikatsiya testlari yashil

**Tarmoq**
- [ ] Barcha konteyner portlari faqat `127.0.0.1`; `ss -ltnp` tashqariga ochilgan yangi port yo'qligini ko'rsatadi; Postgres/Redis/MinIO hostga publish qilinmagan
- [ ] Nginx: zaxira olingan, `nginx -t` OK, `reload` bajarilgan, boshqa saytlar (tiiame, adshare, uzex-agent, migrantlar24 va h.k.) javob berishda davom etadi (har biriga `curl -sI` bilan oldin/keyin solishtirildi)
- [ ] Cloudflare: Proxied, SSL Full (strict), WAF/rate limit, real IP ishlaydi (logda mijoz IP, CF IP emas)
- [ ] HTTPS sertifikati to'g'ri, `https://www.ssllabs.com` yoki `testssl.sh` A darajasi; sarlavhalar (HSTS, CSP, X-Frame-Options) `curl -I` bilan tasdiqlangan; WebSocket ulanadi; 55 MB fayl yuklanadi, 60 MB rad etiladi

**Ma'lumot va ishonchlilik**
- [ ] Migratsiyalar qo'llangan; `/readyz` yashil
- [ ] Backup cron ishlayapti; kamida bitta qo'lda zaxira va **muvaffaqiyatli restore testi** bajarilgan; offsite nusxa shifrlangan
- [ ] Rollback tartibi bir marta sinab ko'rilgan (oldingi teg bilan)
- [ ] Log rotatsiyasi ishlaydi; loglarda PHI yo'q (tekshirilgan)
- [ ] Uptime monitor va alertlar faol; Sentry (agar yoqilgan) PII filtri bilan

**Xavfsizlik va tibbiy**
- [ ] RBAC matritsa testi yashil; hamshira AI natijasini o'zgartira olmaydi
- [ ] Rate limit va login blokirovkasi ishlaydi; audit log yoziladi va tahrirlab bo'lmaydi
- [ ] AI chiqishida "ma'lumot uchun, shifokor tasdiqlaydi" belgisi; tasdiqlanmagan natija bemorga ko'rinmaydi
- [ ] Retention vazifasi sozlangan; foydalanuvchi roziligi (consent) oqimi bor
- [ ] fail2ban/SSH holati ko'rib chiqilgan (egasiga hisobot, global o'zgarish bo'lsa kelishuv bilan)
- [ ] Sirlar aylanish kalendari tuzilgan

**Sifat**
- [ ] CI yashil (lint, test, build, trivy, gitleaks); e2e asosiy oqimlar o'tadi; golden va prompt eval chegaralari bajarilgan; yengil yuklama sinovi chegaralarda
- [ ] Interfeysda emoji yo'q, matnlar o'zbekcha

**Go-live kuni:** deploy → smoke → boshqa saytlar nazorati → 24 soat kuzatuv (`docker stats`, loglar, alertlar) → bir hafta davomida kunlik tekshiruv.

---

## 15. Definition of Done

Vazifa/bo'lim "tayyor" hisoblanadi, agar:
1. Kod `main` ga PR orqali, CI to'liq yashil (ruff, testlar ≥ qamrov chegarasi, build, trivy, gitleaks).
2. Yangi funksiyaga unit + integratsiya testlari bor; kritik oqim uchun e2e; signal/AI o'zgarishida golden/eval yangilangan va ko'rib chiqilgan.
3. DB o'zgarishi orqaga mos Alembic migratsiya bilan, restore va rollback izohlangan.
4. Xavfsizlik: yangi endpointda RBAC + object-level tekshiruv, audit log yozuvi, rate limit, kiruvchi ma'lumot validatsiyasi; PHI loglarga/DeepSeek'ga sizmaydi.
5. Konfiguratsiya `.env.example` ga placeholder bilan qo'shilgan; haqiqiy sir gitda yo'q.
6. Deploy skripti orqali serverga chiqarilgan, `/readyz` yashil, smoke o'tgan, boshqa loyihalar ta'sirlanmagan (oldin/keyin tekshiruv).
7. Monitoring/alert qamrab olingan; hujjat (`docs/`) yangilangan; mavjud xavf va cheklovlar ochiq yozilgan.
8. Tibbiy printsip (00-hujjat) buzilmagan: AI faqat qaror qo'llab-quvvatlash, shifokor tasdiqlaydi, barcha AI chaqiruvlari audit logda.

Butun loyiha uchun Definition of Done: go-live ro'yxati to'liq belgilangan, backup restore testi muvaffaqiyatli, 7 kun barqaror ishlagan (alertsiz yoki hal qilingan), va foydalanuvchi (egasi) qabul qilgan.
