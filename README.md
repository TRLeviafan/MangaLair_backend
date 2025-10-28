# Mangalair Backend (FastAPI + Telegram Bot)

Этот репозиторий содержит только **бэкенд**:
- FastAPI (Uvicorn)
- python-telegram-bot
- SQLAlchemy (SQLite по умолчанию)

## Запуск локально
```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполните BOT_TOKEN и при необходимости PUBLIC_BASE
python run.py
# API: http://127.0.0.1:8000/health
```

## Деплой на VPS (Timeweb Cloud, Ubuntu)
1. Установите зависимости: `nginx`, `python3-venv`, `git`, `sqlite3`, `certbot python3-certbot-nginx`.
2. Расположите код в `/opt/mangalair`, создайте `/opt/mangalair/data/`.
3. Создайте `.venv`, установите зависимости из `requirements.txt`.
4. Скопируйте `.env.example` → `.env` и заполните переменные.
5. Включите WAL для SQLite:  
   `sqlite3 /opt/mangalair/data/data.db "PRAGMA journal_mode=WAL; PRAGMA synchronous=NORMAL;"`
6. Поднимите systemd-сервис с `ExecStart=/opt/mangalair/.venv/bin/python /opt/mangalair/run.py`.
7. Nginx проксирует `api.mangalair.ru` → `127.0.0.1:8000`, затем `certbot --nginx -d api.mangalair.ru`.

### Примечания
- В коде отключена раздача фронта — монтирование `frontend/` происходит **только если папка существует**. Боевой фронт обслуживает Cloudflare Pages.
- БД по умолчанию — **SQLite**, путь задаётся `DATABASE_URL`.