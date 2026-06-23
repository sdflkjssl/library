# Library Prototype

A Django prototype for a small library system with separate reader and librarian workflows.

## Features

- Reader login and librarian login with role-based access control.
- Catalogue search by title, author, or ISBN.
- Availability display based on physical book copies, not just book titles.
- Reader view of current loans and due dates.
- Librarian workflows to create loans, register returns, view a reader's active loans, and modify due dates.
- Transaction-wrapped loan operations and a database constraint preventing two active loans for the same copy.
- Demo seed command and focused automated tests.

## Engineering Notes

The app models `Book` separately from `BookCopy` so one title can have multiple lendable copies. Loan mutations live in `catalogue/services.py`, which keeps business rules consistent across views and tests. Access control is enforced server-side with role decorators, so readers cannot access librarian workflows or another reader's loans.

## Local Setup

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo --reset
python manage.py runserver
```

Open `http://127.0.0.1:8000`.

## Demo Credentials

Reader:

- Username: `reader`
- Password: `ReaderDemo123!`

Librarian:

- Username: `librarian`
- Password: `LibrarianDemo123!`

## Tests

```bash
pytest
```

The test suite covers role restrictions, loan creation, duplicate active loan prevention, returns, due date changes, and catalogue availability counts.

## Deployment

The project is ready for a simple Render/Fly/Railway-style deployment.

Set these environment variables in production:

- `SECRET_KEY`
- `DEBUG=false`
- `ALLOWED_HOSTS`
- `CSRF_TRUSTED_ORIGINS`
- `DATABASE_URL` for PostgreSQL

Then run:

```bash
python manage.py migrate
python manage.py seed_demo --reset
python manage.py collectstatic --noinput
gunicorn library_project.wsgi
```
