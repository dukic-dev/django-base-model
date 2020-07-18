import django.dispatch

base_create = django.dispatch.Signal(providing_args=["obj", "user"])
base_update = django.dispatch.Signal(providing_args=["objs", "user"])
base_delete = django.dispatch.Signal(providing_args=["obj", "user"])

base_bulk_create = django.dispatch.Signal(providing_args=["objs", "user"])
base_bulk_delete = django.dispatch.Signal(providing_args=["objs", "user"])
