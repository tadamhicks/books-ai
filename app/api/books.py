from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.schemas import BookRead, BookCreate, CreateResult, DeleteResult, BooksByAuthorResponse
from app.services.books_service import BookService

router = APIRouter(prefix="/books", tags=["books"])


@router.get("/title", response_model=BookRead)
async def get_by_title(title: str, session: AsyncSession = Depends(get_session)):
    service = BookService()
    book = await service.get_by_title(session, title)
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return book


@router.get("/author", response_model=BooksByAuthorResponse)
async def get_by_author(author_last_name: str, session: AsyncSession = Depends(get_session)):
    service = BookService()
    books = await service.get_by_author(session, author_last_name)
    if not books:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No books found for author")
    first = books[0]
    return BooksByAuthorResponse(
        author_first_name=first.author_first_name,
        author_last_name=first.author_last_name,
        titles=books,
    )


@router.get("/isbn/{isbn}", response_model=BookRead)
async def get_by_isbn(isbn: str, session: AsyncSession = Depends(get_session)):
    service = BookService()
    book = await service.get_by_isbn(session, isbn)
    if not book:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return book


@router.post("", response_model=CreateResult, status_code=status.HTTP_201_CREATED)
async def create_book(payload: BookCreate, session: AsyncSession = Depends(get_session)):
    service = BookService()
    book, outcome, created = await service.create_book(session, payload)
    if book:
        return CreateResult(created=created, book=book, note=None if created else "Book already exists")
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=outcome.suggestions or "Book does not appear to exist",
    )


@router.delete("/{isbn}", response_model=DeleteResult)
async def delete_book(isbn: str, session: AsyncSession = Depends(get_session)):
    service = BookService()
    deleted = await service.delete_by_isbn(session, isbn)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Book not found")
    return DeleteResult(deleted=True, isbn=isbn)

