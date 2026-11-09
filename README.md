# TriageQ

Hospital OPD triage and queue management backend.

Deterministic ESI-style triage rules, Redis priority queues with aging,
Postgres as the source of truth. An optional LLM module turns free-text
symptoms into structured fields, but triage never depends on it.

> Decision support for hospital staff, not a diagnostic tool.

## Run locally

```bash
cp .env.example .env
docker compose up --build
```

Then open http://localhost:8000/health and http://localhost:8000/docs.

## Roadmap

- [x] 1. Project skeleton
- [x] 2. Data model + migrations
- [x] 3. Auth (JWT, roles)
- [ ] 4. Triage rules engine
- [ ] 5. Redis queues with aging
- [ ] 6. Realtime dashboard, overrides, audit log
- [ ] 7. LLM symptom extractor (optional module)
- [ ] 8. Load test, eval, architecture diagram

## Schema (v1)

`users` (roles) · `departments` · `patients` (UHID) · `visits` (status lifecycle) ·
`triage_assessments` (append-only, ESI 1-5, source = rules / llm_assisted / staff_override) ·
`audit_log`. A visit's current priority is its latest assessment, so overrides never
destroy history.

## Migrations & tests

```bash
docker compose exec api alembic upgrade head      # also runs automatically on startup
docker compose exec api alembic revision --autogenerate -m "change"
docker compose exec api pytest -q
```

## Auth

- Staff accounts are created by an admin (`POST /users`); there is no open self-registration.
  The first admin is seeded from `ADMIN_EMAIL` / `ADMIN_PASSWORD` on startup.
- Login: `POST /auth/login` (OAuth2 password form) returns a short-lived JWT. Try it in `/docs`.
- Passwords hashed with argon2. Unknown email and wrong password return the same 401.
- The user is re-loaded from the DB on every request, so deactivating an account cuts access
  immediately, and the role comes from the DB, never from the token.
- `require_role(Role.NURSE, Role.DOCTOR)` protects any endpoint.
- Known gaps (planned): login rate limiting / lockout, refresh tokens, MFA.
