# api

Webhook-only FastAPI service. Runs on port 80, behind Traefik. Handles GitHub App callback/webhook and Stripe webhook. Imports business logic directly from `sdk/` packages.

## Responsibility

- GitHub App installation callback (`/github/callback`)
- GitHub App webhook (`/github/webhook`) — ingests repos, triggers indexing
- Stripe webhook (`/stripe/webhook`)
- Health check (`/health`)

## Directory layout

```
src/api/
├── main.py       FastAPI app with lifespan (sets event loop, shuts down indexer scheduler)
├── auth/
│   └── dependencies.py  JWT validation, GitHub install gate
├── db/
│   ├── users.py          UserDB — user profile access
│   ├── github_users.py   GithubUserDB
│   ├── invoices.py       invoice records
│   └── subscription_plans.py
├── github/
│   └── integration.py   GitHub App integration helpers
├── routes/
│   ├── github.py    /github/callback + /github/webhook
│   ├── stripe.py    /stripe/webhook
│   └── health.py    /health
├── stripe/
│   ├── client.py    Stripe SDK client
│   └── service.py   subscription management
└── users/
    └── service.py   user management helpers
```

## Import pattern

All imports use flat package paths relative to `src/` (the WORKDIR):

```python
from lib.github.client import installation_token_for_id
from api.db.users import UserDB
from sdk.indexer import IndexingScheduler
from sdk.workspace import Workspace
from lib.async_utils import set_main_event_loop
from api.stripe.client import get_stripe_client
```

`IndexingScheduler` is constructed in `main.py` lifespan and stored on `app.state.scheduler`. Webhook handlers access it via `request.app.state.scheduler.trigger(...)`.

## Running locally

```bash
docker compose up -d --build api
```
