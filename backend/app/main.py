import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import settings
from .database import Base, engine
from .routers import analysis, auth, boundaries, citations, evidence, facts, projects, scope

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="公共建筑改造范围与能耗绩效数据核验平台",
    description="证据受理库 / 改造范围册 / 计量边界册 / 绩效事实编译器 / 引用簿",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS + ["http://localhost:8080", "http://127.0.0.1:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for r in (auth.router, projects.router, evidence.router, scope.router,
          boundaries.router, facts.router, citations.router, analysis.router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"status": "ok"}


# 可选：若存在前端构建产物则直接托管（Docker 一体化场景）
_static = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.isdir(_static):
    app.mount("/assets", StaticFiles(directory=os.path.join(_static, "assets")), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        target = os.path.join(_static, full_path)
        if full_path and os.path.isfile(target):
            return FileResponse(target)
        return FileResponse(os.path.join(_static, "index.html"))
