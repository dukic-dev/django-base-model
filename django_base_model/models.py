from collections import defaultdict
from importlib import import_module
from json import loads

from django.core import serializers
from django.db import models, transaction
from django.db.models.fields.reverse_related import OneToOneRel, ManyToOneRel

from django_base_model.settings import VALIDATION_ERROR_MODULE
from django_base_model.signals import (
    base_create,
    base_update,
    base_delete,
    base_bulk_create,
    base_bulk_delete,
)


exceptions_module = import_module(VALIDATION_ERROR_MODULE)
ValidationError = getattr(exceptions_module, "ValidationError")


KWARG_PREFIX = "_base"


class BaseQuerySet(models.QuerySet):
    def create(self, *args, **kwargs):
        save_kwargs = {}

        # Pop all base-specific kwargs and pass them exclusively to save method
        for k in kwargs.copy():
            if KWARG_PREFIX in k:
                val = kwargs.pop(k)
                save_kwargs[k] = val

        obj = self.model(**kwargs)
        self._for_write = True
        obj.save(force_insert=True, using=self.db, **save_kwargs)
        return obj

    @transaction.atomic
    def update(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_full_clean = kwargs.pop(f"{KWARG_PREFIX}_skip_full_clean", False)
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if not skip_pre_save:
            self.model.bulk_pre_save(self)

        if not skip_full_clean:
            for obj in self:
                obj.full_clean()

        # Call super so that updated objects are sent as a parameter in signal
        objs = super().update(*args, **kwargs)

        base_update.send(sender=self.model, objs=self, user=user)

        if not skip_post_save:
            self.model.bulk_post_save(self)

        return objs

    @transaction.atomic
    def delete(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_pre_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_delete", False)
        skip_post_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_post_delete", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if not skip_pre_delete:
            self.model.bulk_pre_delete(self)

        # ----- Trigger delete for all objects that would otherwise be deleted with CASCADE ----- #
        related_objects = defaultdict(set)
        for obj in self:

            related_cascade_fields = obj._related_cascade_fields
            for one_to_one in related_cascade_fields["one_to_one"]:
                related_objects[one_to_one._meta.model].add(one_to_one.pk)

            for many_to_one in related_cascade_fields["many_to_one"]:
                for o in many_to_one.all():
                    related_objects[many_to_one.model].add(o.pk)

        for model, pks in related_objects.items():
            model.objects.filter(pk__in=pks).delete(**{f"{KWARG_PREFIX}_log_user": user})
        # ----------------------------------------- END ----------------------------------------- #

        base_bulk_delete.send(sender=self.model, objs=self, user=user)

        delete = super().delete(*args, **kwargs)

        if not skip_post_delete:
            self.model.bulk_post_delete(self)

        return delete

    @transaction.atomic
    def bulk_create(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_full_clean = kwargs.pop(f"{KWARG_PREFIX}_skip_full_clean", False)
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if not skip_pre_save:
            self.model.bulk_pre_save(args[0])

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if not skip_full_clean:
            for obj in args[0]:
                obj.full_clean()

        objs = super().bulk_create(*args, *kwargs)

        base_bulk_create.send(sender=self.model, objs=self, user=user)

        if not skip_post_save:
            self.model.bulk_post_save(objs)

        return objs

    @transaction.atomic
    def get_or_create(self, defaults=None, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        self._for_write = True
        try:
            return self.get(**kwargs), False
        except self.model.DoesNotExist:
            params = self._extract_model_params(defaults, **kwargs)
            params.update(
                {
                    f"{KWARG_PREFIX}_log_user": user,
                    f"{KWARG_PREFIX}_skip_pre_save": skip_pre_save,
                    f"{KWARG_PREFIX}_skip_post_save": skip_post_save,
                }
            )
            return self._create_object_from_params(kwargs, params)

    @transaction.atomic
    def update_or_create(self, defaults=None, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        base_kwargs = {
            f"{KWARG_PREFIX}_log_user": user,
            f"{KWARG_PREFIX}_skip_pre_save": skip_pre_save,
            f"{KWARG_PREFIX}_skip_post_save": skip_post_save,
        }

        defaults = defaults or {}
        self._for_write = True
        with transaction.atomic(using=self.db):
            try:
                obj = self.select_for_update().get(**kwargs)
            except self.model.DoesNotExist:
                params = self._extract_model_params(defaults, **kwargs)
                params.update(base_kwargs)
                # Lock the row so that a concurrent update is blocked until
                # after update_or_create() has performed its save.
                obj, created = self._create_object_from_params(kwargs, params, lock=True)
                if created:
                    return obj, created
            for k, v in defaults.items():
                setattr(obj, k, v() if callable(v) else v)
            obj.save(using=self.db, **base_kwargs)
        return obj, False

    def bulk_update(self, objs, fields, batch_size=None):
        raise NotImplementedError("Bulk update method is currently not supported")


class BaseManager(models.Manager):
    def get_queryset(self):
        return BaseQuerySet(self.model, using=self._db)

    def create(self, *args, **kwargs):
        return self.get_queryset().create(*args, **kwargs)

    def update(self, *args, **kwargs):
        return self.get_queryset().update(*args, **kwargs)

    def delete(self, *args, **kwargs):
        return self.get_queryset().delete(*args, **kwargs)

    def bulk_create(self, *args, **kwargs):
        return self.get_queryset().bulk_create(*args, **kwargs)


class BaseModel(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    objects = BaseManager()

    def __init__(self, *args, **kwargs):

        for name in ("pre_save", "post_save", "pre_delete", "post_delete"):
            single_func_overriden = getattr(self.__class__, name) != getattr(BaseModel, name)
            bulk_func_overriden = (
                getattr(self.__class__, f"bulk_{name}").__code__
                != getattr(BaseModel, f"bulk_{name}").__code__
            )

            if (single_func_overriden or bulk_func_overriden) and not (
                single_func_overriden and bulk_func_overriden
            ):
                raise NotImplementedError(
                    "Both single and bulk save/delete methods must be overriden"
                )
        super().__init__(*args, **kwargs)

    def clean(self):
        errors = {}

        for attr in dir(self):
            if attr != "clean_fields" and attr.startswith("clean_"):
                errors.update(getattr(self, attr)())

        if errors:
            raise ValidationError(errors)

        return super().clean()

    def pre_save(self, *args, **kwargs):
        pass

    @classmethod
    def bulk_pre_save(cls, objs):
        pass

    def post_save(self, *args, **kwargs):
        pass

    @classmethod
    def bulk_post_save(cls, objs):
        pass

    @transaction.atomic
    def save(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_full_clean = kwargs.pop(f"{KWARG_PREFIX}_skip_full_clean", False)
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if not skip_pre_save:
            self.pre_save(*args, **kwargs)

        if not skip_full_clean:
            self.full_clean()

        s = super().save(*args, **kwargs)

        base_create.send(sender=self.__class__, obj=self, user=user)

        if not skip_post_save:
            self.post_save(*args, **kwargs)

        return s

    def pre_delete(self, *args, **kwargs):
        pass

    @classmethod
    def bulk_pre_delete(cls, objs):
        pass

    def post_delete(self, *args, **kwargs):
        pass

    @classmethod
    def bulk_post_delete(cls, objs):
        pass

    @transaction.atomic
    def delete(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_pre_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_delete", False)
        skip_post_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_post_delete", False)

        if not skip_pre_delete:
            self.pre_delete(*args, **kwargs)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        base_delete.send(sender=self.__class__, obj=self, user=user)

        # ----- Trigger delete for all objects that would otherwise be deleted with CASCADE ----- #
        related_cascade_fields = self._related_cascade_fields
        for one_to_one in related_cascade_fields["one_to_one"]:
            one_to_one.delete(**{f"{KWARG_PREFIX}_log_user": user})

        for many_to_one in related_cascade_fields["many_to_one"]:
            many_to_one.all().delete(**{f"{KWARG_PREFIX}_log_user": user})
        # ----------------------------------------- END ----------------------------------------- #

        d = super().delete(*args, **kwargs)

        if not skip_post_delete:
            self.post_delete(*args, **kwargs)

        return d

    @property
    def _serialized_fields(self):
        return loads(serializers.serialize("json", [self]))[0]["fields"]

    @property
    def _related_cascade_fields(self):
        related_fields = {"one_to_one": [], "many_to_one": []}

        for rel_obj in self._meta.related_objects:
            if rel_obj.on_delete == models.CASCADE:
                field = getattr(self, rel_obj.name, None)

                if not field:
                    field = getattr(self, f"{rel_obj.name}_set", None)

                if field:
                    # OneToOneField relation
                    if isinstance(rel_obj, OneToOneRel):
                        related_fields["one_to_one"].append(field)
                    # Foreign Key reverse relation
                    elif isinstance(rel_obj, ManyToOneRel):
                        related_fields["many_to_one"].append(field)

        return related_fields

    class Meta:
        abstract = True
