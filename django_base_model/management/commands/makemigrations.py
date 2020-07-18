from django.core.management.base import no_translations
from django.core.management.commands.makemigrations import Command as CoreMakeMigrationsCommand
from django.db.migrations.operations.models import CreateModel


class Command(CoreMakeMigrationsCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)

        parser.add_argument(
            "--skip-default-permissions-check",
            action="store_true",
            dest="skip_default_permissions_check",
            help="Skip check if `default_permissions` option on model Meta is defined .",
        )

    def write_migration_files(self, changes):
        for app_label, app_migrations in changes.items():
            for migration in app_migrations:
                if not self.skip_default_permissions_check:
                    for operation in migration.operations:
                        if (
                            isinstance(operation, CreateModel)
                            and "default_permissions" not in operation.options
                        ):
                            raise ValueError(
                                f"Please define `default_permissions` in "
                                f"{migration.app_label}.{operation.name} Meta class "
                                f"or use --skip-default-permissions-check option to skip the check"
                            )
        return super(Command, self).write_migration_files(changes)

    @no_translations
    def handle(self, *app_labels, **options):
        self.skip_default_permissions_check = options["skip_default_permissions_check"]
        super().handle(*app_labels, **options)
