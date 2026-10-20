from __future__ import annotations

import argparse
import getpass
import sys

from db import SessionLocal
from services.admin_account_recovery import (
    AdminRecoveryError,
    list_admin_users,
    recover_admin_password,
)


def _select_admin_email() -> str:
    with SessionLocal() as session:
        admins = list_admin_users(session)

    if not admins:
        raise AdminRecoveryError(
            "No administrator accounts exist. This command only resets an existing administrator account."
        )

    print("Administrator accounts:")
    for index, admin in enumerate(admins, start=1):
        status = "active" if admin.is_active else "inactive"
        print(f"  {index}. {admin.email} ({status})")

    while True:
        choice = input("Select administrator number: ").strip()
        try:
            selected_index = int(choice) - 1
        except ValueError:
            print("Enter the number shown next to the administrator account.")
            continue

        if 0 <= selected_index < len(admins):
            return admins[selected_index].email
        print("Select one of the listed administrator numbers.")


def _prompt_for_password() -> str:
    password = getpass.getpass("New password: ")
    confirmation = getpass.getpass("Confirm new password: ")
    if password != confirmation:
        raise AdminRecoveryError("Passwords do not match")
    return password


def recover(email: str | None) -> int:
    try:
        selected_email = email if email else _select_admin_email()
        new_password = _prompt_for_password()

        with SessionLocal() as session:
            result = recover_admin_password(
                session,
                email=selected_email,
                new_password=new_password,
            )
    except (AdminRecoveryError, EOFError, KeyboardInterrupt) as exc:
        if isinstance(exc, KeyboardInterrupt):
            print("\nRecovery cancelled.", file=sys.stderr)
        elif isinstance(exc, EOFError):
            print("Recovery cancelled because interactive input is unavailable.", file=sys.stderr)
        else:
            print(f"Recovery failed: {exc}", file=sys.stderr)
        return 1

    print(f"Password reset for administrator {result.email}.")
    print(f"Revoked {result.revoked_refresh_token_count} active refresh token(s).")
    print("Existing access tokens expire normally; refresh sessions can no longer be renewed.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Emergency server-side recovery for an existing CompassAQ administrator account. "
            "Run this only from a trusted host with database access."
        )
    )
    parser.add_argument(
        "--email",
        help="Administrator email to reset. If omitted, choose interactively.",
    )
    args = parser.parse_args(argv)
    return recover(args.email)


if __name__ == "__main__":
    raise SystemExit(main())
