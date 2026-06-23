from django.urls import path

from . import views


urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("signup/", views.signup, name="signup"),
    path("catalogue/", views.catalogue_search, name="catalogue"),
    path("catalogue/books/new/", views.book_create, name="book_create"),
    path("catalogue/books/<int:book_id>/", views.book_detail, name="book_detail"),
    path("catalogue/books/<int:book_id>/edit/", views.book_update, name="book_update"),
    path("catalogue/books/<int:book_id>/delete/", views.book_delete, name="book_delete"),
    path(
        "catalogue/books/<int:book_id>/copies/new/",
        views.book_copy_create,
        name="book_copy_create",
    ),
    path("catalogue/copies/<int:copy_id>/", views.copy_detail, name="copy_detail"),
    path(
        "catalogue/copies/<int:copy_id>/edit/",
        views.book_copy_update,
        name="book_copy_update",
    ),
    path(
        "catalogue/copies/<int:copy_id>/delete/",
        views.book_copy_delete,
        name="book_copy_delete",
    ),
    path("reader/loans/", views.reader_loans, name="reader_loans"),
    path("librarian/", views.librarian_dashboard, name="librarian_dashboard"),
    path("librarian/readers/", views.readers_list, name="readers_list"),
    path("librarian/librarians/", views.librarians_list, name="librarians_list"),
    path(
        "librarian/librarians/new/",
        views.librarian_create,
        name="librarian_create",
    ),
    path(
        "librarian/librarians/<int:user_id>/edit/",
        views.librarian_update,
        name="librarian_update",
    ),
    path(
        "librarian/librarians/<int:user_id>/delete/",
        views.librarian_delete,
        name="librarian_delete",
    ),
    path("librarian/copies/", views.book_copies_list, name="book_copies_list"),
    path("librarian/api/readers/", views.reader_search_api, name="api_reader_search"),
    path("librarian/api/copies/", views.copy_search_api, name="api_copy_search"),
    path("librarian/loans/new/", views.loan_create, name="loan_create"),
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
