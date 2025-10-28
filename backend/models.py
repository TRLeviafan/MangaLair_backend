from sqlalchemy import Column, Integer, String, Text, DateTime, UniqueConstraint
from sqlalchemy.sql import func
from .db import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    tg_id = Column(String(64), unique=True, index=True, nullable=False)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=True)
    last_name = Column(String(255), nullable=True)
    photo_url = Column(String(512), nullable=True)
    data_json = Column(Text, nullable=False, default="{}")  # account payload
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Comment(Base):
    __tablename__ = "comments"
    id = Column(Integer, primary_key=True)
    series_key = Column(String(128), index=True, nullable=False)  # "<sid>-<slug>"
    chapter_id = Column(String(64), index=True, nullable=False)
    tg_id = Column(String(64), index=True, nullable=False)
    username = Column(String(255), nullable=True)
    text = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
