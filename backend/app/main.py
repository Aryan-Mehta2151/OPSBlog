import os
from pathlib import Path
from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.core.deps import get_db
from app.db.session import engine
from app.db.models import Base
from app.routers import auth, blogs, vector_search, pdfs, images


app = FastAPI(title="OpsBlog (Multi-tenant)")

# CORS — allow frontend origins
allowed_origins = os.getenv("CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(blogs.router)
app.include_router(vector_search.router)
app.include_router(pdfs.router)
app.include_router(images.router)

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/db-health")
def db_health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"db": "ok"}

@app.get("/tables")
def tables(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT tablename
        FROM pg_tables
        WHERE schemaname = 'public'
        ORDER BY tablename;
    """)).fetchall()
    return {"tables": [r[0] for r in rows]}

# Serve React frontend static files in production
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if FRONTEND_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="static")

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        """Serve React SPA — any non-API path returns index.html"""
        file = FRONTEND_DIR / full_path
        if file.is_file():
            return FileResponse(str(file))
        return FileResponse(str(FRONTEND_DIR / "index.html"))