# QSLite

Quotation Studio Lite — multi-input → AI-priced South African construction quotation, exporting to your own ATESS-style PDF + Excel template.

Drop photos, drawings, PDFs, foreman site-survey files, or just speak the scope — the app runs vision + the SA rate catalogue + SA building codes through Claude, produces a clean line-item quote in your existing 20-year template, and saves it organised by project & client.

Built for **Ndlovu T Projects (Pty) Ltd** but the codebase is generic — swap the logo, header defaults, rate catalogue, and you have a quoting engine for any small/mid SA contractor.

## What it does

- **One input channel** — drop photos / drawings / scanned plans / PDFs / .xlsx site surveys (one or many). The AI decides what to do — single take-off, drawing comparison (delta BOQ), or asks for clarification when stuck.
- **Voice everywhere** — context dictation (en-ZA), and verbal edits before issue ("drop carpenter rate by 10%, add a labourer day, change RE…") that the AI applies as structured edits with diff preview.
- **SA-localised** — SANS 10142 / 10254 / 10400 / NHBRC compliance line items added automatically when scope triggers them. Rate catalogue with public-source SA rates as a starting baseline.
- **Self-improving catalog** — every issued line item joins the learned-items library, sub-categorised by trade. Median rates stabilise as you issue more quotes.
- **Pickers, not retyping** — clients and projects are dropdowns + "+ Add new" inline forms; both required before issue.
- **Past quotes** — search by client / project / labels; load any past quote as a draft or a linked variation.
- **Rate review for Robert** (or whichever human signs off rates) — one-click export of every rate with empty "Robert says" + Notes columns; he sends it back, you re-import.
- **iOS-installable PWA** — Add-to-Home-Screen on iPhone/iPad gives a fullscreen branded app icon.

## Architecture

- **Frontend**: Streamlit
- **Vision + LLM**: Anthropic Claude Sonnet 4.5 (extraction) + Haiku 4.5 (voice-edit parsing, auto-rates)
- **PDF**: ReportLab
- **Excel**: openpyxl
- **OCR / image normalisation**: Pillow
- **PDF rasterisation**: pypdfium2
- **STT**: streamlit-mic-recorder (Web Speech API, free)
- **Clipboard paste**: streamlit-paste-button
- **Memory**: local SQLite (clients, projects, issued quotes, learned items, rate edits)

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env       # then paste your Anthropic API key into .env
streamlit run app.py
```

Open `http://localhost:8501`.

## Deploy on Streamlit Community Cloud

1. Fork or clone this repo onto your GitHub.
2. Go to https://share.streamlit.io and sign in with GitHub.
3. **New app** → pick this repo → branch `main` → main file `app.py`.
4. **Advanced settings → Secrets** — paste:

   ```toml
   ANTHROPIC_API_KEY = "sk-ant-api03-…"
   ```

5. Deploy. App lives at `https://<your-app-name>.streamlit.app`.

> Note: Streamlit Community Cloud's filesystem is **ephemeral**. The local SQLite memory (clients, projects, learned items, audit trail) **resets on each redeploy / cold start**. For production with persistent state, deploy on Render / Fly / Railway with a mounted disk, or migrate the SQLite to a hosted Postgres.

## Folder structure (work folder)

When you set a *Work folder* in the sidebar (e.g. `E:\NdlovuQS\` on Windows, or any synced OneDrive / Google Drive folder), issued quotes auto-save like:

```
{work_folder}/
├── inbox/                  ← drop input files here, click "Process inbox"
├── projects/
│   └── {Project Name}/
│       └── quotes/
│           └── {Quote No.}/
│               ├── {Quote No.} — {Client}.pdf
│               ├── {Quote No.} — {Client}.xlsx
│               └── {Quote No.} — {Client}.json
├── reviews/                ← rate-review xlsx for human sign-off
└── surveys/                ← foreman site-survey templates / filled-ins
```

## Key modules

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI (single file — tabs: Quote builder, Past quotes, Clients & Projects, Rate review queue, Audit log) |
| `extract.py` | Vision + extraction, the "decide what to do" prompt + tools |
| `pdf_render.py` | ATESS-style PDF generator |
| `excel.py` | ATESS-style Excel generator |
| `quote.py` | LineItem assembly, totals, freeze, soft-lock |
| `memory.py` | SQLite tables + CRUD: clients, projects, learned items, issued quotes |
| `rates.py` + `data/rates.json` | Rate catalogue (50+ SA market rates with public-source citations) |
| `voice_edits.py` | Speak edits → Claude parses → structured ops → diff preview |
| `survey_template.py` | Foreman .xlsx template generator + parser |
| `building_codes.py` | SANS / NHBRC compliance reference sent to Claude |
| `validators.py` | Sanity ranges, two-source rule for high-value items |
| `learner.py` | Past-edit predictions, similar-job suggestions |

## License

MIT — adapt for your business.
