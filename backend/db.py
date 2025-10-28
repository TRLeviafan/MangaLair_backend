from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from .settings import settings

engine = create_engine(settings.DATABASE_URL, echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

def init_db():
    # tables created in models import
    from . import models  # noqa
    Base.metadata.create_all(bind=engine)
