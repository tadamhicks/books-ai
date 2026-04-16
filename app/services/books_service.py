import logging
import random
from typing import Optional, List

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import models
from app.schemas import BookCreate, BookRead
from app.services.bedrock_client import BedrockClient, BedrockOutcome, get_bedrock_client
from app.tracing import get_tracer

logger = logging.getLogger(__name__)


class BookService:
    def __init__(self, bedrock: Optional[BedrockClient] = None) -> None:
        self.bedrock = bedrock or get_bedrock_client()
        self.tracer = get_tracer()

    @staticmethod
    def _generate_isbn() -> str:
        return f"{random.randint(0, 9999999999999):013d}"

    async def get_by_title(self, session: AsyncSession, title: str) -> Optional[models.Book]:
        result = await session.execute(select(models.Book).where(models.Book.title.ilike(title)))
        return result.scalars().first()

    async def get_by_author(self, session: AsyncSession, author_last: str) -> List[models.Book]:
        stmt = select(models.Book).where(models.Book.author_last_name.ilike(author_last))
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_isbn(self, session: AsyncSession, isbn: str) -> Optional[models.Book]:
        result = await session.execute(select(models.Book).where(models.Book.isbn == isbn))
        return result.scalars().first()

    async def create_book(
        self, session: AsyncSession, payload: BookCreate
    ) -> tuple[Optional[models.Book], BedrockOutcome, bool]:
        existing = await self.get_by_title(session, payload.title)
        if existing:
            logger.info("Book already exists in DB: '%s'", payload.title)
            return existing, BedrockOutcome(exists=True, summary=existing.summary), False

        logger.info(
            "Book not in DB, evaluating via Bedrock: '%s' by %s %s",
            payload.title, payload.author_first_name, payload.author_last_name,
        )
        try:
            outcome = await self.bedrock.evaluate(payload.title, payload.author_first_name, payload.author_last_name)
        except Exception:
            logger.error("Bedrock evaluation failed for '%s'", payload.title, exc_info=True)
            raise
        if not outcome.exists:
            logger.warning("Bedrock says book does not exist: '%s'", payload.title)
            return None, outcome, False

        book = models.Book(
            isbn=self._generate_isbn(),
            title=payload.title,
            author_first_name=payload.author_first_name,
            author_last_name=payload.author_last_name,
            summary=outcome.summary,
        )
        session.add(book)
        await session.commit()
        await session.refresh(book)
        logger.info("Created book isbn=%s title='%s'", book.isbn, book.title)
        return book, outcome, True

    async def delete_by_isbn(self, session: AsyncSession, isbn: str) -> int:
        result = await session.execute(delete(models.Book).where(models.Book.isbn == isbn))
        await session.commit()
        count = result.rowcount or 0
        logger.info("Deleted %d book(s) with isbn=%s", count, isbn)
        return count

