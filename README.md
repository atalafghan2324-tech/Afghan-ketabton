# PDF Library Sharing API

FastAPI + SQLite backend for sharing and downloading PDF books.

## Install

```bash
python -m venv .venv
# Linux/macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configure secret

Set `SECRET_KEY` to a unique random string (at least 32 characters). Example:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Linux/macOS:

```bash
export SECRET_KEY='paste-generated-secret-here'
```

Windows PowerShell:

```powershell
$env:SECRET_KEY='paste-generated-secret-here'
```

Run:

```bash
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs and use **Authorize** with the token returned from `/auth/login`.

## Routes

| Method | Route | Purpose |
|---|---|---|
| POST | /auth/register | Create account |
| POST | /auth/login | Obtain JWT |
| GET | /auth/me | Current account |
| POST | /books | Upload PDF (multipart form) |
| GET | /books | List/search/filter |
| GET | /books/mine | My uploads |
| GET | /books/{id} | Details |
| GET | /books/{id}/download | Download PDF |
| GET | /books/{id}/read | Read PDF in browser |
| PATCH | /books/{id} | Update metadata (owner/admin) |
| DELETE | /books/{id} | Delete (owner/admin) |
| GET | /favorites | Favorite books |
| POST | /books/{id}/favorite | Favorite book |
| DELETE | /books/{id}/favorite | Unfavorite |
| GET | /admin/stats | Admin statistics |

## Upload

`POST /books` requires Bearer authentication and multipart fields `title`, `author`, `category`, optional `description`, `pdf` and optional `cover`.
PDF max 25 MB; cover max 5 MB (JPEG, PNG, WEBP). PDFs are checked for a PDF header; for production, add malware scanning, deeper document validation, rate limits, email verification and moderation.

## Notes

- All uploaded books are publicly readable and downloadable. Only upload documents you have rights to share.
- Only book owners or admins can update/delete a book.
- New accounts are always regular users. To appoint an admin, update their role securely through database administration; do not expose a public role-change endpoint.
- `/covers/...` is public. Prepend your API origin to the relative `cover_url` in frontend code.
- Uploaded files are stored on local disk. On ephemeral hosting (e.g. standard Render filesystem), use persistent object storage or a persistent disk, and move SQLite to managed PostgreSQL for production.
- CORS_ORIGINS must include your actual frontend origin.
- The download counter counts requests, not confirmed completed downloads.
