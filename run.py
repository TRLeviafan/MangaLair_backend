import asyncio
import uvicorn
from backend.app import app
from backend.settings import settings
from backend.bot import create_application, run_bot

async def main():
    config = uvicorn.Config(app, host=getattr(settings, "HOST", "0.0.0.0"), port=int(getattr(settings, "PORT", 8000)))
    server = uvicorn.Server(config)
    bot_app = create_application()

    async def serve_api():
        await server.serve()

    async def serve_bot():
        await run_bot(bot_app)

    await asyncio.gather(serve_api(), serve_bot())

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
