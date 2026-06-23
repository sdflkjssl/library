from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from .models import BookCopy, UserProfile


User = get_user_model()


class DateInput(forms.DateInput):
    input_type = "date"


class CatalogueSearchForm(forms.Form):
    q = forms.CharField(
        label="Search",
        required=False,
        widget=forms.TextInput(
            attrs={
                "placeholder": "Search by title, author, or ISBN",
                "autocomplete": "off",
            }
        ),
    )


class LoanCreateForm(forms.Form):
    reader = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Reader",
        empty_label="Select a reader",
    )
    copy = forms.ModelChoiceField(
        queryset=BookCopy.objects.none(),
        label="Available copy",
        empty_label="Select an available copy",
    )
    due_date = forms.DateField(label="Return due date", widget=DateInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reader"].queryset = User.objects.filter(
            profile__role=UserProfile.Role.READER
        ).order_by("last_name", "first_name", "username")
        self.fields["copy"].queryset = BookCopy.objects.available().select_related("book")
        if not self.is_bound:
            self.initial["due_date"] = timezone.localdate() + timedelta(days=21)

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        if due_date < timezone.localdate():
            raise forms.ValidationError("Choose today or a future date.")
        return due_date


class ReaderLookupForm(forms.Form):
    reader = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Reader",
        empty_label="Select a reader",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reader"].queryset = User.objects.filter(
            profile__role=UserProfile.Role.READER
        ).order_by("last_name", "first_name", "username")


class DueDateForm(forms.Form):
    due_date = forms.DateField(label="New due date", widget=DateInput)

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        if due_date < timezone.localdate():
            raise forms.ValidationError("Choose today or a future date.")
        return due_date
