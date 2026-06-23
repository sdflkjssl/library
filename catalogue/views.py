from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import (
    CatalogueSearchForm,
    DueDateForm,
    LoanCreateForm,
    ReaderLookupForm,
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
        active_loans = (
            Loan.objects.active()
            .filter(reader=request.user)
            .select_related("copy", "copy__book")
            .order_by("due_date")[:5]
        )
        return render(
            request,
            "catalogue/reader_dashboard.html",
            {"active_loans": active_loans},
        )
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
    copy_rows = [{"copy": copy, "loan": active_loans.get(copy.id)} for copy in copies]
    return render(
        request,
        "catalogue/book_detail.html",
        {
            "book": book,
            "copy_rows": copy_rows,
            "availability_label": _book_availability_label(book),
            "availability_class": _book_availability_class(book),
            "can_view_readers": is_librarian(request.user),
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
            "can_view_readers": is_librarian(request.user),
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
    active_loans = (
        Loan.objects.active()
        .select_related("reader", "copy", "copy__book")
        .order_by("due_date")[:12]
    )
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
            "active_loans": active_loans,
            "reader_lookup_form": ReaderLookupForm(),
            "stats": stats,
        },
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
                f"Loan registered for {loan.reader.get_username()}.",
            )
            return redirect("librarian_reader_loans", reader_id=loan.reader_id)

    return render(request, "catalogue/loan_form.html", {"form": form})


@librarian_required
def reader_lookup(request):
    form = ReaderLookupForm(request.GET or None)
    if form.is_valid():
        reader = form.cleaned_data["reader"]
        return redirect("librarian_reader_loans", reader_id=reader.pk)
    return render(request, "catalogue/reader_lookup.html", {"form": form})


@librarian_required
def librarian_reader_loans(request, reader_id):
    reader = get_object_or_404(
        User.objects.filter(profile__role=UserProfile.Role.READER),
        pk=reader_id,
    )
    active_loans = (
        Loan.objects.active()
        .filter(reader=reader)
        .select_related("copy", "copy__book")
        .order_by("due_date")
    )
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
    reader_id = loan.reader_id
    try:
        return_loan(loan=loan, returned_by=request.user)
    except ValidationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(request, f"Returned {loan.copy.book.title}.")
    return redirect("librarian_reader_loans", reader_id=reader_id)


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
            return redirect("librarian_reader_loans", reader_id=loan.reader_id)
    return render(request, "catalogue/loan_due_date.html", {"form": form, "loan": loan})


@librarian_required
def reader_search_api(request):
    query = request.GET.get("q", "").strip()
    readers = User.objects.filter(profile__role=UserProfile.Role.READER)
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
        copies = copies.filter(
            Q(inventory_code__icontains=query)
            | Q(book__title__icontains=query)
            | Q(book__author__icontains=query)
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
