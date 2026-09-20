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
verdiene i filen. `DATABASE_URL` brukes av appen og Alembic. Sett
`TEST_DATABASE_URL` kun som miljøvariabel i terminalen, aldri i `.env`: ukjente
konfigurasjonsnøkler avvises. Testene leser ikke den lokale `.env`-filen. `uv.lock` låser avhengighetsversjonene.

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

`--reload` laster kodeendringer automatisk. På Windows velger denne modusen
også Selector-eventløkken som async Psycopg krever; bruk kommandoen over ved
lokal utvikling, og Linux-containeren for kjøring uten reload. Stopp med `Ctrl+C`.
Swagger UI finnes på `http://127.0.0.1:8000/docs` ved standard port.
Web bruker `/api` via Vite-proxy lokalt og Nginx-proxy i Docker, så nettleseren
kan kalle API-et fra samme origin uten egen CORS-konfigurasjon. Det gjelder
også fra telefon på samme Wi-Fi via `http://<PC-ens LAN-IP>:5173/weight`;
backend trenger derfor ikke bindes til alle nettverksgrensesnitt.

## API

| Metode | Endepunkt | Resultat |
| --- | --- | --- |
| GET | `/` | Navn, versjon og dokumentasjonslenke når dokumentasjon er aktivert |
| GET | `/readyz` | 200 når påkrevde databasekall fungerer, ellers 503 |
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
$env:TEST_DATABASE_URL = "postgresql+psycopg://emberpath:emberpath_test@127.0.0.1:5433/emberpath_test"
uv run --locked pytest -W error
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked pyright
```

Testene migrerer `emberpath_test` før kjøring og ruller hver test tilbake i en
isolert transaksjon. En egendefinert `TEST_DATABASE_URL` må bruke PostgreSQL
og et databasenavn som slutter på `_test`. Testene feiler hvis databasen ikke
kjører. Uvicorn trenger ikke å kjøre. De øvrige testene kan kjøres uten database:

```powershell
uv run --locked pytest -m "not integration" -W error
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
- `tests/`: drifts-, kontrakt- og PostgreSQL-integrasjonstester.

Tjenesten er foreløpig for lokal bruk med én bruker, uten autentisering.

## Standard fra FastAPI-service

App-fabrikken `create_app(settings)` gir hver app sin egen late databasepool.
Økter bruker async SQLAlchemy/Psycopg; poolen lukkes ved avslutning. Alembic
bruker fortsatt synkron Psycopg for migreringer. Eksisterende modell og migrering
`0001_create_weight_logs` er uendret; ingen ny migrering eller database-reset kreves.

`DATABASE_REQUIRED=true` er satt i eksempelkonfigurasjonen og Compose. Da kreves
`DATABASE_URL` ved oppstart, og `/readyz` kontrollerer databasen. `/healthz` og `/`
gjør aldri databasekall. Uten eksplisitt konfigurasjon er databasen valgfri, som i
templaten; den modusen er kun nyttig for isolerte tester og metadata/helse.

Alle svar får `X-Request-ID` og sikkerhetsheadere. Driftsfeil bruker
`{"detail":"...","request_id":"..."}`. For kompatibilitet beholder
`/weight-logs` sine eksisterende feilformater: 404/409 har kun `detail`, og 422
har FastAPIs detaljerte valideringsliste. OpenAPI dokumenterer fortsatt dette.
Ruter er ikke flyttet til `/api/v1`; eksisterende frontend og proxy virker uendret.

Strukturerte logger beholder exception-type og kildelokasjoner, men skjuler
exception-meldinger og databaseparametre. Ikke logg måledata eller credentials.
Dette gir mindre feilsøkingsinformasjon, med hensikt å beskytte persondata.

Sett `ENVIRONMENT=production` og eksplisitte `ALLOWED_HOSTS` ved produksjonskjøring.
Dokumentasjon er da deaktivert med mindre `DOCS_ENABLED=true` er valgt. Dockerens
helseprobe bruker en tillatt Host-header. Compose bruker `/readyz` for avhengigheter.
Databasepool, tilkoblings-, spørrings-, låse- og transaksjonstimeouts kan justeres
via variablene i `.env.example`. Same-origin-proxyen trenger normalt ikke CORS.

CI installerer låste avhengigheter, kjører Ruff, streng Pyright og alle tester med
PostgreSQL, bygger Docker-image og tester containeren med produksjonsverter og
påkrevd database. Den publiserer eller deployer ingenting.
