# Deploy Gym Overload 24/7 - free, no card

| Piece | Where | Cost |
|---|---|---|
| Database | Supabase (already in the cloud) | $0 |
| API + Telegram bot + reminders | **one** Render free web service (`server.py`) | $0, no card |
| Reminder timer + keep-awake | cron-job.org calls `/cron/tick` every 5 min | $0, no card |
| Website | Vercel Hobby | $0, no card |

How it works without paying:
- Render's free plan has **web services only** (no always-on workers) and **sleeps after 15 minutes
  with no traffic**. So the bot runs in **webhook mode** (Telegram *sends* your messages to
  `/telegram/webhook`) instead of polling, and reminders run when **cron-job.org** calls `/cron/tick`
  every 5 minutes - those calls also stop the service from sleeping.
- Render gives 750 free hours a month; one service running all month uses about 744. Run only this
  one free service.
- No app logic changed: `server.py` just puts `api.py` + the bot's handlers + `scheduler.tick` in one
  process. `bot.py` (polling) still works on your laptop.

Free plans change. If any page asks for a card or payment, **stop** - don't enter it.

---

## Step 0 - Make two secrets (on your PC)

Run this twice and save both results privately (Notes / password manager). Never share them.

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"
```

- First result = `TELEGRAM_WEBHOOK_SECRET`
- Second result = `CRON_SECRET`
- You also need `WEB_PASSWORD` (the website password you made earlier).

## Step 1 - Render: create the service

1. Go to <https://render.com> -> **Get started** -> sign up with **GitHub**.
2. Allow access to the repo `PhranavManjunaath/gym-overload` (choose "Only select repositories").
3. In the Render dashboard click **New -> Blueprint**, pick the `gym-overload` repo, branch `main`.
   Render reads `render.yaml` and shows one service: **gym-overload**, plan **Free**, region **Singapore**.
4. It asks for each secret value. Paste your own values:

   | Name | Value |
   |---|---|
   | `GROQ_API_KEY` | from your `.env` |
   | `TELEGRAM_BOT_TOKEN` | from your `.env` |
   | `TELEGRAM_CHAT_ID` | from your `.env` |
   | `DATABASE_URL` | from your `.env` (the Supabase link) |
   | `TELEGRAM_WEBHOOK_SECRET` | secret #1 from Step 0 |
   | `CRON_SECRET` | secret #2 from Step 0 |
   | `WEB_PASSWORD` | your website password |
   | `WEB_ORIGINS` | put `https://example.com` for now - you'll change it in Step 4 |

5. **Stop your local bot first** (Ctrl+C in the terminal running `python bot.py`), then click **Apply**.
6. Wait for the build (a few minutes). Your address looks like `https://gym-overload-xxxx.onrender.com`.

Check:
- `https://YOUR-RENDER-URL/api/health` -> `{"status":"ok"}`
- Logs show `Webhook set.` and `Database: postgresql` (not `sqlite`).
- Send `/help` to your bot in Telegram -> it answers. (After a sleep, the first reply can take ~1 minute.)

## Step 2 - cron-job.org: reminders + keep awake

1. Go to <https://cron-job.org> -> sign up (free, email).
2. **Create cronjob**:
   - Title: `gym-overload tick`
   - URL: `https://YOUR-RENDER-URL/cron/tick`
   - Schedule: **every 5 minutes**
   - **Advanced -> Headers -> add**: name `X-Cron-Key`, value = your `CRON_SECRET`
     (put the secret in the header, never in the URL - URLs end up in logs)
3. Save, then use **Test run**: the response should be `{"status":"ok","sent":0}` (or `"sent":1`
   if a reminder was due). `403` means the header name or value is wrong.

Reminders still follow your rules: max 2 messages a day, workout messages first.

## Step 3 - Vercel: the website

1. Go to <https://vercel.com> -> sign up with GitHub -> **Add New -> Project** -> import `gym-overload`.
2. **Root Directory**: click **Edit** -> choose `frontend`.
3. **Environment Variables**: `NEXT_PUBLIC_API_URL` = `https://YOUR-RENDER-URL` (no `/` at the end).
4. **Deploy**. Copy your site address, e.g. `https://gym-overload.vercel.app`.

## Step 4 - Connect website and API

1. Render -> your service -> **Environment** -> set `WEB_ORIGINS` to your exact Vercel address
   (e.g. `https://gym-overload.vercel.app`, no `/` at the end) -> **Save** (it redeploys).
2. Open the Vercel site -> log in with `WEB_PASSWORD` -> the dashboard loads your data.

---

## Checklist

- [ ] `/api/health` returns `{"status":"ok"}`
- [ ] Render logs: `Webhook set.` and `Database: postgresql`
- [ ] Telegram `/help` answers; `bench 60x10,10,9` (an exercise you added) logs and replies
- [ ] cron-job.org test run returns `{"status":"ok", ...}` and runs every 5 minutes
- [ ] Website login works, no CORS error
- [ ] Local `python bot.py` is stopped
- [ ] No card was added anywhere; GitHub has no `.env`

## Good to know

- **Running the bot on your laptop again** (`python bot.py`) switches Telegram back to polling and
  removes the webhook - the cloud bot stops hearing you. To go back to the cloud: stop the local bot,
  then Render -> **Manual Deploy -> Restart service** (it re-registers the webhook on startup).
- **First reply slow?** The free service was asleep; cron-job.org every 5 minutes keeps that rare.
- **Free bandwidth / build minutes:** if you hit the monthly limit without a card, Render pauses free
  services until next month. A personal bot uses very little.
- **Memory:** about 105 MB to start (measured); the free plan has 512 MB.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Asks for a card | Stop; don't add it. |
| Bot doesn't answer | Logs must show `Webhook set.`; `TELEGRAM_WEBHOOK_SECRET` only letters, digits, `_`, `-`; local bot stopped; restart the service |
| `403` from `/cron/tick` | Header must be `X-Cron-Key` with exactly your `CRON_SECRET` |
| Logs show `Database: sqlite` | `DATABASE_URL` missing/wrong - fix it and redeploy |
| Website network/CORS error | `WEB_ORIGINS` must exactly match the Vercel address (https, no trailing `/`) |
| Build fails on Python version | `PYTHON_VERSION` is set to 3.11.9 in `render.yaml` |
| Service suspended | Free hours/bandwidth used up for the month - wait for reset, don't upgrade |

## Paid alternative (card needed)

`Procfile` (web = API, worker = polling bot) works on hosts with always-on workers, e.g.
Northflank's Sandbox plan (free but asks for a card to verify) or Railway (paid).
