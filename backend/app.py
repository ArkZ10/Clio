from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.config import DB_PATH, HOST, PORT
from backend import db
from backend.routes.library import router as library_router
from backend.routes.explore import router as explore_router
from backend.routes.vault import router as vault_router
from backend.routes.chat import router as chat_router
from backend.routes.settings import router as settings_router

app = FastAPI(title="Clio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(library_router)
app.include_router(explore_router)
app.include_router(vault_router)
app.include_router(chat_router)
app.include_router(settings_router)


@app.on_event("startup")
async def startup_event():
    db.init_db(DB_PATH)


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
