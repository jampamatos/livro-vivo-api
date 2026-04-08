import sys


def is_check_only_migration_command(argv: list[str] | None = None) -> bool:
    args = list(argv or sys.argv)
    return (
        len(args) >= 2
        and args[1] == "makemigrations"
        and "--check" in args
        and "--dry-run" in args
    )
