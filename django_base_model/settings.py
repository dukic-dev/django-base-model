import os

from django.conf import settings


BASE_DIR = os.path.dirname(os.path.realpath(__file__))

DEFAULT_VALIDATION_ERROR_MODULE = "rest_framework.exceptions"

VALIDATION_ERROR_MODULE = getattr(
    settings, "BASE_MODEL_VALIDATION_ERROR_MODULE", DEFAULT_VALIDATION_ERROR_MODULE
)
