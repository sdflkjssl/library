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

        self.assertContains(response, "1/2")
        self.assertContains(response, reverse("book_detail", args=[self.book.id]))

    def test_librarian_can_search_available_copies_for_modal(self):
        create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        self.client.login(username="librarian", password="pass")

        response = self.client.get(reverse("api_copy_search"), {"q": "Clean"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["meta"], "Copy CA-002")
        self.assertEqual(payload["items"][0]["availability"], "1/2")

    def test_librarian_can_search_readers_for_modal(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.get(reverse("api_reader_search"), {"q": "read"})

        self.assertEqual(response.status_code, 200)
        titles = [item["title"] for item in response.json()["items"]]
        self.assertIn("reader", titles)

    def test_loan_creation_view_accepts_search_picker_ids(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.post(
            reverse("loan_create"),
            {
                "reader": self.reader.id,
                "copy": self.copy.id,
                "due_date": timezone.localdate() + timedelta(days=7),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(Loan.objects.active().filter(reader=self.reader, copy=self.copy).exists())

    def test_signup_creates_reader_account(self):
        User = get_user_model()

        response = self.client.post(
            reverse("signup"),
            {
                "username": "newreader",
                "first_name": "New",
                "last_name": "Reader",
                "email": "new@example.com",
                "password1": "NewReaderDemo123!",
                "password2": "NewReaderDemo123!",
            },
        )

        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="newreader")
        self.assertEqual(user.profile.role, UserProfile.Role.READER)

    def test_librarian_can_create_reader_without_switching_session(self):
        User = get_user_model()
        self.client.login(username="librarian", password="pass")

        response = self.client.post(
            reverse("signup"),
            {
                "username": "deskreader",
                "first_name": "Desk",
                "last_name": "Reader",
                "email": "",
                "password1": "SecureLibraryPass987!",
                "password2": "SecureLibraryPass987!",
            },
        )

        user = User.objects.get(username="deskreader")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("librarian_reader_loans", args=[user.id]))
        self.assertEqual(user.profile.role, UserProfile.Role.READER)
