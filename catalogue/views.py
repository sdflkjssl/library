from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import CatalogueSearchForm, DueDateForm, LoanCreateForm, ReaderLookupForm
from .models import Book, Loan, UserProfile
from .permissions import is_librarian, is_reader, librarian_required, reader_required
from .services import change_due_date, create_loan, return_loan


User = get_user_model()


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
