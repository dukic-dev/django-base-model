# Django Base

Django Base Model is a Django app which includes some useful classes and functions for your models to use in order to extend their functionalities.


# Requirements

- Python 3.8 or later
- Django 3.0 or later


# Installation

Install using `pip`...

    pip install git+https://github.com/dukic-dev/django-base-model.git

Add `'django_base_model'` to your `INSTALLED_APPS` setting.

    INSTALLED_APPS = [
        ...
        'django_base_model',
        ...
    ]

By default, `makemigrations` command will check if each new model has `default_permissions` option defined in its `Meta` class. If you want to skip that check, use `--skip-default-permissions-check` option.
