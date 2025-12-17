from sqlalchemy import Column, String, DateTime, func

from app.db.session import Base


class Book(Base):
    __tablename__ = "books"
    __table_args__ = {"schema": "books"}

    isbn = Column(String(13), primary_key=True, index=True)
    title = Column(String(512), nullable=False, index=True)
    author_first_name = Column(String(256), nullable=False, index=True)
    author_last_name = Column(String(256), nullable=False, index=True)
    summary = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

