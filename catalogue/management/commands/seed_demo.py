from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from catalogue.models import Book, BookCopy, Loan, UserProfile


class Command(BaseCommand):
    help = "Create demo users, catalogue records, copies, and sample loans."

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Remove existing demo data before seeding.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        User = get_user_model()
        demo_usernames = ["reader", "reader2", "librarian"]

        if options["reset"]:
            Loan.objects.all().delete()
            BookCopy.objects.all().delete()
            Book.objects.all().delete()
            User.objects.filter(username__in=demo_usernames).delete()

        reader = self._user(
            username="reader",
            password="ReaderDemo123!",
            first_name="Alex",
            last_name="Reader",
            role=UserProfile.Role.READER,
        )
        second_reader = self._user(
            username="reader2",
            password="ReaderTwoDemo123!",
            first_name="Sam",
            last_name="Patel",
            role=UserProfile.Role.READER,
        )
        librarian = self._user(
            username="librarian",
            password="LibrarianDemo123!",
            first_name="Morgan",
            last_name="Librarian",
            role=UserProfile.Role.LIBRARIAN,
            is_staff=True,
        )

        books = [
            {
                "title": "Clean Code",
                "author": "Robert C. Martin",
                "isbn": "9780132350884",
                "description": "Practical guidance for writing readable and maintainable software.",
                "copies": ["CC-001", "CC-002"],
            },
            {
                "title": "The Pragmatic Programmer",
                "author": "David Thomas and Andrew Hunt",
                "isbn": "9780135957059",
                "description": "Engineering habits and techniques for professional software developers.",
                "copies": ["PP-001", "PP-002", "PP-003"],
            },
            {
                "title": "Designing Data-Intensive Applications",
                "author": "Martin Kleppmann",
                "isbn": "9781449373320",
                "description": "A deep look at reliable, scalable, and maintainable data systems.",
                "copies": ["DDIA-001", "DDIA-002"],
            },
            {
                "title": "Refactoring",
                "author": "Martin Fowler",
                "isbn": "9780134757599",
                "description": "Improving the design of existing code through disciplined transformations.",
                "copies": ["RF-001"],
            },
            {
                "title": "Domain-Driven Design",
                "author": "Eric Evans",
                "isbn": "9780321125217",
                "description": "Tackling complex software domains through model-driven design.",
                "copies": ["DDD-001"],
            },
        ]

        copy_by_code = {}
        for item in books:
            book, _ = Book.objects.update_or_create(
                isbn=item["isbn"],
                defaults={
                    "title": item["title"],
                    "author": item["author"],
                    "description": item["description"],
                },
            )
            for code in item["copies"]:
                copy, _ = BookCopy.objects.get_or_create(
                    inventory_code=code,
                    defaults={"book": book},
                )
                if copy.book_id != book.id:
                    copy.book = book
                    copy.save(update_fields=["book"])
                copy_by_code[code] = copy

        self._active_loan(
            reader=reader,
            copy=copy_by_code["DDIA-001"],
            due_date=timezone.localdate() + timedelta(days=10),
            librarian=librarian,
        )
        self._active_loan(
            reader=reader,
            copy=copy_by_code["RF-001"],
            due_date=timezone.localdate() + timedelta(days=21),
            librarian=librarian,
        )
        self._active_loan(
            reader=second_reader,
            copy=copy_by_code["DDD-001"],
            due_date=timezone.localdate() + timedelta(days=14),
            librarian=librarian,
        )

        self.stdout.write(self.style.SUCCESS("Demo data seeded."))
        self.stdout.write("Reader: reader / ReaderDemo123!")
        self.stdout.write("Librarian: librarian / LibrarianDemo123!")

    def _user(self, *, username, password, first_name, last_name, role, is_staff=False):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=username,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "is_staff": is_staff,
            },
        )
        if created:
            user.set_password(password)
        user.first_name = first_name
        user.last_name = last_name
        user.is_staff = is_staff
        user.save()
        profile, _ = UserProfile.objects.get_or_create(user=user)
        profile.role = role
        profile.save(update_fields=["role"])
        return user

    def _active_loan(self, *, reader, copy, due_date, librarian):
        if not Loan.objects.active().filter(copy=copy).exists():
            Loan.objects.create(
                reader=reader,
                copy=copy,
                due_date=due_date,
                loaned_by=librarian,
            )
