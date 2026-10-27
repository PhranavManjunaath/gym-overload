# Deploy Gym Overload 24/7 for $0

This guide puts the three pieces online without a paid plan:

| Piece | What it is | Where it runs | Cost |
|---|---|---|---|
| Database | Supabase Postgres | Supabase (already cloud) | $0 on the existing/free plan |
| API | `api.py` FastAPI | Northflank combined service (HTTPS) | $0, Sandbox plan |
| Bot | `bot.py` Telegram long polling + reminders | Northflank combined service (no public URL) | $0, Sandbox plan |
| Website | `frontend/` Next.js 16 | Vercel Hobby | $0 |

`dashboard.py` (Streamlit) is optional and is **not** deployed.

No app logic, formulas, tests or features were changed for deployment. The only
new deployment files are `Procfile`, `.python-version`, `runtime.txt` and this guide.

---

## Money check first

The recommended stack is:

| Service | Plan | Price | Why it fits |
|---|---|---|---|
| Northflank | Sandbox | $0 | 2 services, always on, no sleeping, up to $20/month of resources |
| Vercel | Hobby | $0 | Personal, non-commercial Next.js hosting |
| Supabase | Free | $0 | Your existing database |
| Groq / Telegram | Free tier | $0 | Existing API and bot |

Northflank's pricing page says the **Sandbox** plan is free and **"No card needed"**.
If signup asks for a card, **stop and do not enter payment details**. Tell the person
helping you. Do not upgrade to Pay as you go.

- Pricing: [Northflank](https://northflank.com/pricing), [Vercel](https://vercel.com/pricing), [Supabase](https://supabase.com/pricing).
- Free limits can change. Stay on the free plans; if a screen says you exceeded a
  limit, stop rather than upgrading.
- The bot cannot use a sleeping free web service. Northflank Sandbox is always on,
  which is why it is used here.

---

## Before you start

1. Push the deploy files to GitHub so Northflank can see them:

   ```powershell
   git status
   git add Procfile .python-version runtime.txt DEPLOY.md .gitignore
   git commit -m "Add zero-cost Northflank deployment config"
   git push
   ```

   Do not add `.env`.

2. Keep your local `.env` open in a private window. You will copy your own values into
   the Northflank dashboards. Never paste those values into GitHub, chat, screenshots
   or this guide.

3. Generate a long random `WEB_PASSWORD` (64 characters here) and save it in a password
   manager:

   ```powershell
   .\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

4. Know which local file has your values: `.env` (it is git-ignored).

5. **Stop your local bot right before the cloud bot starts** - in the terminal running
   `python bot.py`, press `Ctrl+C`. Telegram allows only one poller per bot token. If
   the local bot and the cloud bot poll at the same time, the logs show
   `409 Conflict` and messages/replies become unreliable.

6. Never commit `.env`. If a secret is ever exposed, rotate it (new Telegram token from
   @BotFather, new Groq key, new Supabase password, new `WEB_PASSWORD`) and update the
   hosting dashboards.

---

## Environment variables (names only)

Set these in Northflank. Values are yours; the host stores them encrypted, not in Git.

### Both the API and the bot service

| Variable | Required? | Notes |
|---|---|---|
| `GROQ_API_KEY` | Yes | From your local `.env` |
| `GROQ_MODEL` | Optional | Defaults to `openai/gpt-oss-120b` |
| `TELEGRAM_BOT_TOKEN` | Yes | Never log or share this |
| `TELEGRAM_CHAT_ID` | Yes | The numeric chat id |
| `DATABASE_URL` | Yes | Supabase Postgres URI. If missing, the app falls back to SQLite inside the container and data disappears on redeploy |
| `REMINDER_TIMEZONE` | Yes | Example: `Asia/Kolkata` |
| `WORKOUT_DAYS` | Optional | Example: `mon,wed,fri` |
| `WORKOUT_REMINDER_TIME` | Optional | Example: `07:00` |
| `MISSED_WORKOUT_CHECK_TIME` | Optional | Example: `21:00` |
| `WEEKLY_REPORT_TIME` | Optional | Example: `19:00` |
| `MEAL_REMINDER_TIMES` | Optional | Example: `08:00,13:00,20:00` |

### API service only

| Variable | Required? | Notes |
|---|---|---|
| `WEB_PASSWORD` | **Yes, before making the API public** | One long random shared password. This is a single-user password, **not** multi-user accounts |
| `WEB_ORIGINS` | **Yes, before the website can call the API** | Exactly your Vercel URL, e.g. `https://your-app.vercel.app` (no trailing slash). Comma-separate extra origins |

`NEXT_PUBLIC_API_URL` is the only website variable (set on Vercel). It is public, not a
secret.

---

## Northflank: API + bot (two services, one repo)

Northflank builds both services from the same GitHub repo. The `Procfile` defines the
two commands:

```text
web: uvicorn api:create_app --factory --host 0.0.0.0 --port 8000
worker: python bot.py
```

The API uses the `web` process. The bot uses the `worker` process. The bot must have
**no public port** and **one instance**.

### 1. Create the free project

1. Go to <https://app.northflank.com/signup> and create an account with GitHub.
2. Choose the **Sandbox** plan (free). Do not upgrade.
3. Create a project named `gym-overload`. Pick the region closest to you.
4. Link your GitHub account when prompted and allow access to
   `PhranavManjunaath/gym-overload`.

### 2. Create the API service

1. In the project, click **Create service -> Combined service**.
2. Name it `gym-overload-api`.
3. **Repository**: choose `PhranavManjunaath/gym-overload`, branch `main`.
4. **Build options**: choose **Buildpack**.
   - Builder: `heroku/builder:24` (default is fine).
   - Build context: `/` (repo root, not `frontend`).
5. **Runtime mode**: **Default process** (`web`).
6. **Networking**: add a port:
   - Port: `8000`
   - Protocol: `HTTP`
   - Accessibility: **Public**
   - Name: `api`
   - If Northflank auto-added another port, delete it so only `8000` remains.
7. **Resources**: choose the smallest allowed plan (for example `0.1 vCPU / 256 MB`)
   and **1 instance**.
8. **Environment variables**: add every variable from "Both the API and the bot
   service", plus `WEB_PASSWORD` and `WEB_ORIGINS`.
   - `WEB_ORIGINS` can be set later, after Vercel gives you the website URL.
   - Use your own `.env` values. Never paste them into chat or screenshots.
9. **Health checks** (Advanced): add:
   - Liveness: HTTP, port `8000`, path `/api/health`
   - Readiness: HTTP, port `8000`, path `/api/health`
   - Initial delay `10s`, interval `30s`, timeout `5s`, failures `3`
10. Click **Create service**. The first build starts automatically.

**Set `WEB_PASSWORD` before creating the public port.** Without it, anyone who finds
the API URL can read and change your workouts.

### 3. Get the API URL and check it

1. Open the `gym-overload-api` service.
2. Copy the public URL from the service header or **Networking** (it looks like
   `https://api--gym-overload-api--xxxx.code.run`).
3. Wait for the build and deployment to finish.
4. Open this in a browser:

   ```text
   https://YOUR-API-URL/api/health
   ```

   It must return:

   ```json
   {"status":"ok"}
   ```

5. Also check:

   ```text
   https://YOUR-API-URL/api/auth
   ```

   It must return `{"status":"ok","password_required":true}`.

If the health check fails, see **Troubleshooting** before changing anything.

### 4. Create the bot service

1. In the same project, click **Create service -> Combined service**.
2. Name it `gym-overload-bot`.
3. **Repository**: same repo, branch `main`.
4. **Build options**: **Buildpack**, same builder, build context `/`.
5. **Runtime mode**: **Custom process** and select `worker`.
   - If `worker` is not in the list, the `Procfile` was not pushed to GitHub.
6. **Networking**: add **no ports**. Delete any auto-added public port. The bot uses
   long polling and needs no inbound traffic.
7. **Resources**: smallest allowed plan, exactly **1 instance**. Never scale the bot.
8. **Advanced -> Pod rollout strategy**: choose **Recreate** if it is shown.
   - Rolling deploys can briefly run the old and new bot together. Two pollers with
     the same token fight over Telegram updates.
   - If **Recreate** is not shown, pause the bot service before every redeploy, then
     resume it after the new deployment is running.
9. **Environment variables**: add only the "Both the API and the bot service" variables.
   Do **not** add `WEB_PASSWORD` or `WEB_ORIGINS` here.
10. **Stop your local bot first** (`Ctrl+C`), then click **Create service**.

### 5. Check the bot logs

Open `gym-overload-bot -> Logs`. Good signs:

```text
Database: postgresql ...
Bot online. ...
```

- `Database: sqlite` means `DATABASE_URL` is missing or wrong. Fix it and restart the
  service; otherwise cloud data will vanish.
- `409 Conflict` / `terminated by other getUpdates request` means another poller exists:
  your local bot is still running, a second bot service/replica exists, or a rolling
  deploy left the old container alive. Stop the extra one. Do not create a new Telegram
  token to "fix" this.
- Do not paste full logs publicly if they contain anything private. The app keeps
  `httpx` quiet so Telegram URLs with the token are not logged; leave that code alone.

---

## Vercel: website

1. Go to <https://vercel.com> and sign in with GitHub.
2. Click **Add New -> Project**.
3. Import `PhranavManjunaath/gym-overload`.
4. Before deploying, open **Root Directory -> Edit** and choose `frontend`.
   - Framework should be detected as **Next.js**.
   - Leave the build command and install command at their defaults.
5. Add an Environment Variable:
   - Name: `NEXT_PUBLIC_API_URL`
   - Value: your Northflank API URL, e.g. `https://api--gym-overload-api--xxxx.code.run`
   - Environment: Production (add Preview too only if you want preview builds to work).
6. Click **Deploy**.
7. Copy the production website URL, e.g. `https://gym-overload.vercel.app`.
8. `NEXT_PUBLIC_*` values are baked in at build time. If you change the API URL later,
   change the variable and click **Deployments -> Redeploy**.

### Connect the API to the website (CORS)

1. Go back to Northflank -> `gym-overload-api` -> **Environment**.
2. Set `WEB_ORIGINS` to the exact Vercel production origin, no trailing slash:

   ```text
   https://gym-overload.vercel.app
   ```

   If you use a custom domain too, comma-separate the origins with no spaces.
3. Save the variable and restart the API service if Northflank does not redeploy it
   automatically.
4. Open the website. If it asks for a password, enter the `WEB_PASSWORD` you generated.
   This is one shared password, not user accounts.

A CORS error in the browser (DevTools -> Console/Network) usually means `WEB_ORIGINS`
does not exactly match the address bar: check `https`, the domain, and that there is no
trailing `/`.

`WEB_ORIGINS` is a browser rule, not the lock. The real lock is `WEB_PASSWORD`: anyone
with the password and `curl` can call the API regardless of CORS. Keep the password
private. The API docs at `/api/docs` and the health/auth routes are public by design;
every route that reads or changes your data requires the password.

---

## Verification checklist

Do these in order after both Northflank services and Vercel finish deploying:

- [ ] `https://YOUR-API-URL/api/health` returns `{"status":"ok"}`.
- [ ] `https://YOUR-API-URL/api/auth` returns `{"status":"ok","password_required":true}`.
- [ ] The website opens; the login screen appears; the shared `WEB_PASSWORD` works.
- [ ] After login, the dashboard loads data from Supabase (exercises/history you already
      have). No CORS error in the browser console.
- [ ] Telegram: send `/help` to your bot. It replies with the command list.
- [ ] Telegram: send `/next bench` (or another exercise you have). The numbers match
      your data.
- [ ] Bot logs show `Bot online.` and `Database: postgresql` (not `sqlite`).
- [ ] The bot service is on 1 instance and has no public port.
- [ ] Your local `python bot.py` is stopped, no second bot service exists, and no
      preview environment is running the same bot token.
- [ ] Telegram `/reminders` shows your timezone (e.g. `Asia/Kolkata`).
- [ ] Optional live reminder test: change `MEAL_REMINDER_TIMES` on the bot service to
      two minutes from now, restart it, wait for the message, then put the original
      value back. Do not leave test values in place. Maximum 2 proactive messages/day.
- [ ] GitHub repo does not contain `.env` (only `.env.example`).
- [ ] Website and API both use HTTPS (Northflank and Vercel do this automatically).
- [ ] Northflank still shows the **Sandbox** plan and no payment method was added.

---

## Updating the app later

```powershell
git add .
git commit -m "Describe the change"
git push
```

- Northflank rebuilds and redeploys both Python services on push.
- Vercel redeploys the website on push.
- Keep your local bot stopped after the cloud bot is live. If you need to run it
  locally for debugging, stop the Northflank bot service first.
- For bot updates, use **Recreate** (or pause the bot before the deploy). If the logs
  show a Telegram conflict, wait for the old container to stop; do not start a second
  service.

---

## Troubleshooting

| Symptom | Likely fix |
|---|---|
| Northflank asks for a card | The Sandbox plan should not need one. Stop; do not add payment details. Tell the person helping you |
| Build fails with no process/command | Check `Procfile` is pushed and the service uses the `web` process (API) or `worker` process (bot) |
| API deploy fails health check | Port must be `8000`, public, HTTP; path must be `/api/health`; the `web` command must bind `0.0.0.0`; check build logs for a Python error |
| Website says network/CORS error | `WEB_ORIGINS` must exactly match the Vercel origin, including `https://` and no trailing `/`; restart the API |
| Website shows "Wrong password" | Re-enter the current `WEB_PASSWORD`; if you changed it, log in again |
| API returns 401 | Set the `X-App-Password` header/website login. The browser stores the password; clear it by logging in again |
| Bot logs `409 Conflict` | Stop the local bot, remove extra bot replicas/services, set rollout to `Recreate` or pause before deploy; keep one poller |
| Bot logs `Database: sqlite` | Add/fix `DATABASE_URL` on that service and restart |
| Bot has no logs | Runtime mode must be **Custom process -> worker**; resources must be at least the smallest plan; check build logs |
| Reminders never arrive | Bot must be always on, 1 instance; check `REMINDER_TIMEZONE`; check `/reminders`; max 2/day |
| Build uses the wrong Python | `.python-version` and `runtime.txt` pin 3.11. Use the `heroku/builder:24` builder and check the build log for the selected Python version |
| Service restarts, logs show `Killed` / `OOMKilled` / exit code 137 | Out of memory. Each process uses about 105 MB just to start (measured), more while the AI answers. Pick the next memory size up (512 MB) if your free plan allows it |
| Free resource limit warning | Do not upgrade. Stop extra services/instances; the two small services should fit in the $20/month Sandbox allowance |

Rollback: Northflank -> service -> **Builds/Deployments** -> choose an older successful
build -> **Deploy**. Vercel -> project -> **Deployments** -> a previous deployment ->
**Promote/Rollback**.

---

## What is safe to commit

- Commit: `Procfile`, `.python-version`, `runtime.txt`, `DEPLOY.md`, `.gitignore`,
  `.env.example` (placeholders only).
- Never commit: `.env`, real keys, the real `DATABASE_URL`, `WEB_PASSWORD`, Telegram
  tokens, Northflank/Vercel tokens, or screenshots showing those values.
- `.env.example` lists the variable names with fake values; that is the only env file
  that belongs in Git.
