from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional

import json
import os

import git
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, validator

# =========================================================
# 設定
# =========================================================

# Git リポジトリの場所（このプロジェクトのルートを指す想定）
REPO_PATH = Path(os.getenv("REPO_PATH", Path(__file__).resolve().parents[2])).resolve()
REPO_BRANCH = os.getenv("REPO_BRANCH", "main")
BACKUP_FILE = REPO_PATH / "backup.json"

# 認証用トークン（開発中は未設定でもOK）
API_TOKEN = os.getenv("API_TOKEN")

# CORS許可（GitHub Pages など別オリジンから叩けるように）
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*")  # カンマ区切りで指定も可


def get_repo() -> git.Repo:
    """既存のGitリポジトリを開く。起動前に git clone 済み前提。"""
    if not REPO_PATH.exists():
        raise RuntimeError(f"REPO_PATH not found: {REPO_PATH}")
    try:
        repo = git.Repo(REPO_PATH)
    except Exception as e:
        raise RuntimeError(f"Failed to open git repo at {REPO_PATH}: {e}")
    return repo


# =========================================================
# 認証（超シンプルなBearerトークン）
# =========================================================

def require_token(authorization: Optional[str] = Header(default=None)) -> None:
    """
    Authorization: Bearer xxx 形式のトークンをチェック。
    API_TOKEN が未設定ならスキップ（開発モード）。
    """
    if API_TOKEN is None:
        return  # 認証スキップ

    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid token")

    token = authorization.removeprefix("Bearer ").strip()
    if token != API_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid token")


# =========================================================
# データモデル（Pydantic）
# =========================================================

VALID_STATUS = ["未提出", "印刷済", "返却待ち", "ピッキング完了", "出庫済", "入庫確認"]


def normalize_status(value: Optional[str]) -> str:
    if not value:
        return ""
    v = str(value).strip()
    if v == "出庫完了":
        return "出庫済"
    if v in VALID_STATUS:
        return v
    return ""


def normalize_date(value: Optional[str]) -> str:
    """
    'YYYY-MM-DD' 形式だけ通す簡易版。
    それ以外は '' にしてしまう。
    """
    if not value:
        return ""
    v = str(value).strip()
    if len(v) == 10 and v[4] == "-" and v[7] == "-":
        return v
    return ""


class TodoEntry(BaseModel):
    status: str = ""
    completedAt: Optional[str] = None
    updatedAt: Optional[str] = None
    fields: Dict[str, Any] = Field(default_factory=dict)

    @validator("status", pre=True)
    def _normalize_status(cls, v: Optional[str]) -> str:
        return normalize_status(v)

    @validator("completedAt", "updatedAt", pre=True)
    def _normalize_iso(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        return str(v)


class BackupPayload(BaseModel):
    data: Dict[str, TodoEntry]
    meta: Dict[str, Any] = Field(default_factory=dict)


class BackupResponse(BaseModel):
    ok: bool
    data: Dict[str, TodoEntry]
    meta: Dict[str, Any]


class BackupSaveResponse(BaseModel):
    ok: bool
    commit: Dict[str, Any]


# =========================================================
# ヘルパー
# =========================================================

def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_backup_from_disk() -> Dict[str, Any]:
    """
    backup.json を読み込んで dict を返す。
    なければ空 dict。
    """
    if not BACKUP_FILE.exists():
        return {}
    try:
        with BACKUP_FILE.open("r", encoding="utf-8") as f:
            obj = json.load(f)
        if not isinstance(obj, dict):
            raise ValueError("backup.json is not a JSON object")
        return obj
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"backup_read_error: {e}")


def save_backup_to_disk(data: Dict[str, Any]) -> None:
    """
    dict を backup.json に保存。
    """
    BACKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    with BACKUP_FILE.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def git_commit_and_push(repo: git.Repo, message: str) -> str:
    """
    backup.json を add / commit / push する。
    戻り値はコミットハッシュ。
    """
    repo.git.add(str(BACKUP_FILE))

    # 変更がなければそのまま返す
    if not repo.index.diff("HEAD"):
        return repo.head.commit.hexsha

    commit = repo.index.commit(message)
    origin = repo.remotes.origin
    origin.push(REPO_BRANCH)
    return commit.hexsha


# =========================================================
# FastAPI アプリ
# =========================================================

app = FastAPI(
    title="Picking ToDo Backup API",
    version="0.1.0",
)

# CORS 設定
if ALLOWED_ORIGINS == "*":
    origins = ["*"]
else:
    origins = [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health():
    repo_info = {
        "path": str(REPO_PATH),
        "branch": REPO_BRANCH,
        "backup_exists": BACKUP_FILE.exists(),
    }
    return {"status": "ok", "repo": repo_info}


@app.get("/api/backup", response_model=BackupResponse)
def get_backup(token: None = Depends(require_token)):
    """
    backup.json をGitリポジトリから読み込んで返す。
    """
    repo = get_repo()
    # 必要であればここで origin.pull(REPO_BRANCH) しても良い

    raw = load_backup_from_disk()

    normalized: Dict[str, TodoEntry] = {}
    for order_no, entry in raw.items():
        normalized[order_no] = TodoEntry(**entry)

    return BackupResponse(
        ok=True,
        data=normalized,
        meta={
            "source": "git",
            "commit_hash": repo.head.commit.hexsha if repo.head.is_valid() else None,
            "updated_at": now_iso(),
        },
    )


@app.post("/api/backup", response_model=BackupSaveResponse)
def save_backup(payload: BackupPayload, token: None = Depends(require_token)):
    """
    フロントから送られた todoStore を backup.json に保存し、
    Git で commit & push する。
    """
    repo = get_repo()

    normalized_dict: Dict[str, Any] = {
        order_no: entry.dict(by_alias=True) for order_no, entry in payload.data.items()
    }

    save_backup_to_disk(normalized_dict)

    author = payload.meta.get("author") or "unknown"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    message = f"[picking-todo] update backup by {author} at {ts}"

    try:
        commit_hash = git_commit_and_push(repo, message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"git_push_failed: {e}")

    return BackupSaveResponse(
        ok=True,
        commit={
            "hash": commit_hash,
            "timestamp": now_iso(),
        },
    )
