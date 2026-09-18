# Emberpath Weight Service

FastAPI-tjeneste for daglige vektlogger, med PostgreSQL, SQLAlchemy og Alembic.
Én registrering per dato. Vekten lagres som `NUMERIC(6, 2)` og må være positiv,
maks 9999,99 kg, med inntil to desimaler. API-et returnerer vekten som JSON-tall.

## Installasjon

Installer [uv](https://docs.astral.sh/uv/getting-started/installation/).
Python 3.13 eller nyere kreves; uv henter Python ved behov.

```powershell
cd C:\Workspace\Repos\Emberpath-weight-service
uv sync --locked
Copy-Item .env.example .env
```

`.env` er lokal konfigurasjon og ignoreres av Git. Miljøvariabler overstyrer
verdiene i filen. `DATABASE_URL` brukes av appen og Alembic; `TEST_DATABASE_URL`
brukes kun av testene. `uv.lock` låser avhengighetsversjonene.

## Kjør hele appen i Docker

Docker Compose ligger i søsterrepoet `Emberpath`. Alle tre repoene må ligge
ved siden av hverandre. Dockerfilene ligger i tjenesterepoene.

```powershell
cd C:\Workspace\Repos\Emberpath
docker compose up --build -d --wait
```

Compose starter PostgreSQL, kjører `alembic upgrade head`, og starter backend
og web etter vellykket migrering. Standardporter er web `5173`, API `8000`
og PostgreSQL `5432`; de kan endres i hubrepoets `.env`. Stopp eventuell
Vite-server først, siden den også bruker port 5173. Web er tilgjengelig på
lokalnettet; API og PostgreSQL er kun bundet til `127.0.0.1`.
Data beholdes i et navngitt Docker-volum når containerne stoppes.

Se [felles oppstartsinstruksjoner](../Emberpath/readme.md).

## Kjør backend lokalt med PostgreSQL i Docker

Start databasen fra hubrepoet:

```powershell
cd C:\Workspace\Repos\Emberpath
docker compose stop weight-service
docker compose up -d --wait postgres
```

Kjør deretter fra dette repoet:

```powershell
cd C:\Workspace\Repos\Emberpath-weight-service
uv run alembic upgrade head
uv run uvicorn src.main:app --reload --port 8000
```

Oppdater `DATABASE_URL` i backendens `.env` hvis hubrepoet bruker en annen
PostgreSQL-port eller et annet passord. Kommandoene over forutsetter at API-port
8000 er ledig; stopp en eventuell eksisterende API-prosess først. Unngå å
starte både containeren og lokal Uvicorn på samme port. Hvis hubens `.env`
har `POSTGRES_PORT=55432`, bruk
`postgresql+psycopg://emberpath:emberpath_local@127.0.0.1:55432/emberpath`
som `DATABASE_URL` med standardpassordet.

`--reload` laster kodeendringer automatisk. Stopp med `Ctrl+C`.
Swagger UI finnes på `http://127.0.0.1:8000/docs` ved standard port.
Web bruker `/api` via Vite-proxy lokalt og Nginx-proxy i Docker, så nettleseren
kan kalle API-et fra samme origin uten egen CORS-konfigurasjon. Det gjelder
også fra telefon på samme Wi-Fi via `http://<PC-ens LAN-IP>:5173/weight`;
backend trenger derfor ikke bindes til alle nettverksgrensesnitt.

## API

| Metode | Endepunkt | Resultat |
| --- | --- | --- |
| GET | `/healthz` | 200 og `{"status":"ok"}`, uten databasekall |
| POST | `/weight-logs` | Opprett logg, 201 |
| GET | `/weight-logs` | Liste, nyeste dato først |
| GET | `/weight-logs/{id}` | Hent logg, 200 |
| PATCH | `/weight-logs/{id}` | Endre dato og/eller vekt, 200 |
| DELETE | `/weight-logs/{id}` | Slett logg, 204 uten responsinnhold |

Eksempel på opprettelse fra PowerShell:

```powershell
$log = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/weight-logs `
  -ContentType application/json -Body '{"date":"2026-09-17","weight_kg":82.35}'
$log
Invoke-RestMethod http://127.0.0.1:8000/weight-logs
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/weight-logs/$($log.id)" `
  -ContentType application/json -Body '{"weight_kg":82.1}'
Invoke-RestMethod -Method Delete -Uri "http://127.0.0.1:8000/weight-logs/$($log.id)"
```

En logg har feltene `id` (UUID), `date` (`YYYY-MM-DD`) og `weight_kg` (tall).
PATCH krever minst ett felt; eksplisitt `null` avvises. Ukjente felter og
ugyldige verdier gir 422. Ukjent ID gir 404. Dato som allerede er registrert
gir 409 med en `detail`-streng, også ved oppdatering. Databasen håndhever unik
dato slik at samtidige kall heller ikke lager duplikater.

## Tester

Testene kjører mot en egen PostgreSQL-container på port 5433. De bruker aldri
`DATABASE_URL`. Testdatabasen er midlertidig og separat fra dine vektlogger.

```powershell
cd C:\Workspace\Repos\Emberpath
docker compose --profile test up -d --wait postgres-test
cd ..\Emberpath-weight-service
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

Testene migrerer `emberpath_test` før kjøring og ruller hver test tilbake i en
isolert transaksjon. En egendefinert `TEST_DATABASE_URL` må bruke PostgreSQL
og et databasenavn som slutter på `_test`. Testene feiler hvis databasen ikke
kjører. Uvicorn trenger ikke å kjøre. Kun helsetesten krever ingen database:

```powershell
uv run pytest tests/test_health.py
```

Testdekningen omfatter CRUD, sortering, duplikatdato, delvis oppdatering,
validering, ukjent ID og at avviste endringer bevarer eksisterende data.

## Databaseendringer

Skjemaet opprettes og oppdateres gjennom Alembic, ikke ved appoppstart.
Etter modellendringer oppretter du en migrering og kontrollerer innholdet:

```powershell
uv run alembic revision --autogenerate -m "Describe schema change"
uv run alembic upgrade head
```

## Struktur

- `src/main.py`: FastAPI-app og ruteregistrering.
- `src/core/`: miljøkonfigurasjon og databaseøkter.
- `src/models/`: SQLAlchemy-modeller.
- `src/schemas/`: validering og API-responser.
- `src/routers/`: helse og CRUD.
- `alembic/`: versjonerte databaseendringer.
- `tests/`: helsetest og PostgreSQL-integrasjonstester.

Tjenesten er foreløpig for lokal bruk med én bruker, uten autentisering.
