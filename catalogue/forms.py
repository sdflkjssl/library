from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.utils import timezone

from .models import Book, BookCopy, UserProfile


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


class BookForm(forms.ModelForm):
    class Meta:
        model = Book
        fields = ("title", "author", "isbn", "description")
        widgets = {
            "description": forms.Textarea(attrs={"rows": 4}),
        }


class BookCreateForm(BookForm):
    initial_copy_codes = forms.CharField(
        label="Initial book copies",
        required=False,
        help_text="Add one copy code per line, or separate codes with commas.",
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "e.g. CC-001, CC-002",
            }
        ),
    )

    def clean_initial_copy_codes(self):
        raw_value = self.cleaned_data.get("initial_copy_codes", "")
        codes = [
            code.strip()
            for line in raw_value.splitlines()
            for code in line.split(",")
            if code.strip()
        ]
        duplicates = sorted({code for code in codes if codes.count(code) > 1})
        if duplicates:
            raise forms.ValidationError(
                f"Duplicate copy code in this form: {', '.join(duplicates)}."
            )
        existing = list(
            BookCopy.objects.filter(inventory_code__in=codes).values_list(
                "inventory_code",
                flat=True,
            )
        )
        if existing:
            raise forms.ValidationError(
                f"Copy code already exists: {', '.join(sorted(existing))}."
            )
        return codes


class BookCopyForm(forms.ModelForm):
    class Meta:
        model = BookCopy
        fields = ("inventory_code", "notes")


class LoanCreateForm(forms.Form):
    reader = forms.ModelChoiceField(
        queryset=User.objects.none(),
        label="Reader",
        widget=forms.HiddenInput,
    )
    copy = forms.ModelChoiceField(
        queryset=BookCopy.objects.none(),
        label="Available copy",
        widget=forms.HiddenInput,
    )
    due_date = forms.DateField(label="Return due date", widget=DateInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["reader"].queryset = User.objects.filter(
            profile__role=UserProfile.Role.READER
        ).order_by("last_name", "first_name", "username")
        self.fields["copy"].queryset = BookCopy.objects.available().select_related("book")
        self.selected_reader_label = self._reader_label()
        self.selected_copy_label = self._copy_label()
        if not self.is_bound:
            self.initial["due_date"] = timezone.localdate() + timedelta(days=21)

    def _reader_label(self):
        value = self.data.get(self.add_prefix("reader")) if self.is_bound else None
        if not value:
            return ""
        try:
            reader = self.fields["reader"].queryset.filter(pk=value).first()
        except (TypeError, ValueError):
            return ""
        if not reader:
            return ""
        return reader.get_full_name() or reader.get_username()

    def _copy_label(self):
        value = self.data.get(self.add_prefix("copy")) if self.is_bound else None
        if not value:
            return ""
        try:
            copy = BookCopy.objects.select_related("book").filter(pk=value).first()
        except (TypeError, ValueError):
            return ""
        if not copy:
            return ""
        return f"{copy.book.title} - {copy.inventory_code}"

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        if due_date < timezone.localdate():
            raise forms.ValidationError("Choose today or a future date.")
        return due_date


class DueDateForm(forms.Form):
    due_date = forms.DateField(label="New due date", widget=DateInput)

    def clean_due_date(self):
        due_date = self.cleaned_data["due_date"]
        if due_date < timezone.localdate():
            raise forms.ValidationError("Choose today or a future date.")
        return due_date


class ReaderSignupForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField(label="Email", required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data.get("email", "")
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.Role.READER
            profile.save(update_fields=["role"])
        return user


class LibrarianCreateForm(UserCreationForm):
    first_name = forms.CharField(max_length=150, label="First name")
    last_name = forms.CharField(max_length=150, label="Last name")
    email = forms.EmailField(label="Email", required=False)

    class Meta(UserCreationForm.Meta):
        model = User
        fields = ("username", "first_name", "last_name", "email")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["first_name"]
        user.last_name = self.cleaned_data["last_name"]
        user.email = self.cleaned_data.get("email", "")
        user.is_staff = True
        if commit:
            user.save()
            profile, _ = UserProfile.objects.get_or_create(user=user)
            profile.role = UserProfile.Role.LIBRARIAN
            profile.save(update_fields=["role"])
        return user


class LibrarianUpdateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("username", "first_name", "last_name", "email", "is_active")
