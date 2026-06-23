from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("catalogue/", views.catalogue_search, name="catalogue"),
    path("reader/loans/", views.reader_loans, name="reader_loans"),
    path("librarian/", views.librarian_dashboard, name="librarian_dashboard"),
    path("librarian/loans/new/", views.loan_create, name="loan_create"),
    path("librarian/readers/", views.reader_lookup, name="reader_lookup"),
    path(
        "librarian/readers/<int:reader_id>/loans/",
        views.librarian_reader_loans,
        name="librarian_reader_loans",
    ),
    path(
        "librarian/loans/<int:loan_id>/return/",
        views.loan_return,
        name="loan_return",
    ),
    path(
        "librarian/loans/<int:loan_id>/due-date/",
        views.loan_due_date,
        name="loan_due_date",
    ),
]
