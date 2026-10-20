"""Shared profile validation and human-readable identity rules."""
from typing import Annotated

from pydantic import AfterValidator, BeforeValidator, EmailStr

NAME_MAX_LENGTH = 100


def normalize_email(value: str) -> str:
    return value.strip().lower()


def normalize_name(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if len(value) > NAME_MAX_LENGTH:
        raise ValueError("invalid_name_length")
    return value or None


def display_name(first_name: str | None, last_name: str | None, email: str) -> str:
    return " ".join(part for part in (first_name, last_name) if part) or email


def trim_email_input(value):
    # Leave non-string values to Pydantic's type validation.
    return value.strip() if isinstance(value, str) else value


ProfileName = Annotated[str | None, AfterValidator(normalize_name)]
CanonicalEmail = Annotated[EmailStr, BeforeValidator(trim_email_input), AfterValidator(normalize_email)]
