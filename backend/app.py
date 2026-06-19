from fastapi import FastAPI
from backend.config import DB_PATH
from backend import db

app = FastAPI(title="Clio")


@app.on_event("startup")
async def startup_event():
    db.init_db(DB_PATH)


@app.get("/health")
async def health():
    return {"status": "ok"}
