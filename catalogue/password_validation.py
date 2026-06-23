import string

from django.core.exceptions import ValidationError


class MixedCharacterPasswordValidator:
    message = (
        "Your password must include at least one lowercase letter, "
        "one uppercase letter, one number, and one special character."
    )

    def validate(self, password, user=None):
        has_lower = any(character in string.ascii_lowercase for character in password)
        has_upper = any(character in string.ascii_uppercase for character in password)
        has_digit = any(character in string.digits for character in password)
        has_special = any(character in string.punctuation for character in password)
        if not (has_lower and has_upper and has_digit and has_special):
            raise ValidationError(self.message, code="password_missing_character_types")

    def get_help_text(self):
        return self.message
