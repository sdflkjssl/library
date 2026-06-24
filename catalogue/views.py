from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.deletion import ProtectedError
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    BookCopyForm,
    BookCreateForm,
    BookForm,
    CatalogueSearchForm,
    DueDateForm,
    LibrarianCreateForm,
    LibrarianUpdateForm,
    LoanCreateForm,
    ReaderUpdateForm,
    ReaderSignupForm,
)
from .models import Book, BookCopy, Loan, UserProfile
from .permissions import is_librarian, is_reader, librarian_required, reader_required
from .services import change_due_date, create_loan, return_loan


User = get_user_model()


def _book_availability_label(book):
    return f"{book.available_copies}/{book.total_copies}"


def _book_availability_class(book):
    return "success" if book.available_copies > 0 else "danger"


def _user_display(user):
    return user.get_full_name() or user.get_username()


def _librarians():
    return User.objects.filter(profile__role=UserProfile.Role.LIBRARIAN)


def _readers():
    return User.objects.filter(profile__role=UserProfile.Role.READER)


def _book_has_active_loans(book):
    return Loan.objects.active().filter(copy__book=book).exists()


def _copy_has_active_loan(copy):
    return Loan.objects.active().filter(copy=copy).exists()


def _copy_has_loan_history(copy):
    return Loan.objects.filter(copy=copy).exists()


def signup(request):
    librarian_creating_reader = is_librarian(request.user)
    if request.user.is_authenticated and not librarian_creating_reader:
        return redirect("dashboard")

    form = ReaderSignupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        if librarian_creating_reader:
            messages.success(request, f"Reader account created for {_user_display(user)}.")
            return redirect("librarian_reader_loans", reader_id=user.id)
        login(request, user)
        messages.success(request, "Your reader account has been created.")
        return redirect("dashboard")
    return render(
        request,
        "registration/signup.html",
        {"form": form, "librarian_creating_reader": librarian_creating_reader},
    )


@login_required
def dashboard(request):
    if is_librarian(request.user):
        return redirect("librarian_dashboard")
    if is_reader(request.user):
        return redirect("reader_loans")
    raise Http404("Unknown user role")


@login_required
def catalogue_search(request):
    form = CatalogueSearchForm(request.GET or None)
    query = ""
    if form.is_valid():
        query = form.cleaned_data["q"].strip()

    books = Book.objects.with_availability().search(query).order_by("title", "author")
    return render(
        request,
        "catalogue/catalogue.html",
        {"form": form, "books": books, "query": query},
    )


@librarian_required
def book_create(request):
    form = BookCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            book = form.save()
            for code in form.cleaned_data["initial_copy_codes"]:
                BookCopy.objects.create(book=book, inventory_code=code)
        messages.success(request, f"Book created: {book.title}.")
        return redirect("book_detail", book_id=book.id)
    return render(
        request,
        "catalogue/book_form.html",
        {"form": form, "title": "Add Book", "submit_label": "Add Book"},
    )


@librarian_required
def book_update(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    if _book_has_active_loans(book):
        messages.error(
            request,
            "This book cannot be edited while one or more copies are on loan.",
        )
        return redirect("book_detail", book_id=book.id)
    form = BookForm(request.POST or None, instance=book)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Book updated.")
        return redirect("book_detail", book_id=book.id)
    return render(
        request,
        "catalogue/book_form.html",
        {
            "form": form,
            "book": book,
            "title": "Edit Book",
            "submit_label": "Save Book",
        },
    )


@librarian_required
def book_delete(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    if _book_has_active_loans(book):
        messages.error(
            request,
            "This book cannot be deleted while one or more copies are on loan.",
        )
        return redirect("book_detail", book_id=book.id)
    if request.method == "POST":
        title = book.title
        try:
            book.delete()
        except ProtectedError:
            messages.error(
                request,
                "This book cannot be deleted because one or more copies have loan history.",
            )
            return redirect("book_detail", book_id=book.id)
        messages.success(request, f"Deleted {title}.")
        return redirect("catalogue")
    return render(
        request,
        "catalogue/confirm_delete.html",
        {
            "title": "Delete Book",
            "object_name": book.title,
            "cancel_href": reverse("book_detail", args=[book.id]),
        },
    )


@login_required
def book_detail(request, book_id):
    book = get_object_or_404(Book.objects.with_availability(), pk=book_id)
    copies = BookCopy.objects.filter(book=book).with_active_loan_flag().select_related("book")
    active_loans = {
        loan.copy_id: loan
        for loan in Loan.objects.active()
        .filter(copy__book=book)
        .select_related("reader", "copy")
    }
    loan_history_copy_ids = set(
        Loan.objects.filter(copy__book=book).values_list("copy_id", flat=True)
    )
    copy_rows = [
        {
            "copy": copy,
            "loan": active_loans.get(copy.id),
            "has_loan_history": copy.id in loan_history_copy_ids,
        }
        for copy in copies
    ]
    can_edit = is_librarian(request.user)
    book_has_active_loans = bool(active_loans)
    book_has_loan_history = bool(loan_history_copy_ids)
    return render(
        request,
        "catalogue/book_detail.html",
        {
            "book": book,
            "copy_rows": copy_rows,
            "availability_label": _book_availability_label(book),
            "availability_class": _book_availability_class(book),
            "can_view_readers": can_edit,
            "can_edit": can_edit,
            "can_modify_book": can_edit and not book_has_active_loans,
            "can_delete_book": can_edit
            and not book_has_active_loans
            and not book_has_loan_history,
        },
    )


@login_required
def copy_detail(request, copy_id):
    copy = get_object_or_404(BookCopy.objects.select_related("book"), pk=copy_id)
    book = Book.objects.with_availability().get(pk=copy.book_id)
    active_loan = (
        Loan.objects.active()
        .filter(copy=copy)
        .select_related("reader", "copy", "copy__book")
        .first()
    )
    can_view_loan = bool(
        active_loan
        and (is_librarian(request.user) or active_loan.reader_id == request.user.id)
    )
    can_edit = is_librarian(request.user)
    has_loan_history = _copy_has_loan_history(copy)
    return render(
        request,
        "catalogue/copy_detail.html",
        {
            "copy": copy,
            "book": book,
            "active_loan": active_loan,
            "can_view_loan": can_view_loan,
            "availability_label": _book_availability_label(book),
            "availability_class": _book_availability_class(book),
            "can_view_readers": can_edit,
            "can_edit": can_edit,
            "can_modify_copy": can_edit and not active_loan,
            "can_delete_copy": can_edit and not active_loan and not has_loan_history,
        },
    )


@librarian_required
def book_copy_create(request, book_id):
    book = get_object_or_404(Book, pk=book_id)
    form = BookCopyForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        copy = form.save(commit=False)
        copy.book = book
        copy.save()
        messages.success(request, f"Book copy {copy.inventory_code} added.")
        return redirect("book_detail", book_id=book.id)
    return render(
        request,
        "catalogue/book_copy_form.html",
        {
            "form": form,
            "book": book,
            "title": "Add Book Copy",
            "submit_label": "Add Copy",
        },
    )


@librarian_required
def book_copy_update(request, copy_id):
    copy = get_object_or_404(BookCopy.objects.select_related("book"), pk=copy_id)
    if _copy_has_active_loan(copy):
        messages.error(request, "This book copy cannot be edited while it is on loan.")
        return redirect("copy_detail", copy_id=copy.id)
    form = BookCopyForm(request.POST or None, instance=copy)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Book copy updated.")
        return redirect("copy_detail", copy_id=copy.id)
    return render(
        request,
        "catalogue/book_copy_form.html",
        {
            "form": form,
            "copy": copy,
            "book": copy.book,
            "title": "Edit Book Copy",
            "submit_label": "Save Copy",
        },
    )


@librarian_required
def book_copy_delete(request, copy_id):
    copy = get_object_or_404(BookCopy.objects.select_related("book"), pk=copy_id)
    if _copy_has_active_loan(copy):
        messages.error(request, "This book copy cannot be deleted while it is on loan.")
        return redirect("copy_detail", copy_id=copy.id)
    book_id = copy.book_id
    if request.method == "POST":
        code = copy.inventory_code
        try:
            copy.delete()
        except ProtectedError:
            messages.error(
                request,
                "This book copy cannot be deleted because it has loan history.",
            )
            return redirect("copy_detail", copy_id=copy.id)
        messages.success(request, f"Deleted copy {code}.")
        return redirect("book_detail", book_id=book_id)
    return render(
        request,
        "catalogue/confirm_delete.html",
        {
            "title": "Delete Book Copy",
            "object_name": copy.inventory_code,
            "cancel_href": reverse("copy_detail", args=[copy.id]),
        },
    )


@reader_required
def reader_loans(request):
    active_loans = (
        Loan.objects.active()
        .filter(reader=request.user)
        .select_related("copy", "copy__book")
        .order_by("due_date")
    )
    returned_loans = (
        Loan.objects.returned()
        .filter(reader=request.user)
        .select_related("copy", "copy__book")
        .order_by("-returned_at")[:10]
    )
    return render(
        request,
        "catalogue/reader_loans.html",
        {
            "active_loans": active_loans,
            "returned_loans": returned_loans,
            "today": timezone.localdate(),
        },
    )


@librarian_required
def librarian_dashboard(request):
    status = request.GET.get("status", "active")
    loans = Loan.objects.active().select_related("reader", "copy", "copy__book")
    if status == "overdue":
        loans = loans.filter(due_date__lt=timezone.localdate())
        list_title = "Overdue Loans"
    else:
        status = "active"
        list_title = "Active Loans"

    stats = {
        "active_loans": Loan.objects.active().count(),
        "overdue_loans": Loan.objects.overdue().count(),
        "available_copies": sum(
            book.available_copies for book in Book.objects.with_availability()
        ),
        "readers": User.objects.filter(profile__role=UserProfile.Role.READER).count(),
    }
    return render(
        request,
        "catalogue/librarian_dashboard.html",
        {
            "loans": loans.order_by("due_date", "reader__last_name", "reader__username"),
            "list_title": list_title,
            "status": status,
            "stats": stats,
        },
    )


@librarian_required
def readers_list(request):
    query = request.GET.get("q", "").strip()
    readers = _readers()
    if query:
        readers = readers.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
    readers = readers.annotate(
        loan_count=Count("loans", distinct=True),
        active_loan_count=Count(
            "loans",
            filter=Q(loans__returned_at__isnull=True),
            distinct=True,
        ),
        overdue_loan_count=Count(
            "loans",
            filter=Q(
                loans__returned_at__isnull=True,
                loans__due_date__lt=timezone.localdate(),
            ),
            distinct=True,
        ),
    ).order_by("last_name", "first_name", "username")
    return render(
        request,
        "catalogue/readers_list.html",
        {"readers": readers, "query": query},
    )


@librarian_required
def reader_update(request, user_id):
    reader = get_object_or_404(_readers(), pk=user_id)
    form = ReaderUpdateForm(request.POST or None, instance=reader)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Reader account updated.")
        return redirect("librarian_reader_loans", reader_id=reader.id)
    return render(
        request,
        "catalogue/reader_form.html",
        {
            "form": form,
            "reader": reader,
            "title": "Edit Reader",
            "submit_label": "Save Reader",
        },
    )


@librarian_required
def reader_delete(request, user_id):
    reader = get_object_or_404(_readers(), pk=user_id)
    if Loan.objects.active().filter(reader=reader).exists():
        messages.error(request, "This reader cannot be deleted while they have active loans.")
        return redirect("librarian_reader_loans", reader_id=reader.id)
    if request.method == "POST":
        name = _user_display(reader)
        try:
            reader.delete()
        except ProtectedError:
            messages.error(
                request,
                "This reader cannot be deleted because they have loan history.",
            )
            return redirect("readers_list")
        messages.success(request, f"Deleted reader account for {name}.")
        return redirect("readers_list")
    return render(
        request,
        "catalogue/confirm_delete.html",
        {
            "title": "Delete Reader",
            "object_name": _user_display(reader),
            "cancel_href": reverse("readers_list"),
        },
    )


@librarian_required
def librarians_list(request):
    query = request.GET.get("q", "").strip()
    librarians = _librarians()
    if query:
        librarians = librarians.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
    librarians = librarians.order_by("last_name", "first_name", "username")
    return render(
        request,
        "catalogue/librarians_list.html",
        {"librarians": librarians, "query": query},
    )


@librarian_required
def librarian_create(request):
    form = LibrarianCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        librarian = form.save()
        messages.success(request, f"Librarian account created for {_user_display(librarian)}.")
        return redirect("librarians_list")
    return render(
        request,
        "catalogue/librarian_form.html",
        {
            "form": form,
            "title": "Add Librarian",
            "submit_label": "Add Librarian",
        },
    )


@librarian_required
def librarian_update(request, user_id):
    librarian = get_object_or_404(_librarians(), pk=user_id)
    form = LibrarianUpdateForm(request.POST or None, instance=librarian)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Librarian account updated.")
        return redirect("librarians_list")
    return render(
        request,
        "catalogue/librarian_form.html",
        {
            "form": form,
            "librarian": librarian,
            "title": "Edit Librarian",
            "submit_label": "Save Librarian",
        },
    )


@librarian_required
def librarian_delete(request, user_id):
    librarian = get_object_or_404(_librarians(), pk=user_id)
    if librarian.id == request.user.id:
        messages.error(request, "You cannot delete your own librarian account.")
        return redirect("librarians_list")
    if request.method == "POST":
        name = _user_display(librarian)
        librarian.delete()
        messages.success(request, f"Deleted librarian account for {name}.")
        return redirect("librarians_list")
    return render(
        request,
        "catalogue/confirm_delete.html",
        {
            "title": "Delete Librarian",
            "object_name": _user_display(librarian),
            "cancel_href": reverse("librarians_list"),
        },
    )


@librarian_required
def book_copies_list(request):
    status = request.GET.get("status", "all")
    if status == "available":
        copies = BookCopy.objects.available().select_related("book")
        title = "Available Book Copies"
    else:
        status = "all"
        copies = BookCopy.objects.with_active_loan_flag().select_related("book")
        title = "All Book Copies"

    active_loans = {
        loan.copy_id: loan
        for loan in Loan.objects.active()
        .filter(copy_id__in=copies.values("id"))
        .select_related("reader", "copy", "copy__book")
    }
    loan_history_copy_ids = set(
        Loan.objects.filter(copy_id__in=copies.values("id")).values_list(
            "copy_id",
            flat=True,
        )
    )
    copy_rows = [
        {
            "copy": copy,
            "loan": active_loans.get(copy.id),
            "has_loan_history": copy.id in loan_history_copy_ids,
        }
        for copy in copies.order_by("book__title", "inventory_code")
    ]
    return render(
        request,
        "catalogue/book_copies_list.html",
        {"copy_rows": copy_rows, "status": status, "title": title},
    )


@librarian_required
def loan_create(request):
    form = LoanCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            loan = create_loan(
                reader=form.cleaned_data["reader"],
                copy=form.cleaned_data["copy"],
                due_date=form.cleaned_data["due_date"],
                loaned_by=request.user,
            )
        except ValidationError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(
                request,
                f"Loan registered for {loan.reader_display}.",
            )
            return redirect("librarian_dashboard")

    return render(request, "catalogue/loan_form.html", {"form": form})


@librarian_required
def librarian_reader_loans(request, reader_id):
    reader = get_object_or_404(
        _readers(),
        pk=reader_id,
    )
    active_loans = (
        Loan.objects.active()
        .filter(reader=reader)
        .select_related("copy", "copy__book")
        .order_by("due_date")
    )
    reader_has_active_loans = active_loans.exists()
    returned_loans = (
        Loan.objects.returned()
        .filter(reader=reader)
        .select_related("copy", "copy__book")
        .order_by("-returned_at")[:15]
    )
    return render(
        request,
        "catalogue/librarian_reader_loans.html",
        {
            "reader": reader,
            "active_loans": active_loans,
            "returned_loans": returned_loans,
            "can_delete_reader": not reader_has_active_loans,
            "today": timezone.localdate(),
        },
    )


@require_POST
@librarian_required
def loan_return(request, loan_id):
    loan = get_object_or_404(
        Loan.objects.active().select_related("reader", "copy", "copy__book"),
        pk=loan_id,
    )
    try:
        return_loan(loan=loan, returned_by=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f"Returned {loan.copy.book.title}.")
    return redirect("librarian_dashboard")


@librarian_required
def loan_due_date(request, loan_id):
    loan = get_object_or_404(
        Loan.objects.active().select_related("reader", "copy", "copy__book"),
        pk=loan_id,
    )
    form = DueDateForm(request.POST or None, initial={"due_date": loan.due_date})
    if request.method == "POST" and form.is_valid():
        try:
            change_due_date(loan=loan, due_date=form.cleaned_data["due_date"])
        except ValidationError as exc:
            form.add_error(None, exc.message)
        else:
            messages.success(request, "Due date updated.")
            return redirect("librarian_dashboard")
    return render(request, "catalogue/loan_due_date.html", {"form": form, "loan": loan})


@librarian_required
def reader_search_api(request):
    query = request.GET.get("q", "").strip()
    readers = _readers()
    if query:
        readers = readers.filter(
            Q(username__icontains=query)
            | Q(first_name__icontains=query)
            | Q(last_name__icontains=query)
            | Q(email__icontains=query)
        )
    readers = readers.annotate(
        active_loan_count=Count("loans", filter=Q(loans__returned_at__isnull=True))
    ).order_by("last_name", "first_name", "username")[:20]
    return JsonResponse(
        {
            "items": [
                {
                    "id": reader.id,
                    "title": _user_display(reader),
                    "subtitle": reader.get_username(),
                    "meta": f"{reader.active_loan_count} active loan"
                    f"{'' if reader.active_loan_count == 1 else 's'}",
                }
                for reader in readers
            ]
        }
    )


@librarian_required
def copy_search_api(request):
    query = request.GET.get("q", "").strip()
    copies = BookCopy.objects.available().select_related("book")
    if query:
        copy_number_matches = copies.filter(inventory_code__icontains=query)
        if copy_number_matches.exists():
            copies = copy_number_matches
        else:
            copies = copies.filter(
                Q(book__title__icontains=query)
                | Q(book__author__icontains=query)
                | Q(book__reference_number__icontains=query)
                | Q(book__isbn__icontains=query)
        )
    copies = list(copies.order_by("book__title", "inventory_code")[:20])
    book_ids = {copy.book_id for copy in copies}
    availability_by_book_id = {
        book.id: book for book in Book.objects.with_availability().filter(id__in=book_ids)
    }
    return JsonResponse(
        {
            "items": [
                {
                    "id": copy.id,
                    "title": copy.book.title,
                    "subtitle": copy.book.author,
                    "meta": f"Copy {copy.inventory_code}",
                    "availability": _book_availability_label(
                        availability_by_book_id[copy.book_id]
                    ),
                    "availabilityClass": _book_availability_class(
                        availability_by_book_id[copy.book_id]
                    ),
                }
                for copy in copies
            ]
        }
    )
