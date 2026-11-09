
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
import os

from fastapi import (
    FastAPI, Depends, HTTPException,
    UploadFile, File, Form, Query
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, or_, func
from sqlalchemy.orm import Session

from database import Base, engine, get_db
from models import User, Book, Favorite
from schemas import (
    RegisterIn, LoginIn, UserOut,
    TokenOut, BookOut, BookUpdate
)
from auth import (
    hash_password, verify_password,
    create_token, current_user
)

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_FILE = BASE_DIR / "index.html"

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
PDF_DIR = UPLOAD_DIR / "pdfs"
COVER_DIR = UPLOAD_DIR / "covers"

PDF_DIR.mkdir(parents=True, exist_ok=True)
COVER_DIR.mkdir(parents=True, exist_ok=True)

MAX_PDF_BYTES = 25 * 1024 * 1024
MAX_COVER_BYTES = 5 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(
    title="Afghan Ketabton API",
    version="1.0.0",
    lifespan=lifespan
)

origins = [
    x.strip()
    for x in os.getenv(
        "CORS_ORIGINS",
        "http://localhost:5500,http://127.0.0.1:5500"
    ).split(",")
    if x.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"]
)

app.mount(
    "/covers",
    StaticFiles(directory=str(COVER_DIR)),
    name="covers"
)


# ==========================================
# FRONTEND AND FAVICON
# ==========================================

@app.get("/", include_in_schema=False)
def home():
    if FRONTEND_FILE.is_file():
        return FileResponse(
            FRONTEND_FILE,
            media_type="text/html"
        )

    return HTMLResponse(
        "<h2>Afghan Ketabton API is running</h2>"
        "<p>index.html not found.</p>"
        '<a href="/docs">API Documentation</a>'
    )


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return Response(status_code=204)


# ==========================================
# HELPERS
# ==========================================

def book_out(book: Book) -> BookOut:
    return BookOut.model_validate({
        "id": book.id,
        "title": book.title,
        "author": book.author,
        "description": book.description,
        "category": book.category,
        "cover_url": (
            f"/covers/{Path(book.cover_path).name}"
            if book.cover_path else None
        ),
        "file_size": book.file_size,
        "uploader_id": book.uploader_id,
        "downloads": book.downloads,
        "created_at": book.created_at
    })


async def save_validated(
    upload: UploadFile,
    folder: Path,
    max_bytes: int,
    kind: str
) -> tuple[str, int]:

    head = await upload.read(16)

    if kind == "pdf":
        if not head.startswith(b"%PDF-"):
            raise HTTPException(400, "Only valid PDF files allowed")
        ext = ".pdf"
    else:
        if head.startswith(b"\x89PNG\r\n\x1a\n"):
            ext = ".png"
        elif head.startswith(b"\xff\xd8\xff"):
            ext = ".jpg"
        elif head.startswith(b"RIFF") and head[8:12] == b"WEBP":
            ext = ".webp"
        else:
            raise HTTPException(
                400, "Cover must be PNG, JPEG or WEBP"
            )

    path = folder / f"{uuid4().hex}{ext}"
    size = 0

    try:
        with path.open("wb") as f:
            size = len(head)

            if size > max_bytes:
                raise HTTPException(413, "File too large")

            f.write(head)

            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)

                if size > max_bytes:
                    raise HTTPException(413, "File too large")

                f.write(chunk)

        if size == 0:
            raise HTTPException(400, "Empty file")

    except Exception:
        path.unlink(missing_ok=True)
        raise

    finally:
        await upload.close()

    return str(path), size


def get_book_or_404(book_id: int, db: Session):
    book = db.get(Book, book_id)

    if not book:
        raise HTTPException(404, "Book not found")

    return book


def ensure_owner(book: Book, user: User):
    if book.uploader_id != user.id and user.role != "admin":
        raise HTTPException(
            403, "You cannot modify this book"
        )


# ==========================================
# AUTHENTICATION
# ==========================================

@app.post(
    "/auth/register",
    response_model=UserOut,
    status_code=201
)
def register(
    data: RegisterIn,
    db: Session = Depends(get_db)
):
    email = str(data.email).lower()

    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "Email already registered")

    user = User(
        name=data.name.strip(),
        email=email,
        password_hash=hash_password(data.password),
        role="user"
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user


@app.post("/auth/login", response_model=TokenOut)
def login(
    data: LoginIn,
    db: Session = Depends(get_db)
):
    user = db.scalar(
        select(User).where(
            User.email == str(data.email).lower()
        )
    )

    if not user or not verify_password(
        data.password, user.password_hash
    ):
        raise HTTPException(
            401, "Incorrect email or password"
        )

    return TokenOut(
        access_token=create_token(user.id)
    )


@app.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


# ==========================================
# UPLOAD PDF BOOK
# ==========================================

@app.post(
    "/books",
    response_model=BookOut,
    status_code=201
)
async def upload_book(
    title: str = Form(min_length=1, max_length=250),
    author: str = Form(min_length=1, max_length=200),
    category: str = Form(min_length=1, max_length=100),
    description: str = Form(default="", max_length=5000),
    pdf: UploadFile = File(...),
    cover: UploadFile | None = File(default=None),
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    pdf_path, size = await save_validated(
        pdf, PDF_DIR, MAX_PDF_BYTES, "pdf"
    )

    cover_path = None

    try:
        if cover and cover.filename:
            cover_path, _ = await save_validated(
                cover, COVER_DIR, MAX_COVER_BYTES, "cover"
            )

        book = Book(
            title=title.strip(),
            author=author.strip(),
            category=category.strip(),
            description=description.strip(),
            pdf_path=pdf_path,
            cover_path=cover_path,
            file_size=size,
            uploader_id=user.id
        )

        db.add(book)
        db.commit()
        db.refresh(book)

        return book_out(book)

    except Exception:
        db.rollback()
        Path(pdf_path).unlink(missing_ok=True)

        if cover_path:
            Path(cover_path).unlink(missing_ok=True)

        raise


# ==========================================
# ALL BOOKS AND SEARCH
# ==========================================

@app.get("/books", response_model=list[BookOut])
def list_books(
    q: str | None = None,
    category: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    stmt = select(Book)

    if q:
        term = f"%{q}%"
        stmt = stmt.where(
            or_(
                Book.title.ilike(term),
                Book.author.ilike(term),
                Book.description.ilike(term)
            )
        )

    if category:
        stmt = stmt.where(
            Book.category.ilike(category)
        )

    books = db.scalars(
        stmt.order_by(
            Book.created_at.desc(),
            Book.id.desc()
        ).offset(skip).limit(limit)
    ).all()

    return [book_out(b) for b in books]


# ==========================================
# MY BOOKS
# ==========================================

@app.get("/books/mine", response_model=list[BookOut])
def my_books(
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    books = db.scalars(
        select(Book)
        .where(Book.uploader_id == user.id)
        .order_by(Book.id.desc())
    ).all()

    return [book_out(b) for b in books]


# ==========================================
# FAVORITES
# ==========================================

@app.get("/favorites", response_model=list[BookOut])
def favorites(
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    books = db.scalars(
        select(Book)
        .join(Favorite, Favorite.book_id == Book.id)
        .where(Favorite.user_id == user.id)
    ).all()

    return [book_out(b) for b in books]


# ==========================================
# BOOK DETAILS
# ==========================================

@app.get("/books/{book_id}", response_model=BookOut)
def book_details(
    book_id: int,
    db: Session = Depends(get_db)
):
    return book_out(get_book_or_404(book_id, db))


# ==========================================
# DOWNLOAD PDF
# ==========================================

@app.get("/books/{book_id}/download")
def download_book(
    book_id: int,
    db: Session = Depends(get_db)
):
    book = get_book_or_404(book_id, db)

    if not Path(book.pdf_path).is_file():
        raise HTTPException(
            404, "PDF file is unavailable"
        )

    book.downloads += 1
    db.commit()

    return FileResponse(
        book.pdf_path,
        media_type="application/pdf",
        filename=f"book-{book.id}.pdf"
    )


# ==========================================
# READ PDF ONLINE
# ==========================================

@app.get("/books/{book_id}/read")
def read_book(
    book_id: int,
    db: Session = Depends(get_db)
):
    book = get_book_or_404(book_id, db)

    if not Path(book.pdf_path).is_file():
        raise HTTPException(
            404, "PDF file is unavailable"
        )

    return FileResponse(
        book.pdf_path,
        media_type="application/pdf",
        content_disposition_type="inline"
    )


# ==========================================
# UPDATE BOOK
# ==========================================

@app.patch("/books/{book_id}", response_model=BookOut)
def update_book(
    book_id: int,
    data: BookUpdate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    book = get_book_or_404(book_id, db)
    ensure_owner(book, user)

    for key, value in data.model_dump(
        exclude_unset=True
    ).items():
        if value is not None:
            setattr(
                book,
                key,
                value.strip() if isinstance(value, str)
                else value
            )

    db.commit()
    db.refresh(book)

    return book_out(book)


# ==========================================
# DELETE BOOK
# ==========================================

@app.delete("/books/{book_id}")
def delete_book(
    book_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    book = get_book_or_404(book_id, db)
    ensure_owner(book, user)

    db.query(Favorite).filter(
        Favorite.book_id == book_id
    ).delete(synchronize_session=False)

    paths = [book.pdf_path, book.cover_path]

    db.delete(book)
    db.commit()

    for path in paths:
        if path:
            Path(path).unlink(missing_ok=True)

    return {"message": "Book deleted"}


# ==========================================
# ADD FAVORITE
# ==========================================

@app.post("/books/{book_id}/favorite", status_code=201)
def add_favorite(
    book_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    get_book_or_404(book_id, db)

    exists = db.scalar(
        select(Favorite).where(
            Favorite.user_id == user.id,
            Favorite.book_id == book_id
        )
    )

    if not exists:
        db.add(
            Favorite(
                user_id=user.id,
                book_id=book_id
            )
        )
        db.commit()

    return {"message": "Added to favorites"}


@app.delete("/books/{book_id}/favorite")
def remove_favorite(
    book_id: int,
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    db.query(Favorite).filter(
        Favorite.user_id == user.id,
        Favorite.book_id == book_id
    ).delete(synchronize_session=False)

    db.commit()

    return {"message": "Removed from favorites"}


# ==========================================
# ADMIN STATISTICS
# ==========================================

@app.get("/admin/stats")
def admin_stats(
    user: User = Depends(current_user),
    db: Session = Depends(get_db)
):
    if user.role != "admin":
        raise HTTPException(
            403, "Admin access required"
        )

    return {
        "users": db.scalar(
            select(func.count()).select_from(User)
        ),
        "books": db.scalar(
            select(func.count()).select_from(Book)
        ),
        "downloads": db.scalar(
            select(func.coalesce(func.sum(Book.downloads), 0))
        )
    }
