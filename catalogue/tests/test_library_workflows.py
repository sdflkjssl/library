from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from catalogue.forms import (
    LibrarianCreateForm,
    LibrarianUpdateForm,
    ReaderSignupForm,
    ReaderUpdateForm,
)
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
            reference_number="BK-CA",
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

    def test_reader_dashboard_redirects_to_my_loans(self):
        self.client.login(username="reader", password="pass")

        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("reader_loans"))

    def test_password_policy_requires_min_length_and_mixed_character_types(self):
        validate_password("Valid1!a")

        with self.assertRaises(ValidationError):
            validate_password("Aa1!")
        with self.assertRaises(ValidationError):
            validate_password("lowercase1!")
        with self.assertRaises(ValidationError):
            validate_password("NoNumber!")
        with self.assertRaises(ValidationError):
            validate_password("NoSymbol1")

    def test_account_username_forms_use_short_limit(self):
        for form_class in (
            ReaderSignupForm,
            LibrarianCreateForm,
            ReaderUpdateForm,
            LibrarianUpdateForm,
        ):
            form = form_class()
            self.assertEqual(form.fields["username"].max_length, 40)
            self.assertEqual(form.fields["username"].widget.attrs["maxlength"], "40")
            self.assertIn("40 characters or fewer", form.fields["username"].help_text)

        form = ReaderSignupForm(
            data={
                "username": "u" * 41,
                "first_name": "Long",
                "last_name": "Username",
                "email": "",
                "password1": "ValidPass1!",
                "password2": "ValidPass1!",
            }
        )

        self.assertFalse(form.is_valid())
        self.assertIn("40 characters", form.errors["username"][0])

    def test_theme_switcher_renders_on_public_pages(self):
        response = self.client.get(reverse("login"))

        self.assertContains(response, 'data-theme-option="system"')
        self.assertContains(response, 'data-theme-option="light"')
        self.assertContains(response, 'data-theme-option="dark"')

    def test_reader_pages_use_reader_view_label(self):
        self.client.login(username="reader", password="pass")

        response = self.client.get(reverse("reader_loans"))

        self.assertContains(response, "Reader View")

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

    def test_navigation_marks_current_page_without_linking_brand(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.get(reverse("librarian_dashboard"))

        self.assertContains(response, '<span class="brand">Library Desk</span>')
        self.assertNotContains(response, '<a class="brand"')
        self.assertContains(response, '<a class="active" href="/librarian/">Loans</a>')
        self.assertContains(response, "New Loan")
        self.assertNotContains(response, "New loan")

        response = self.client.get(reverse("book_copies_list"))

        self.assertContains(
            response,
            '<a class="active" href="/librarian/copies/">All Book Copies</a>',
        )

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

    def test_copy_search_filters_by_copy_number(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.get(reverse("api_copy_search"), {"q": "001"})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["meta"], "Copy CA-001")

    def test_librarian_can_search_readers_for_modal(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.get(reverse("api_reader_search"), {"q": "read"})

        self.assertEqual(response.status_code, 200)
        titles = [item["title"] for item in response.json()["items"]]
        self.assertIn("reader", titles)

    def test_loans_page_filters_active_and_overdue_loans(self):
        overdue_loan = Loan.objects.create(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() - timedelta(days=1),
            loaned_by=self.librarian,
        )
        active_loan = create_loan(
            reader=self.other_reader,
            copy=self.second_copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        self.client.login(username="librarian", password="pass")

        active_response = self.client.get(reverse("librarian_dashboard"), {"status": "active"})
        overdue_response = self.client.get(reverse("librarian_dashboard"), {"status": "overdue"})

        self.assertContains(active_response, "Active Loans")
        self.assertContains(active_response, "Book Copy")
        self.assertContains(active_response, "7d Left")
        self.assertContains(active_response, "1d Overdue")
        self.assertContains(active_response, overdue_loan.copy.inventory_code)
        self.assertContains(active_response, active_loan.copy.inventory_code)
        self.assertContains(overdue_response, "Overdue Loans")
        self.assertContains(overdue_response, overdue_loan.copy.inventory_code)
        self.assertNotContains(overdue_response, active_loan.copy.inventory_code)
        self.assertContains(overdue_response, "row-overdue")

    def test_book_copies_page_filters_available_and_all_copies(self):
        create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        self.client.login(username="librarian", password="pass")

        available_response = self.client.get(
            reverse("book_copies_list"),
            {"status": "available"},
        )
        all_response = self.client.get(reverse("book_copies_list"), {"status": "all"})

        self.assertContains(available_response, self.second_copy.inventory_code)
        self.assertNotContains(available_response, self.copy.inventory_code)
        self.assertContains(available_response, "All Book Copies")
        self.assertContains(available_response, "Available Book Copies")
        self.assertContains(all_response, self.copy.inventory_code)
        self.assertContains(all_response, self.second_copy.inventory_code)

    def test_librarian_can_create_book_with_initial_copies(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.post(
            reverse("book_create"),
            {
                "title": "Working Effectively with Legacy Code",
                "author": "Michael Feathers",
                "reference_number": "BK-LEG",
                "isbn": "9780131177055",
                "description": "Legacy code techniques.",
                "initial_copy_codes": "LEG-001, LEG-002",
            },
        )

        book = Book.objects.get(isbn="9780131177055")
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("book_detail", args=[book.id]))
        self.assertEqual(book.copies.count(), 2)

    def test_librarian_can_edit_book(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.post(
            reverse("book_update", args=[self.book.id]),
            {
                "title": "Clean Architecture Updated",
                "author": self.book.author,
                "reference_number": self.book.reference_number,
                "isbn": self.book.isbn,
                "description": "Updated description.",
            },
        )

        self.book.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.book.title, "Clean Architecture Updated")

    def test_book_identifiers_are_globally_unique_on_create_and_edit(self):
        other_book = Book.objects.create(
            title="Patterns of Enterprise Application Architecture",
            author="Martin Fowler",
            reference_number="BK-PEAA",
            isbn="9780321127426",
        )
        self.client.login(username="librarian", password="pass")

        duplicate_isbn_response = self.client.post(
            reverse("book_create"),
            {
                "title": "Duplicate ISBN",
                "author": "Someone",
                "reference_number": "BK-DUP-ISBN",
                "isbn": self.book.isbn,
                "description": "",
                "initial_copy_codes": "",
            },
        )
        duplicate_reference_response = self.client.post(
            reverse("book_create"),
            {
                "title": "Duplicate reference",
                "author": "Someone",
                "reference_number": self.book.reference_number,
                "isbn": "9780000000001",
                "description": "",
                "initial_copy_codes": "",
            },
        )
        duplicate_edit_response = self.client.post(
            reverse("book_update", args=[other_book.id]),
            {
                "title": other_book.title,
                "author": other_book.author,
                "reference_number": self.book.reference_number,
                "isbn": self.book.isbn,
                "description": "",
            },
        )

        other_book.refresh_from_db()
        self.assertEqual(duplicate_isbn_response.status_code, 200)
        self.assertEqual(duplicate_reference_response.status_code, 200)
        self.assertEqual(duplicate_edit_response.status_code, 200)
        self.assertFalse(Book.objects.filter(reference_number="BK-DUP-ISBN").exists())
        self.assertFalse(Book.objects.filter(isbn="9780000000001").exists())
        self.assertEqual(other_book.reference_number, "BK-PEAA")
        self.assertEqual(other_book.isbn, "9780321127426")

    def test_librarian_can_delete_book_without_loan_history(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.post(reverse("book_delete", args=[self.book.id]))

        self.assertEqual(response.status_code, 302)
        self.assertFalse(Book.objects.filter(id=self.book.id).exists())
        self.assertFalse(BookCopy.objects.filter(book_id=self.book.id).exists())

    def test_active_book_and_copy_cannot_be_edited_or_deleted(self):
        create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        self.client.login(username="librarian", password="pass")

        book_update_response = self.client.post(
            reverse("book_update", args=[self.book.id]),
            {
                "title": "Blocked update",
                "author": self.book.author,
                "reference_number": self.book.reference_number,
                "isbn": self.book.isbn,
                "description": "",
            },
        )
        book_delete_response = self.client.post(reverse("book_delete", args=[self.book.id]))
        copy_update_response = self.client.post(
            reverse("book_copy_update", args=[self.copy.id]),
            {"inventory_code": "CA-001X"},
        )
        copy_delete_response = self.client.post(reverse("book_copy_delete", args=[self.copy.id]))

        self.book.refresh_from_db()
        self.copy.refresh_from_db()
        self.assertEqual(book_update_response.url, reverse("book_detail", args=[self.book.id]))
        self.assertEqual(book_delete_response.url, reverse("book_detail", args=[self.book.id]))
        self.assertEqual(copy_update_response.url, reverse("copy_detail", args=[self.copy.id]))
        self.assertEqual(copy_delete_response.url, reverse("copy_detail", args=[self.copy.id]))
        self.assertEqual(self.book.title, "Clean Architecture")
        self.assertEqual(self.copy.inventory_code, "CA-001")
        self.assertTrue(Book.objects.filter(id=self.book.id).exists())
        self.assertTrue(BookCopy.objects.filter(id=self.copy.id).exists())

    def test_active_book_and_copy_actions_are_hidden(self):
        create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        self.client.login(username="librarian", password="pass")

        book_response = self.client.get(reverse("book_detail", args=[self.book.id]))
        copy_response = self.client.get(reverse("copy_detail", args=[self.copy.id]))
        copies_response = self.client.get(reverse("book_copies_list"), {"status": "all"})

        self.assertNotContains(book_response, reverse("book_update", args=[self.book.id]))
        self.assertNotContains(book_response, reverse("book_delete", args=[self.book.id]))
        self.assertNotContains(book_response, reverse("book_copy_update", args=[self.copy.id]))
        self.assertNotContains(book_response, reverse("book_copy_delete", args=[self.copy.id]))
        self.assertNotContains(copy_response, reverse("book_copy_update", args=[self.copy.id]))
        self.assertNotContains(copy_response, reverse("book_copy_delete", args=[self.copy.id]))
        self.assertNotContains(copies_response, reverse("book_copy_update", args=[self.copy.id]))
        self.assertNotContains(copies_response, reverse("book_copy_delete", args=[self.copy.id]))

    def test_librarian_can_add_edit_and_delete_book_copy(self):
        self.client.login(username="librarian", password="pass")

        create_response = self.client.post(
            reverse("book_copy_create", args=[self.book.id]),
            {"inventory_code": "CA-003"},
        )
        copy = BookCopy.objects.get(inventory_code="CA-003")

        update_response = self.client.post(
            reverse("book_copy_update", args=[copy.id]),
            {"inventory_code": "CA-003A"},
        )
        copy.refresh_from_db()

        delete_response = self.client.post(reverse("book_copy_delete", args=[copy.id]))

        self.assertEqual(create_response.status_code, 302)
        self.assertEqual(update_response.status_code, 302)
        self.assertEqual(copy.inventory_code, "CA-003A")
        self.assertFalse(BookCopy.objects.filter(id=copy.id).exists())
        self.assertEqual(delete_response.url, reverse("book_detail", args=[self.book.id]))

    def test_book_copy_number_is_globally_unique_on_create_and_edit(self):
        self.client.login(username="librarian", password="pass")

        duplicate_create_response = self.client.post(
            reverse("book_copy_create", args=[self.book.id]),
            {"inventory_code": self.copy.inventory_code},
        )
        duplicate_edit_response = self.client.post(
            reverse("book_copy_update", args=[self.second_copy.id]),
            {"inventory_code": self.copy.inventory_code},
        )

        self.second_copy.refresh_from_db()
        self.assertEqual(duplicate_create_response.status_code, 200)
        self.assertEqual(duplicate_edit_response.status_code, 200)
        self.assertEqual(self.second_copy.inventory_code, "CA-002")
        self.assertEqual(
            BookCopy.objects.filter(inventory_code=self.copy.inventory_code).count(),
            1,
        )

    def test_book_copy_with_loan_history_cannot_be_deleted(self):
        loan = create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        return_loan(loan=loan, returned_by=self.librarian)
        self.client.login(username="librarian", password="pass")

        response = self.client.post(reverse("book_copy_delete", args=[self.copy.id]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(BookCopy.objects.filter(id=self.copy.id).exists())

    def test_readers_page_lists_readers_and_links_to_reader_loans(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.get(reverse("readers_list"))

        self.assertContains(response, "Readers")
        self.assertContains(response, reverse("librarian_reader_loans", args=[self.reader.id]))
        self.assertContains(response, reverse("reader_update", args=[self.reader.id]))
        self.assertContains(response, reverse("reader_delete", args=[self.reader.id]))

    def test_librarian_can_edit_and_delete_reader_account(self):
        User = get_user_model()
        self.client.login(username="librarian", password="pass")

        update_response = self.client.post(
            reverse("reader_update", args=[self.other_reader.id]),
            {
                "username": "other-updated",
                "first_name": "Other",
                "last_name": "Updated",
                "email": "other@example.com",
            },
        )
        self.other_reader.refresh_from_db()
        role = self.other_reader.profile.role
        form_response = self.client.get(reverse("reader_update", args=[self.other_reader.id]))
        delete_response = self.client.post(
            reverse("reader_delete", args=[self.other_reader.id])
        )

        self.assertEqual(update_response.status_code, 302)
        self.assertEqual(
            update_response.url,
            reverse("librarian_reader_loans", args=[self.other_reader.id]),
        )
        self.assertEqual(self.other_reader.username, "other-updated")
        self.assertEqual(role, UserProfile.Role.READER)
        self.assertNotContains(form_response, "is_active")
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(User.objects.filter(username="other-updated").exists())

    def test_reader_with_active_loans_cannot_be_deleted(self):
        create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        self.client.login(username="librarian", password="pass")

        response = self.client.post(reverse("reader_delete", args=[self.reader.id]))

        self.assertEqual(
            response.url,
            reverse("librarian_reader_loans", args=[self.reader.id]),
        )
        self.assertTrue(get_user_model().objects.filter(id=self.reader.id).exists())

    def test_reader_with_only_returned_loans_can_be_deleted(self):
        User = get_user_model()
        loan = create_loan(
            reader=self.other_reader,
            copy=self.copy,
            due_date=timezone.localdate() - timedelta(days=2),
            loaned_by=self.librarian,
        )
        return_loan(loan=loan, returned_by=self.librarian)
        self.client.login(username="librarian", password="pass")

        list_response = self.client.get(reverse("readers_list"))
        response = self.client.post(reverse("reader_delete", args=[self.other_reader.id]))
        loan.refresh_from_db()

        self.assertContains(list_response, reverse("reader_delete", args=[self.other_reader.id]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(User.objects.filter(id=self.other_reader.id).exists())
        self.assertIsNone(loan.reader)

    def test_loan_creation_view_accepts_search_picker_ids(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.post(
            reverse("loan_create"),
            {
                "reader": self.reader.id,
                "copy": self.copy.id,
                "due_date": timezone.localdate() - timedelta(days=1),
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("librarian_dashboard"))
        self.assertTrue(Loan.objects.active().filter(reader=self.reader, copy=self.copy).exists())
        self.assertTrue(Loan.objects.get(reader=self.reader, copy=self.copy).is_overdue)

    def test_loan_due_date_update_and_return_redirect_to_loans_page(self):
        loan = create_loan(
            reader=self.reader,
            copy=self.copy,
            due_date=timezone.localdate() + timedelta(days=7),
            loaned_by=self.librarian,
        )
        new_due_date = timezone.localdate() - timedelta(days=3)
        self.client.login(username="librarian", password="pass")

        update_response = self.client.post(
            reverse("loan_due_date", args=[loan.id]),
            {"due_date": new_due_date},
        )
        loan.refresh_from_db()
        return_response = self.client.post(reverse("loan_return", args=[loan.id]))
        loan.refresh_from_db()

        self.assertEqual(update_response.status_code, 302)
        self.assertEqual(update_response.url, reverse("librarian_dashboard"))
        self.assertEqual(loan.due_date, new_due_date)
        self.assertEqual(return_response.status_code, 302)
        self.assertEqual(return_response.url, reverse("librarian_dashboard"))
        self.assertIsNotNone(loan.returned_at)

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

    def test_user_email_must_be_unique_across_account_forms(self):
        self.reader.email = "taken@example.com"
        self.reader.save(update_fields=["email"])

        signup_form = ReaderSignupForm(
            data={
                "username": "duplicate-email-reader",
                "first_name": "Duplicate",
                "last_name": "Reader",
                "email": "TAKEN@example.com",
                "password1": "ValidPass1!",
                "password2": "ValidPass1!",
            }
        )
        librarian_form = LibrarianCreateForm(
            data={
                "username": "duplicate-email-librarian",
                "first_name": "Duplicate",
                "last_name": "Librarian",
                "email": "taken@example.com",
                "password1": "ValidPass1!",
                "password2": "ValidPass1!",
            }
        )
        update_form = ReaderUpdateForm(
            data={
                "username": self.other_reader.username,
                "first_name": self.other_reader.first_name,
                "last_name": self.other_reader.last_name,
                "email": "taken@example.com",
            },
            instance=self.other_reader,
        )

        self.assertFalse(signup_form.is_valid())
        self.assertFalse(librarian_form.is_valid())
        self.assertFalse(update_form.is_valid())
        self.assertIn("already used", signup_form.errors["email"][0])
        self.assertIn("already used", librarian_form.errors["email"][0])
        self.assertIn("already used", update_form.errors["email"][0])

    def test_signup_password_help_has_no_bullet_list(self):
        response = self.client.get(reverse("signup"))

        self.assertContains(response, "Your password must be at least 8 characters")
        self.assertNotContains(response, "<li>Your password must")
        self.assertNotContains(response, "<ul>")

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

    def test_librarian_can_create_edit_and_delete_librarian_account(self):
        User = get_user_model()
        self.client.login(username="librarian", password="pass")

        create_response = self.client.post(
            reverse("librarian_create"),
            {
                "username": "assistant",
                "first_name": "Desk",
                "last_name": "Assistant",
                "email": "assistant@example.com",
                "password1": "AssistantPass987!",
                "password2": "AssistantPass987!",
            },
        )
        librarian = User.objects.get(username="assistant")

        update_response = self.client.post(
            reverse("librarian_update", args=[librarian.id]),
            {
                "username": "assistant",
                "first_name": "Updated",
                "last_name": "Assistant",
                "email": "updated@example.com",
            },
        )
        librarian.refresh_from_db()
        role = librarian.profile.role

        list_response = self.client.get(reverse("librarians_list"))
        form_response = self.client.get(reverse("librarian_update", args=[librarian.id]))
        delete_response = self.client.post(reverse("librarian_delete", args=[librarian.id]))

        self.assertEqual(create_response.status_code, 302)
        self.assertEqual(role, UserProfile.Role.LIBRARIAN)
        self.assertEqual(update_response.status_code, 302)
        self.assertEqual(librarian.first_name, "Updated")
        self.assertContains(list_response, "(myself)")
        self.assertNotContains(list_response, "<th>Status</th>")
        self.assertNotContains(form_response, "is_active")
        self.assertContains(list_response, reverse("librarian_update", args=[librarian.id]))
        self.assertContains(list_response, reverse("librarian_delete", args=[librarian.id]))
        self.assertEqual(delete_response.status_code, 302)
        self.assertFalse(User.objects.filter(username="assistant").exists())

    def test_librarian_cannot_delete_own_account(self):
        self.client.login(username="librarian", password="pass")

        response = self.client.post(reverse("librarian_delete", args=[self.librarian.id]))

        self.assertEqual(response.status_code, 302)
        self.assertTrue(get_user_model().objects.filter(id=self.librarian.id).exists())
