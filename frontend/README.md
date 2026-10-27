# Gym Overload — website

Next.js 16 + Tailwind CSS 4 + Lucide + Recharts. Talks to the Python API (`../api.py`),
which is the only source of numbers. This frontend never calculates weights, reps or e1RM.

```bash
# 1. API (from the project root)
uvicorn api:create_app --factory --host 127.0.0.1 --port 8000

# 2. Website (from this folder)
npm install
npm run dev          # http://localhost:3000
```

- API address: `NEXT_PUBLIC_API_URL` (default `http://127.0.0.1:8000`). Not a secret.
- The API only accepts requests from the origins in `WEB_ORIGINS` (default localhost:3000).
- Design tokens live in `src/app/globals.css` (`@theme`); UI building blocks in `src/components/ui`.
- Pages: `src/app/*/page.tsx` → views in `src/views`.

Checks: `npx tsc --noEmit`, `npm run lint`, `npm run build`.
