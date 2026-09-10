# Agni Setu backend

Django 5.2 LTS / Django REST Framework modular monolith. See `docs/04_TECHNICAL_ARCHITECTURE.md`
for module boundaries and `docs/10_BUILD_GUIDE.md` for the developer workflow.

Install exactly what is locked:

```bash
cd backend
uv sync --frozen
uv run python manage.py check
```

`DATABASE_URL` is required by every settings module (PostgreSQL only, ADR-02). Local
development reads it from a gitignored `backend/.env`; see `docs/10_BUILD_GUIDE.md` s.6.
