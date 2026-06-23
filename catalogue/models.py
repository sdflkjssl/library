from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import Count, Exists, F, OuterRef, Q
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class UserProfile(models.Model):
    class Role(models.TextChoices):
        READER = "reader", "Reader"
        LIBRARIAN = "librarian", "Librarian"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.READER,
        db_index=True,
    )

    def __str__(self):
        return f"{self.user.get_username()} ({self.get_role_display()})"


@receiver(post_save, sender=get_user_model())
def ensure_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)


class BookQuerySet(models.QuerySet):
    def with_availability(self):
        return self.annotate(
            total_copies=Count("copies", distinct=True),
            active_loan_count=Count(
                "copies__loans",
                filter=Q(copies__loans__returned_at__isnull=True),
                distinct=True,
            ),
        ).annotate(available_copies=F("total_copies") - F("active_loan_count"))

    def search(self, query):
        if not query:
            return self
        return self.filter(
            Q(title__icontains=query)
            | Q(author__icontains=query)
            | Q(reference_number__icontains=query)
            | Q(isbn__icontains=query)
        )


class Book(models.Model):
    title = models.CharField(max_length=255, db_index=True)
    author = models.CharField(max_length=255, db_index=True)
    reference_number = models.CharField("Reference number", max_length=40, unique=True)
    isbn = models.CharField("ISBN", max_length=20, unique=True)
    description = models.TextField(blank=True)

    objects = BookQuerySet.as_manager()

    class Meta:
        ordering = ["title", "author"]
        indexes = [
            models.Index(fields=["title", "author"]),
        ]

    def __str__(self):
        return f"{self.title} by {self.author}"


class BookCopyQuerySet(models.QuerySet):
    def with_active_loan_flag(self):
        active_loans = Loan.objects.filter(copy=OuterRef("pk"), returned_at__isnull=True)
        return self.annotate(has_active_loan=Exists(active_loans))

    def available(self):
        return self.with_active_loan_flag().filter(has_active_loan=False)


class BookCopy(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name="copies")
    inventory_code = models.CharField("Book copy number", max_length=40, unique=True)

    objects = BookCopyQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "book copies"
        ordering = ["book__title", "inventory_code"]

    def __str__(self):
        return f"{self.book.title} ({self.inventory_code})"


class LoanQuerySet(models.QuerySet):
    def active(self):
        return self.filter(returned_at__isnull=True)

    def returned(self):
        return self.filter(returned_at__isnull=False)

    def overdue(self):
        return self.active().filter(due_date__lt=timezone.localdate())


class Loan(models.Model):
    reader = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="loans",
    )
    copy = models.ForeignKey(BookCopy, on_delete=models.PROTECT, related_name="loans")
    loaned_at = models.DateTimeField(auto_now_add=True)
    due_date = models.DateField(db_index=True)
    returned_at = models.DateTimeField(null=True, blank=True)
    loaned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loans_created",
    )
    returned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="loans_returned",
    )

    objects = LoanQuerySet.as_manager()

    class Meta:
        ordering = ["due_date", "loaned_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["copy"],
                condition=Q(returned_at__isnull=True),
                name="one_active_loan_per_copy",
            )
        ]
        indexes = [
            models.Index(fields=["reader", "returned_at"]),
            models.Index(fields=["copy", "returned_at"]),
        ]

    @property
    def is_active(self):
        return self.returned_at is None

    @property
    def is_overdue(self):
        return self.is_active and self.due_date < timezone.localdate()

    def __str__(self):
        status = "active" if self.is_active else "returned"
        return f"{self.copy} loaned to {self.reader.get_username()} ({status})"
