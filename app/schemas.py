from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field


class BookBase(BaseModel):
    title: str = Field(..., min_length=1, max_length=512)
    author_first_name: str = Field(..., min_length=1, max_length=256)
    author_last_name: str = Field(..., min_length=1, max_length=256)


class BookCreate(BookBase):
    pass


class BookRead(BookBase):
    isbn: str = Field(..., min_length=13, max_length=13)
    summary: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BooksByAuthorResponse(BaseModel):
    author_first_name: str
    author_last_name: str
    titles: List[BookRead]


class CreateResult(BaseModel):
    created: bool
    book: BookRead
    note: Optional[str] = None


class DeleteResult(BaseModel):
    deleted: bool
    isbn: str




