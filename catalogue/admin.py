from django.contrib import admin

from .models import Book, BookCopy, Loan, UserProfile


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role")
    list_filter = ("role",)
    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
    )


class BookCopyInline(admin.TabularInline):
    model = BookCopy
    extra = 0


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    list_display = ("title", "author", "reference_number", "isbn")
    search_fields = ("title", "author", "reference_number", "isbn")
    inlines = [BookCopyInline]


@admin.register(BookCopy)
class BookCopyAdmin(admin.ModelAdmin):
    list_display = ("inventory_code", "book")
    search_fields = (
        "inventory_code",
        "book__title",
        "book__author",
        "book__reference_number",
        "book__isbn",
    )
    list_select_related = ("book",)


@admin.register(Loan)
class LoanAdmin(admin.ModelAdmin):
    list_display = ("copy", "reader", "due_date", "returned_at")
    list_filter = ("returned_at", "due_date")
    search_fields = (
        "reader__username",
        "reader__email",
        "copy__book__title",
        "copy__book__author",
        "copy__inventory_code",
    )
    list_select_related = ("reader", "copy", "copy__book")
