# Agni Setu

Fire-safety certificate case management: application intake, inspections, notices, decisions,
certificate issuance and public verification. Demonstration build on synthetic data; it is not an
official government service and issues no real certificates.

**Stack:** Django 5.2 + Django REST Framework + PostgreSQL 17 · React 19 + TypeScript + Vite ·
RabbitMQ · Valkey · S3-compatible object storage · Docker Compose.

## 1. What you need

| Tool | Windows | macOS |
| --- | --- | --- |
| Docker Desktop (running) | https://www.docker.com/products/docker-desktop | same |
| Git | Git for Windows (includes **Git Bash**) | Xcode command line tools or Homebrew |
| Shell | **Git Bash** (not PowerShell / cmd) | Terminal |

Give Docker Desktop at least 4 GB of memory if you can (Settings → Resources). Everything else runs
inside containers.

## 2. Clone

```bash
git clone https://github.com/Git-hub00/Agni-Setu.git
cd Agni-Setu
```

## 3. Check the machine

```bash
scripts/dev/doctor.sh
```

It checks Docker, free ports and tooling and tells you exactly what is missing.

## 4. Start the application

```bash
scripts/dev/up.sh app
```

The first run creates `.env.local` with random secrets, then starts PostgreSQL, RabbitMQ, Valkey,
the object store, the API, the background worker, the scheduler and the web front end. Wait until
it prints `all services healthy` (a few minutes the first time).

Optional extras (needs about 2 GB more memory):

```bash
scripts/dev/up.sh all        # also starts Keycloak (staff sign-in) and ClamAV (file scanning)
```

Without ClamAV, uploaded files stay in "quarantined" until a scanner is available.

## 5. Load the demonstration data

```bash
docker exec agni-dev-api-1 python manage.py seed_demo --scenario baseline --require-demo
```

Safe to run again; it never duplicates data.

## 6. Open it

| What | Address |
| --- | --- |
| Web app | http://localhost:5173 |
| API health | http://127.0.0.1:8000/api/v1/health/ready |
| Keycloak (only with `all`) | http://localhost:8080 |

**Applicant sign-in:** enter any email address on the sign-in page, then read the one-time code from
the local demo inbox:

```
http://127.0.0.1:8000/api/v1/demo/inbox?channel=EMAIL&contact=<the email you typed>
```

**Staff sign-in** (needs `all`): click *Continue with staff identity* and use a demo persona, for
example `anita` (supervisor), `priya` / `suresh` (officers), `arjun` (administrator),
`meera` (policy approver). The password of each persona is `demo-<name>-password`.

## 7. Stop and restart

```bash
scripts/dev/down.sh          # stop containers, keep all data
scripts/dev/up.sh app        # start again
```

## 8. Run the tests (optional)

```bash
uv run --directory backend pytest -q                       # backend (needs the stack running)
corepack pnpm --dir web install --frozen-lockfile
corepack pnpm --dir web test --run                          # web unit tests
uv run --directory backend python ../scripts/dev/acceptance_run.py   # end-to-end journeys against the running stack
```

Backend tests need `uv` (https://docs.astral.sh/uv/) and web tests need Node 24 with corepack
enabled (`corepack enable`).

## 9. If something goes wrong

- `scripts/dev/doctor.sh` explains missing tools and busy ports.
- `docker compose -p agni-dev -f infra/compose/compose.dev.yml --env-file .env.local ps` shows
  container health; `... logs api` shows the API log.
- Port 5432 busy on your machine is fine: the database is published on 55432.
- Delete `.env.local` only if you want fresh secrets; the data volumes are never deleted by these
  scripts.

More on the local stack: [infra/compose/README.md](infra/compose/README.md).
Production packaging and release procedure: [infra/containers/production/README.md](infra/containers/production/README.md).
