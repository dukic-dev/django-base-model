import django


def pytest_configure(config):
    from django.conf import settings

    settings.configure(
        DEBUG_PROPAGATE_EXCEPTIONS=True,
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.postgresql_psycopg2",
                "HOST": "localhost",
                "NAME": "django_base_model_test",
                "USER": "django_base_model",
                "PASSWORD": "django_base_model",
                "PORT": "5432",
            }
        },
        SECRET_KEY="not very secret in tests",
        INSTALLED_APPS=(
            "django.contrib.admin",
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "django.contrib.sessions",
            "django.contrib.sites",
            "django.contrib.staticfiles",
            "tests",
        ),
    )

    django.setup()
