CREATE SCHEMA IF NOT EXISTS books;

CREATE TABLE IF NOT EXISTS books.books (
    isbn VARCHAR(13) PRIMARY KEY,
    title VARCHAR(512) NOT NULL,
    author_first_name VARCHAR(256) NOT NULL,
    author_last_name VARCHAR(256) NOT NULL,
    summary TEXT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW() NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_books_title ON books.books (title);
CREATE INDEX IF NOT EXISTS idx_books_author_last ON books.books (author_last_name);




