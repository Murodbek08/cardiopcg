# CardioPCG AI

Fonokardiogramma (PCG) tahlili platformasi: hamshira yozuv yuklaydi, signal tahlili + AI (DeepSeek) natija beradi,
shifokor tasdiqlaydi, admin boshqaradi. Tizim qaror qo'llab-quvvatlash vositasi; sertifikatsiyalangan tibbiy qurilma emas.

```
backend/    FastAPI + SQLAlchemy + Alembic + Celery (Python 3.13, uv)
frontend/   React 19 + Vite + TanStack Router (pnpm)
deploy/     production/dev compose, Dockerfile, nginx vhost, deploy/backup scripts
e2e/        Playwright end-to-end tests (dev compose stack)
docs/       TZ (00-04), BUILD_PROMPT.md
.github/    CI (ruff, pytest, frontend verify, docker build + trivy, e2e, gitleaks)
```

## Local full stack (dev)

```bash
docker compose -f deploy/docker-compose.dev.yml up -d --build --wait
# SPA + /api proxy:  http://localhost:8080      API directly: http://localhost:8000/api/v1/system/health
```

Services: `postgres` 17, `redis` 7, `minio`, `migrate` (alembic, one-shot), `api`, `worker`, `beat`, `web` (nginx, built SPA).
Create an admin by hand (password is read from the environment, never from argv):

```bash
docker compose -f deploy/docker-compose.dev.yml exec -e CREATE_ADMIN_PASSWORD='<choose>' api \
  python scripts/create_admin.py --username admin --full-name "Administrator"
```

Frontend only (hot reload, needs the API on :8080): `cd frontend && pnpm install && pnpm dev`.
Checks: `cd frontend && pnpm verify` (typecheck, lint, no-emoji, tests, build, bundle budget);
`cd backend && uv run ruff check . && uv run pytest -q` (tests start PostgreSQL via testcontainers, Docker required).

## End-to-end tests (Playwright)

```bash
bash e2e/scripts/setup-e2e.sh            # starts the dev stack + creates the test admin via backend/scripts/create_admin.py
cd e2e && pnpm install && pnpm exec playwright install chromium
pnpm test                                # chromium (all specs) + mobile viewport (access/RBAC spec)
bash scripts/setup-e2e.sh --fresh        # (from e2e/) wipes the dev DB and starts clean
```

The admin password is random, stored only in `e2e/.e2e.env` (gitignored). `global-setup.ts` creates a fresh doctor and
nurse per run. The WAV fixture is synthetic (`e2e/scripts/gen-wav.mjs`, no patient data).

Coverage: login per role, RBAC redirects (UI) and 401/403 (API), admin creates a user in the UI and the forced password
change, audit log visible and append-only, nurse creates patient + exam and uploads a synthetic wav, analysis on the worker,
nurse cannot alter AI/prescription/conclusion, doctor approves + signs, PDF export gate, audit entries.
NOTE: the doctor/nurse clinical screens (wizard, review workspace) are still placeholders in `frontend/`, so those steps run
through the REST API; the specs are written so they can be swapped for UI steps once the screens exist.

## Production deploy (shared server)

Everything is isolated: compose project `cardiopcg`, own network/volumes, CPU/RAM limits, ports bound to `127.0.0.1` only.
Ports default to the **placeholder range 18400-18409** (`CARDIOPCG_API_PORT=18400`, `CARDIOPCG_WEB_PORT=18401`) and must be
confirmed by recon.

1. **Recon (read-only):** `ssh deploy@<server> 'bash -s' < deploy/scripts/recon.sh` - ports, RAM/disk, nginx, other projects.
   If RAM < 3 GB, disk >= 80% or ports clash: stop and ask the owner.
2. **Server layout:** `/opt/cardiopcg/{releases,shared,backups,scripts}`; create `/opt/cardiopcg/shared/.env` from
   `deploy/.env.production.example`, generate every secret on the server (`openssl rand -hex 32`), `chmod 600`.
   No demo users, no secrets in git.
3. **nginx vhost (one new file, shared server!):** `deploy/scripts/install-vhost.sh` on the server (backs up `/etc/nginx`,
   `nginx -t`, `reload` only). Template: `deploy/nginx/cardiopcgai.189.uz.conf.template` (Cloudflare real IP, WebSocket
   `/api/v1/ws`, SSE, 55 MB uploads, gzip, HSTS/CSP; access log omits query strings so WS tokens are never logged).
   Cloudflare: proxied, SSL **Full (strict)**.
4. **Deploy:** `DEPLOY_HOST=deploy@<server> OTHER_SITES="https://a.example https://b.example" deploy/scripts/deploy.sh`
   (git archive | ssh tar, `compose -p cardiopcg up -d --build`, migrations via the `migrate` one-shot, health checks,
   automatic rollback on failure; other sites checked before/after). Rollback: `deploy/scripts/deploy.sh --rollback [sha]`.
5. **First admin:** `docker compose -p cardiopcg -f deploy/docker-compose.prod.yml run --rm api python scripts/create_admin.py --username <name> --full-name "<name>"` (interactive password).
6. **Verify:** `deploy/scripts/post-deploy-check.sh --own https://cardiopcgai.189.uz`
   and `--compare before.txt <other-site-urls>` for the neighbours.
7. **Backups:** cron `15 3 * * * /opt/cardiopcg/scripts/backup.sh` (age-encrypted pg dump + MinIO + vhost + env; public key
   only on the server). Restore test: `RESTORE_AGE_IDENTITY=<private key> deploy/scripts/restore-test.sh`.

Never on the shared server: `docker system/volume/network prune`, `compose down` without `-p cardiopcg`, restarting
nginx/docker, editing other vhosts.

## Rules

Secrets only in the server `.env`; DeepSeek receives de-identified data only; AI output reaches patients only after doctor
approval; the nurse cannot edit AI results; UI is Uzbek with Tabler icons (no emoji).
After first deployment rotate any credential that was ever pasted into chat (server password, DeepSeek key).
