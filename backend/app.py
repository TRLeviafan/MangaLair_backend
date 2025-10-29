import os, json
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .settings import settings
from .db import SessionLocal, init_db
from .models import User
from .auth import parse_and_verify_init_data, extract_init_data_from_request, InitDataError

from sqlalchemy.orm import Session

import urllib.request, urllib.error
from urllib.parse import quote

# --- simple in-memory rate limiter for like endpoint ---
import time
_RATE_LIKE_BUCKET = {}
def _rate_limit_ok(key: str, limit=5, window=10):
    # allow 'limit' requests per 'window' seconds
    now = time.time()
    bucket = _RATE_LIKE_BUCKET.get(key) or []
    bucket = [t for t in bucket if now - t < window]
    if len(bucket) >= limit:
        _RATE_LIKE_BUCKET[key] = bucket
        return False
    bucket.append(now)
    _RATE_LIKE_BUCKET[key] = bucket
    return True
# --- end rate limiter ---


ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
FRONTEND_DIR = os.path.join(ROOT, "frontend")


from fastapi.responses import RedirectResponse


app = FastAPI(title="Mangalair MiniApp API")

@app.get("/comments,{series_key},{chapter_id}")
def legacy_comments_alias(series_key: str, chapter_id: str):
    # 307 keeps method; FastAPI will handle URL decoding of %2C → ',' before matching
    return RedirectResponse(url=f"/api/comments/{series_key}/{chapter_id}", status_code=307)

@app.post("/comments,{series_key},{chapter_id},add")
async def legacy_comments_add_alias(series_key: str, chapter_id: str):
    # старый POST /comments,sr_xxx,ch_yyy,add -> новый POST /api/comments/sr_xxx/ch_yyy/add
    return RedirectResponse(url=f"/api/comments/{series_key}/{chapter_id}/add", status_code=307)

@app.get("/likes,all")
def legacy_likes_all_alias():
    return RedirectResponse(url="/api/likes/all", status_code=307)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def default_account(user: dict[str, Any]) -> dict[str, Any]:
    return {
        "username": user.get("username") or f"user{user.get('id')}",
        "avatarUrl": user.get("photo_url") or "https://api.dicebear.com/7.x/thumbs/svg?seed=Guest&backgroundType=gradientLinear",
        "since": __import__("datetime").datetime.utcnow().isoformat(),
        "favorites": [],
        "likes": {},
        "readProgress": {},
        "stats": {"chaptersRead": 0},
        "prefs": {"direction": "manhwa", "continuous": True, "comments": "after"},
    }

@app.on_event("startup")
def startup():
    init_db()

@app.get("/health")
def health():
    return {"ok": True}

@app.get("/api/config")
def api_config():
    if not settings.PUBLIC_BASE:
        raise HTTPException(500, "PUBLIC_BASE is not configured")
    return {"PUBLIC_BASE": settings.PUBLIC_BASE, "COMMENTS_API": "/api"}

def _get_user_from_db(db: Session, tg_id: str) -> Optional[User]:
    return db.query(User).filter(User.tg_id == str(tg_id)).one_or_none()

def _ensure_user(db: Session, user_payload: dict) -> User:
    tg_id = str(user_payload["id"])
    u = _get_user_from_db(db, tg_id)
    if u is None:
        u = User(
            tg_id=tg_id,
            username=user_payload.get("username"),
            first_name=user_payload.get("first_name"),
            last_name=user_payload.get("last_name"),
            photo_url=user_payload.get("photo_url"),
            data_json=json.dumps(default_account(user_payload), ensure_ascii=False),
        )
        db.add(u)
        db.commit()
        db.refresh(u)
    return u

def require_user(request: Request, db: Session = Depends(get_db)) -> tuple[User, dict]:
    raw = extract_init_data_from_request(request)
    if not raw:
        raise HTTPException(401, "initData missing")
    try:
        pairs = parse_and_verify_init_data(raw, settings.BOT_TOKEN)
    except InitDataError as e:
        raise HTTPException(401, f"initData invalid: {e}")
    user_json = pairs.get("user")
    try:
        user_payload = json.loads(user_json) if user_json else None
    except Exception:
        user_payload = None
    if not user_payload or "id" not in user_payload:
        raise HTTPException(401, "user missing in initData")

    user = _ensure_user(db, user_payload)
    try:
        account = json.loads(user.data_json or "{}")
    except Exception:
        account = default_account(user_payload)
    return user, account

@app.get("/api/me")
def me(dep=Depends(require_user)):
    user, account = dep
    return {"ok": True, "account": account}

@app.post("/api/me/update")
async def me_update(payload: Dict[str, Any], dep=Depends(require_user), db: Session=Depends(get_db)):
    user, account = dep
    updated = {**account}
    for key, value in payload.items():
        if key == "prefs":
            prefs = updated.get("prefs", {})
            # direction + continuous
            prefs.update({
                "direction": value.get("direction", prefs.get("direction", "manhwa")),
            })
            # continuous derives from direction unless explicitly provided (for ltr/rtl)
            if prefs["direction"] == "manhwa":
                prefs["continuous"] = True
            else:
                prefs["continuous"] = bool(value.get("continuous", prefs.get("continuous", False)))
            # comments: "after" | "always" | "off"
            cval = (value.get("comments", prefs.get("comments", "after")) or "after")
            if cval not in ("after","always","off"):
                cval = "after"
            prefs["comments"] = cval
            updated["prefs"] = prefs
        elif key in ("favorites", "likes", "readProgress", "stats"):
            cur = updated.get(key, {} if key != "favorites" else [])
            if isinstance(cur, dict) and isinstance(value, dict):
                cur.update(value)
                updated[key] = cur
            elif isinstance(cur, list) and isinstance(value, list):
                updated[key] = value
            else:
                updated[key] = value
        else:
            updated[key] = value
    user.data_json = json.dumps(updated, ensure_ascii=False)
    db.add(user)
    db.commit()
    return {"ok": True, "account": updated}

# ---------- Server-side JSON proxy (with URL-encoding for slugs) ----------

def _fetch_json_no_store(url: str):
    req = urllib.request.Request(url, headers={
        "Cache-Control": "no-store",
        "Pragma": "no-cache",
        "User-Agent": "MangalairMiniApp/1.0"
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = resp.read()
            return json.loads(data.decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise HTTPException(e.code, f"Upstream HTTP {e.code} for {url}")
    except urllib.error.URLError as e:
        raise HTTPException(502, f"Upstream error for {url}: {e.reason}")
    except Exception as e:
        raise HTTPException(500, f"Upstream parse error for {url}: {e}")

@app.get("/api/catalog")
def api_catalog(db: Session = Depends(get_db)):
    if not settings.PUBLIC_BASE:
        raise HTTPException(500, "PUBLIC_BASE is not configured")
    url = f"{settings.PUBLIC_BASE}/catalog/index.json"
    data = _fetch_json_no_store(url)
    # Merge likes counts
    try:
        counts = _count_likes_patch(db)
        items = data if isinstance(data, list) else (data.get("items") if isinstance(data, dict) else None)
        if isinstance(items, list):
            for it in items:
                key = None
                try:
                    sid = str(it.get("sid") or it.get("seriesId") or it.get("series_id") or it.get("id") or "")
                    slug = str(it.get("slug") or "")
                    key = f"{sid}-{slug}" if slug else (sid if sid and sid.startswith("sr_") else None)
                except Exception:
                    key = None
                if key:
                    it["likes"] = int(counts.get(key, 0))
    except Exception:
        pass
    return data

@app.get("/api/series/{sid}-{slug}/meta")
def api_series_meta(sid: str, slug: str):
    if not settings.PUBLIC_BASE:
        raise HTTPException(500, "PUBLIC_BASE is not configured")
    sid_q = quote(str(sid), safe="")
    slug_q = quote(str(slug), safe="")
    url = f"{settings.PUBLIC_BASE}/series/{sid_q}-{slug_q}/meta.json"
    return _fetch_json_no_store(url)

@app.get("/api/series/{sid}-{slug}/chapters-index")
def api_series_chapters_index(sid: str, slug: str):
    if not settings.PUBLIC_BASE:
        raise HTTPException(500, "PUBLIC_BASE is not configured")
    sid_q = quote(str(sid), safe="")
    slug_q = quote(str(slug), safe="")
    url = f"{settings.PUBLIC_BASE}/series/{sid_q}-{slug_q}/chapters/index.json"
    return _fetch_json_no_store(url)

# ---------- Global Likes (computed across users' data_json) ----------
def _series_key(sid: str, slug: str) -> str:
    return f"{sid}-{slug}"

def _count_likes(db: Session) -> dict[str, int]:
    rows = db.query(User).all()
    counts: dict[str, int] = {}
    for u in rows:
        try:
            data = json.loads(u.data_json or "{}")
            likes = data.get("likes") or {}
            if isinstance(likes, dict):
                for k, v in likes.items():
                    if v:
                        counts[k] = counts.get(k, 0) + 1
        except Exception:
            continue
    return counts

@app.get("/api/likes/all")
def api_likes_all(db: Session = Depends(get_db)):
    return {"ok": True, "counts": _count_likes(db)}

@app.post("/api/likes/{sid}-{slug}/toggle")
def api_like_toggle(sid: str, slug: str, db: Session = Depends(get_db), dep=Depends(require_user)):
    user, account = dep
    key = _series_key(sid, slug)
    likes = account.get("likes") or {}
    liked = not bool(likes.get(key))
    likes[key] = liked
    account["likes"] = likes
    user.data_json = json.dumps(account, ensure_ascii=False)
    db.add(user)
    db.commit()
    total = _count_likes(db).get(key, 0)
    return {"ok": True, "liked": liked, "count": total}

# -------------------------------------------------------------------------


# --- Patch: add GET support and dash-joined series key for likes toggle ---

from fastapi import Response
from sqlalchemy.orm import Session

def _series_key_patch(sid: str, slug: str) -> str:
    return f"{sid}-{slug}"

def _count_likes_patch(db: Session) -> Dict[str, int]:
    out: Dict[str, int] = {}
    try:
        users = db.query(User).all()
    except Exception:
        return out
    for u in users:
        try:
            acc = json.loads(u.data_json or "{}")
            for k, v in (acc.get("likes") or {}).items():
                if v:
                    out[k] = out.get(k, 0) + 1
        except Exception:
            continue
    return out

def _get_or_create_user_from_initdata(request: Request, db: Session) -> User:
    raw = extract_init_data_from_request(request)
    if not raw:
        raise HTTPException(status_code=401, detail="initData required")
    pairs = parse_and_verify_init_data(raw, settings.BOT_TOKEN)
    user_field = pairs.get("user")
    if isinstance(user_field, str):
        try:
            user_obj = json.loads(user_field)
        except Exception:
            user_obj = {}
    else:
        user_obj = user_field or {}
    tg_id = str(user_obj.get("id") or "")
    if not tg_id:
        raise HTTPException(status_code=401, detail="invalid initData (no user)")
    user = db.query(User).filter(User.tg_id == tg_id).first()
    if not user:
        user = User(
            tg_id=tg_id,
            username=user_obj.get("username"),
            first_name=user_obj.get("first_name"),
            last_name=user_obj.get("last_name"),
            photo_url=user_obj.get("photo_url"),
            data_json="{}",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    return user

@app.get("/api/likes/{series_key}/toggle")
@app.post("/api/likes/{series_key}/toggle")
def toggle_like_dash(series_key: str, request: Request):
    """
    Accepts series_key in form '<sid>-<slug>' (hyphen-joined).
    This endpoint mirrors the POST /api/likes/{sid}-{slug}/toggle behavior
    and exists to avoid 404s when clients send GET.
    """
    # split into sid and slug by first hyphen
    if "-" not in series_key:
        raise HTTPException(status_code=404, detail="invalid series key")
    sid, slug = series_key.split("-", 1)

    db = SessionLocal()
    try:
        user = _get_or_create_user_from_initdata(request, db)
        # load account payload
        try:
            account = json.loads(user.data_json or "{}")
        except Exception:
            account = {}
        key = _series_key_patch(sid, slug)
        likes = account.get("likes") or {}
        liked = not bool(likes.get(key))
        likes[key] = liked
        account["likes"] = likes
        user.data_json = json.dumps(account, ensure_ascii=False)
        db.add(user)
        db.commit()
        total = _count_likes_patch(db).get(key, 0)
        return {"ok": True, "liked": liked, "count": total}
    finally:
        db.close()

# --- end patch ---



# --------------------- Comments API ---------------------

from sqlalchemy import select, desc, asc
from .models import Comment

def _series_key(sid: str, slug: str) -> str:
    return f"{sid}-{slug}"

@app.get("/api/comments/{sid}-{slug}/{chapter_id}")
def api_comments_list(sid: str, slug: str, chapter_id: str, db: Session = Depends(get_db)):
    key = _series_key(sid, slug)
    rows = db.execute(
        select(Comment).where(Comment.series_key == key, Comment.chapter_id == str(chapter_id)).order_by(asc(Comment.created_at)).limit(200)
    ).scalars().all()
    items = [{
        "id": c.id,
        "author": c.username or f"user{c.tg_id}",
        "tg_id": c.tg_id,
        "text": c.text,
        "ts": c.created_at.isoformat() if c.created_at else None,
    } for c in rows]
    return {"ok": True, "items": items}

@app.post("/api/comments/{sid}-{slug}/{chapter_id}/add")
async def api_comments_add(sid: str, slug: str, chapter_id: str, payload: Dict[str, Any], dep=Depends(require_user), db: Session = Depends(get_db)):
    user, account = dep
    # basic rate limit per user
    rl_key = f"cmt:{user.tg_id}"
    if not _rate_limit_ok(rl_key, limit=5, window=30):
        raise HTTPException(429, "Слишком часто. Попробуйте чуть позже.")
    text = (payload.get("text") or "").strip()
    if not text:
        raise HTTPException(400, "Пустой комментарий")
    if len(text) > 1000:
        raise HTTPException(413, "Слишком длинный комментарий (макс. 1000 символов)")
    c = Comment(
        series_key=_series_key(sid, slug),
        chapter_id=str(chapter_id),
        tg_id=str(user.tg_id),
        username=account.get("username") or user.username,
        text=text[:1000],
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"ok": True, "item": {
        "id": c.id, "author": c.username or f"user{c.tg_id}", "tg_id": c.tg_id, "text": c.text,
        "ts": c.created_at.isoformat() if c.created_at else None
    }}

# Mount frontend only if directory exists (Pages serves the real front)
import os as _os
if _os.path.isdir(FRONTEND_DIR):
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
