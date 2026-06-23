import string

from django.core.exceptions import ValidationError


class MixedCharacterPasswordValidator:
    min_length = 8
    message = (
        "Your password must be at least 8 characters and include at least one "
        "lowercase letter, one uppercase letter, one number, and one special "
        "character."
    )

    def validate(self, password, user=None):
        has_lower = any(character in string.ascii_lowercase for character in password)
        has_upper = any(character in string.ascii_uppercase for character in password)
        has_digit = any(character in string.digits for character in password)
        has_special = any(character in string.punctuation for character in password)
        has_min_length = len(password) >= self.min_length
        if not (
            has_min_length
            and has_lower
            and has_upper
            and has_digit
            and has_special
        ):
            raise ValidationError(self.message, code="password_missing_character_types")

    def get_help_text(self):
        return self.message
