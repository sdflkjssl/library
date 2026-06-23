from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogue.models import Book, BookCopy, Loan, UserProfile
from catalogue.services import change_due_date, create_loan, return_loan


class LibraryWorkflowTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.reader = User.objects.create_user("reader", password="pass")
        self.reader.profile.role = UserProfile.Role.READER
        self.reader.profile.save()

        self.other_reader = User.objects.create_user("other", password="pass")
        self.other_reader.profile.role = UserProfile.Role.READER
        self.other_reader.profile.save()

        self.librarian = User.objects.create_user("librarian", password="pass")
        self.librarian.profile.role = UserProfile.Role.LIBRARIAN
        self.librarian.profile.save()

        self.book = Book.objects.create(
            title="Clean Architecture",
            author="Robert C. Martin",
            isbn="9780134494166",
        )
        self.copy = BookCopy.objects.create(book=self.book, inventory_code="CA-001")
        self.second_copy = BookCopy.objects.create(
            book=self.book,
            inventory_code="CA-002",
        )

    def test_reader_can_only_view_their_own_loans(self):
        loan = create_loan(
            reader=self.other_reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )

        self.client.login(username="reader", password="pass")
        response = self.client.get(reverse("reader_loans"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, loan.copy.inventory_code)

    def test_librarian_can_create_valid_loan(self):
        loan = create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )

        self.assertEqual(loan.reader, self.reader)
        self.assertTrue(Loan.objects.active().filter(copy=self.copy).exists())

    def test_unavailable_copy_cannot_be_loaned_twice(self):
        due_date = timezone.localdate() + timedelta(days=7)
        create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=due_date,
            loaned_by=self.librarian,
        )

        with self.assertRaises(ValidationError):
            create_loan(
                reader=self.other_reader,
                copy=self.copy,
                due_date=due_date,
                loaned_by=self.librarian,
            )

    def test_returning_loan_restores_copy_availability(self):
        loan = create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )

        return_loan(loan=loan, returned_by=self.librarian)

        self.assertFalse(Loan.objects.active().filter(copy=self.copy).exists())
        self.assertIn(self.copy, list(BookCopy.objects.available()))

    def test_due_date_change_only_applies_to_active_loan(self):
        loan = create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        new_due_date = timezone.localdate() + timedelta(days=14)

        changed = change_due_date(loan=loan, due_date=new_due_date)

        self.assertEqual(changed.due_date, new_due_date)

    def test_reader_cannot_access_librarian_views(self):
        self.client.login(username="reader", password="pass")

        response = self.client.get(reverse("librarian_dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_librarian_catalogue_shows_availability_counts(self):
        create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        self.client.login(username="librarian", password="pass")

        response = self.client.get(reverse("catalogue"), {"q": "Clean"})

        self.assertContains(response, "1 available")
        self.assertContains(response, "2 total")
