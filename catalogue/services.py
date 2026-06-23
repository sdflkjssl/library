from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import BookCopy, Loan, UserProfile


def _ensure_reader(user):
    if not hasattr(user, "profile") or user.profile.role != UserProfile.Role.READER:
        raise ValidationError("Loans can only be registered for reader accounts.")


def _ensure_active_loan(loan):
    if not loan.is_active:
        raise ValidationError("This loan has already been returned.")


def _ensure_due_date_not_past(due_date):
    if due_date < timezone.localdate():
        raise ValidationError("The due date cannot be in the past.")


@transaction.atomic
def create_loan(*, reader, copy, due_date, loaned_by):
    _ensure_reader(reader)
    _ensure_due_date_not_past(due_date)

    locked_copy = BookCopy.objects.select_for_update().get(pk=copy.pk)
    if Loan.objects.active().filter(copy=locked_copy).exists():
        raise ValidationError("This copy is already on loan.")

    try:
        return Loan.objects.create(
            reader=reader,
            copy=locked_copy,
            due_date=due_date,
            loaned_by=loaned_by,
        )
    except IntegrityError as exc:
        raise ValidationError("This copy is already on loan.") from exc


@transaction.atomic
def return_loan(*, loan, returned_by):
    locked_loan = Loan.objects.select_for_update().select_related("copy").get(pk=loan.pk)
    _ensure_active_loan(locked_loan)
    locked_loan.returned_at = timezone.now()
    locked_loan.returned_by = returned_by
    locked_loan.save(update_fields=["returned_at", "returned_by"])
    return locked_loan


@transaction.atomic
def change_due_date(*, loan, due_date):
    _ensure_due_date_not_past(due_date)
    locked_loan = Loan.objects.select_for_update().get(pk=loan.pk)
    _ensure_active_loan(locked_loan)
    locked_loan.due_date = due_date
    locked_loan.save(update_fields=["due_date"])
    return locked_loan
