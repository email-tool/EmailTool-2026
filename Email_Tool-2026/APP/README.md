# EmailTool-2026 — Project README

> **Documentation basis:** this guide describes the source tree in the supplied `EmailTool-2026-feature-email-tool-2026-clean.zip`. It distinguishes the launcher-selected files from similarly named legacy/backup files. It does not assume that untracked files on the developer's machine are present in this archive.

## 1. What this project contains

EmailTool-2026 is a multi-part application with three independently started web services:

| Service | Entry point selected by `run_all.py` | Port | Main responsibility |
|---|---|---:|---|
| Django dashboard | `email-generator/manage.py runserver 0.0.0.0:8000` | 8000 | Sheet upload, missing-data review, work assignment and row editing |
| Flask Old Tool | `APP/tool_old.py` | 4000 | Legacy email-tool interface and its API routes |
| Flask New Tool | `APP/new_tool.py` | 3000 | Current Flask interface, database training, email generation, verification and automatic discovery |

The launcher is `run_all.py` at the repository root. It installs dependencies from `email-generator/requirements.txt` if that file exists, starts all three processes, waits for Enter, and terminates them.

**Archive discrepancy:** `run_all.py` refers to `email-generator/requirements.txt`, but that requirements file is not present in the supplied ZIP. The Django folder does contain a Dockerfile and Compose file, but the ZIP does not provide the launcher dependency manifest. Confirm the real working copy has this file before relying on automatic installation.

## 2. Start-up

From the `Email_Tool-2026` directory:

```powershell
python run_all.py
```

The script uses the same Python interpreter that launched `run_all.py` (`sys.executable`) for all child processes. It launches:

```text
python manage.py runserver 0.0.0.0:8000   # cwd: email-generator
python tool_old.py                         # cwd: APP; serves port 4000
python new_tool.py                         # cwd: APP; serves port 3000
```

Press Enter in the launcher terminal to request shutdown. The checked-in launcher does not currently perform health checks or wait for child processes after termination. Django/Flask development servers are for development, not production deployment.

## 3. Main user workflows

### A. Train the company email-pattern database (New Tool and Tool Old)

1. Browser sends a file or folder upload to Flask `/train-database`.
2. `APP/tool_old.py` or `APP/new_tool.py` receives the request. Both import `process_single_file` and `process_folder` from `database_training.db_pipeline`.
3. `db_pipeline.read_file()` reads and normalizes the input columns using `column_map.json`.
4. `extract_patterns()` compares each email local-part against templates from `patterns.json` and groups the identified pattern by company.
5. `process_single_file()` writes a dated `*_output.csv` and calls `update_pickle()`.
6. `update_pickle()` merges company/pattern values into the selected pickle database.

The two Flask applications are configured with separate output/database paths in their respective source files. Inspect those constants before moving files or changing working directories.

### B. Generate email addresses

1. Browser sends a file to Flask `/email`.
2. Route function `create_email()` in the selected Flask app calls `email_creation.create_emails.email_creator_app()`.
3. `email_creator_app()` reads/normalizes the input via `email_creation.reader_email.reader()` and uses the supplied email-pattern database to create candidate email addresses.
4. The route returns/downloads the generated result according to its implementation.

### C. Verify emails

1. Browser sends a file to `/emailverify`.
2. Flask route `verify_email()` calls `email_verifier.email_verifier.verify_app()`.
3. `verify_app()` loads the file and calls ZeroBounce validation through `get_email_status()`.

This workflow requires a valid ZeroBounce API key and network access. Review the current implementation before processing a full file: `get_verified_data()` currently slices the DataFrame to its first two rows (`processed_data[:2]`).

### D. Automatic email discovery

1. Browser sends a file to `/automatic-email`.
2. Flask route `automatic_email()` calls `automatic_email_format.automatic_email_runner.run_automatic_email()`.
3. The runner queries Serper, parses search snippets, extracts email candidates, compares company/domain similarity, selects a candidate, and emits progress through Socket.IO.
4. Supporting modules include `serper_email_module.py`, `process_scrapped_data.py`, `scarpper_manager.py`, `get_best_email.py`, and `web_email_scrapper_multiEngine.py`.

Some of these modules are alternative/older scraping pipelines and are not all imported by the active runner. See `ARCHITECTURE.md` for each module's actual callable inventory.

### E. Django sheet and missing-data workflow

1. `email-generator/email_generator/urls.py` includes `dashboard.urls` at `/`.
2. `dashboard/urls.py` maps routes to `dashboard/views.py`.
3. Views use models in `dashboard/models.py` for uploaded sheets, missing-data files and work assignments.
4. Templates in `dashboard/templates/` render login, home, upload, and missing-data screens.

## 4. Directory guide

```text
Email_Tool-2026/
├── run_all.py                  # starts Django + both Flask services
├── APP/
│   ├── tool_old.py             # Old Tool Flask service used by launcher
│   ├── new_tool.py             # New Tool Flask service used by launcher
│   ├── old_tool.py             # older/alternate Flask implementation; NOT launcher target
│   ├── new_tool copy 2.py      # snapshot/backup; NOT launcher target
│   ├── database_training/     # file ingestion, pattern extraction, pickle updates
│   ├── email_creation/        # candidate email construction
│   ├── email_verifier/        # ZeroBounce verification integration
│   ├── automatic_email_format/ # web/Serper discovery and scraping pipelines
│   ├── helper/                # shared CSV/Excel loader
│   ├── templates/              # Flask HTML templates
│   └── static/                 # Flask CSS
└── email-generator/             # Django project and dashboard app
```

## 5. Configuration and data files

| File | Purpose |
|---|---|
| `APP/database_training/patterns.json` | Email local-part templates, aliases and invalid templates used by `db_pipeline.py` |
| `APP/database_training/column_map.json` | Accepted source-column labels mapped to canonical company/name/email fields |
| `email-generator/email_generator/settings.py` | Django settings, SQLite path, installed apps, media/static configuration and timezone |
| `email-generator/db.sqlite3` | Checked-in SQLite database snapshot; contains Django application data |
| `APP/static/style.css` | Flask UI stylesheet |
| `APP/templates/*.html` | Flask dashboard variants and backups; active template selection is in Flask `render_template()` calls |
| `email-generator/dashboard/templates/*.html` | Django templates |
| `APP/automatic_email_format/*.ipynb` | Research/experimentation notebooks; not launched by `run_all.py` |
| `APP/database_training/*.ipynb` | Database-training exploration notebooks; not launched by `run_all.py` |

## 6. Important operational notes

- **Do not assume `old_tool.py` is the Old Tool that runs.** `run_all.py` explicitly launches `tool_old.py`.
- **Do not assume `new_tool copy 2.py` is active.** The launcher runs `new_tool.py`.
- The ZIP includes historical/backup notebooks and duplicate implementations. Treat them as reference material unless a route/import explicitly uses them.
- The current Flask services use development settings in their entry points. Do not expose the debug server to the public internet.
- The Django settings in this archive have `DEBUG = True` and a literal `SECRET_KEY`; production deployment must use environment-provided secrets and `DEBUG = False`.
- `email_verifier.py` sends validation requests to ZeroBounce. Protect API keys and handle rate limits/timeouts before large-scale use.
- Pickle files can execute code when unpickled. Only load PKL files from trusted sources.
- The file `email-generator/requirements.txt` is missing from this ZIP even though the launcher references it. Create/restore a pinned dependency file before reproducible setup.

## 7. Detailed reference

See [`ARCHITECTURE.md`](ARCHITECTURE.md) for:

- each Python file and its responsibility;
- every top-level function/class found by source inspection;
- which route/module calls it (where traceable from imports and call sites);
- the data flow between services;
- templates, notebooks, JSON configuration and Django models;
- known gaps where the source does not establish a caller.

## 8. Scope and accuracy

This documentation is a source-code map, not a guarantee that every feature is currently operational. Function descriptions are derived from the implementation and call relationships visible in the supplied archive. Where a helper has no direct in-project caller, it is marked as a standalone/legacy helper rather than inventing a caller. Runtime behavior still needs integration testing with the real environment, API credentials, uploads and PKL databases.
