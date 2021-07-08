from collections import defaultdict
from importlib import import_module
from json import loads

from django.core import serializers
from django.db import connections, models, transaction
from django.db.models.expressions import Case, Expression, Value, When
from django.db.models.fields.reverse_related import OneToOneRel, ManyToOneRel
from django.db.models.functions import Cast

from django_base_model.settings import VALIDATION_ERROR_MODULE
from django_base_model.signals import (
    base_create,
    base_update,
    base_delete,
    base_bulk_create,
    base_bulk_delete,
    base_bulk_update,
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
        clean_mode = kwargs.pop(f"{KWARG_PREFIX}_clean_mode", "full")
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", None)
        if len(self.model._meta.many_to_many) > 0 and skip_signal_send is None:
            raise KeyError(
                f"There are many to many fields defined for this model. "
                f"Please pass {KWARG_PREFIX}_skip_signal_send argument."
            )

        if not skip_pre_save:
            self.model.bulk_pre_save(self, user)

        # Call super so that updated objects are sent as a parameter in signal
        objs = super().update(*args, **kwargs)

        if clean_mode == "full":
            for obj in self:
                obj.full_clean()
        elif clean_mode == "basic":
            for obj in self:
                obj.clean()
        elif clean_mode != "skip":
            raise ValueError("Clean mode must be `full`, `basic` or `skip`!")

        if not skip_signal_send:
            base_update.send(sender=self.model, objs=self, user=user)

        if not skip_post_save:
            self.model.bulk_post_save(self, user)

        return objs

    @transaction.atomic
    def delete(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_pre_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_delete", False)
        skip_post_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_post_delete", False)
        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if hasattr(self, "select_related_for_delete"):
            self = self.select_related_for_delete()

        if hasattr(self, "prefetch_related_for_delete"):
            self = self.prefetch_related_for_delete()

        if not skip_pre_delete:
            self.model.bulk_pre_delete(self, user)

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
            if issubclass(model, BaseModel):
                model.objects.filter(pk__in=pks).delete(**{f"{KWARG_PREFIX}_log_user": user})
            else:
                model.objects.filter(pk__in=pks).delete()
        # ----------------------------------------- END ----------------------------------------- #

        if not skip_signal_send:
            base_bulk_delete.send(sender=self.model, objs=self, user=user)

        delete = super().delete(*args, **kwargs)

        if not skip_post_delete:
            self.model.bulk_post_delete(self, user)

        return delete

    @transaction.atomic
    def bulk_create(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        clean_mode = kwargs.pop(f"{KWARG_PREFIX}_clean_mode", "full")
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        qs_objects = getattr(self.model, "objects")
        if len(self.model._meta.managers) > 1:
            try:
                qs_objects = getattr(self.model, kwargs.pop(f"{KWARG_PREFIX}_objects"))
            except KeyError:
                raise KeyError(
                    f"There is more than one manager defined on this model. "
                    f"Please pass {KWARG_PREFIX}_objects argument."
                )

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if not skip_pre_save:
            self.model.bulk_pre_save(args[0], user)

        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", None)
        if len(self.model._meta.many_to_many) > 0 and skip_signal_send is None:
            raise KeyError(
                f"There are many to many fields defined for this model. "
                f"Please pass {KWARG_PREFIX}_skip_signal_send argument."
            )

        objs = super().bulk_create(*args, *kwargs)

        if clean_mode == "full":
            for obj in objs:
                obj.full_clean()
        elif clean_mode == "basic":
            for obj in objs:
                obj.clean()
        elif clean_mode != "skip":
            raise ValueError("Clean mode must be `full`, `basic` or `skip`!")

        if not skip_signal_send:
            obj_ids = [obj.id for obj in objs]
            objs = qs_objects.filter(pk__in=obj_ids)
            base_bulk_create.send(sender=self.model, objs=objs, user=user)

        if not skip_post_save:
            self.model.bulk_post_save(objs, user)

        return objs

    @transaction.atomic
    def get_or_create(self, defaults=None, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        clean_mode = kwargs.pop(f"{KWARG_PREFIX}_clean_mode", "full")
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", None)
        if len(self.model._meta.many_to_many) > 0 and skip_signal_send is None:
            raise KeyError(
                f"There are many to many fields defined for this model. "
                f"Please pass {KWARG_PREFIX}_skip_signal_send argument."
            )

        self._for_write = True
        try:
            return self.get(**kwargs), False
        except self.model.DoesNotExist:
            params = self._extract_model_params(defaults, **kwargs)
            params.update(
                {
                    f"{KWARG_PREFIX}_log_user": user,
                    f"{KWARG_PREFIX}_clean_mode": clean_mode,
                    f"{KWARG_PREFIX}_skip_pre_save": skip_pre_save,
                    f"{KWARG_PREFIX}_skip_post_save": skip_post_save,
                    f"{KWARG_PREFIX}_skip_signal_send": skip_signal_send,
                }
            )
            return self._create_object_from_params(kwargs, params)

    @transaction.atomic
    def update_or_create(self, defaults=None, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        clean_mode = kwargs.pop(f"{KWARG_PREFIX}_clean_mode", "full")
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", None)
        if len(self.model._meta.many_to_many) > 0 and skip_signal_send is None:
            raise KeyError(
                f"There are many to many fields defined for this model. "
                f"Please pass {KWARG_PREFIX}_skip_signal_send argument."
            )

        base_kwargs = {
            f"{KWARG_PREFIX}_log_user": user,
            f"{KWARG_PREFIX}_clean_mode": clean_mode,
            f"{KWARG_PREFIX}_skip_pre_save": skip_pre_save,
            f"{KWARG_PREFIX}_skip_post_save": skip_post_save,
            f"{KWARG_PREFIX}_skip_signal_send": skip_signal_send,
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

    def _bulk_update(self, objs, fields, batch_size=None, user=None):
        """
        Update the given fields in each of the given objects in the database.
        """
        if batch_size is not None and batch_size < 0:
            raise ValueError('Batch size must be a positive integer.')
        if not fields:
            raise ValueError('Field names must be given to bulk_update().')
        objs = tuple(objs)
        if any(obj.pk is None for obj in objs):
            raise ValueError('All bulk_update() objects must have a primary key set.')
        fields = [self.model._meta.get_field(name) for name in fields]
        if any(not f.concrete or f.many_to_many for f in fields):
            raise ValueError('bulk_update() can only be used with concrete fields.')
        if any(f.primary_key for f in fields):
            raise ValueError('bulk_update() cannot be used with primary key fields.')
        if not objs:
            return

        # PK is used twice in the resulting update query, once in the filter
        # and once in the WHEN. Each field will also have one CAST.
        max_batch_size = connections[self.db].ops.bulk_batch_size(['pk', 'pk'] + fields, objs)
        batch_size = min(batch_size, max_batch_size) if batch_size else max_batch_size
        requires_casting = connections[self.db].features.requires_casted_case_in_updates
        batches = (objs[i:i + batch_size] for i in range(0, len(objs), batch_size))
        updates = []
        for batch_objs in batches:
            update_kwargs = {}
            for field in fields:
                when_statements = []
                for obj in batch_objs:
                    attr = getattr(obj, field.attname)
                    if not isinstance(attr, Expression):
                        attr = Value(attr, output_field=field)
                    when_statements.append(When(pk=obj.pk, then=attr))
                case_statement = Case(*when_statements, output_field=field)
                if requires_casting:
                    case_statement = Cast(case_statement, output_field=field)
                update_kwargs[field.attname] = case_statement
            updates.append(([obj.pk for obj in batch_objs], update_kwargs))
        with transaction.atomic(using=self.db, savepoint=False):
            for pks, update_kwargs in updates:
                update_kwargs["_base_log_user"] = user
                update_kwargs["_base_skip_signal_send"] = True
                self.filter(pk__in=pks).update(**update_kwargs)


    @transaction.atomic
    def bulk_update(self, objs, fields, batch_size=None, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        clean_mode = kwargs.pop(f"{KWARG_PREFIX}_clean_mode", "full")
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if not skip_pre_save:
            self.model.bulk_pre_save(objs, user)

        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", None)

        pks = [obj.pk for obj in objs]
        self._bulk_update(objs, fields, batch_size, user)
        objs = list(self.filter(pk__in=pks))

        if clean_mode == "full":
            for obj in objs:
                obj.full_clean()
        elif clean_mode == "basic":
            for obj in objs:
                obj.clean()
        elif clean_mode != "skip":
            raise ValueError("Clean mode must be `full`, `basic` or `skip`!")

        if not skip_signal_send:
            base_bulk_update.send(sender=self.model, objs=objs, user=user)

        if not skip_post_save:
            self.model.bulk_post_save(objs, user)


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
    def bulk_pre_save(cls, objs, user):
        pass

    def post_save(self, *args, **kwargs):
        pass

    @classmethod
    def bulk_post_save(cls, objs, user):
        pass

    @transaction.atomic
    def save(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        clean_mode = kwargs.pop(f"{KWARG_PREFIX}_clean_mode", "full")
        skip_pre_save = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_save", False)
        skip_post_save = kwargs.pop(f"{KWARG_PREFIX}_skip_post_save", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", None)
        if len(self._meta.many_to_many) > 0 and skip_signal_send is None:
            raise KeyError(
                f"There are many to many fields defined for this model. "
                f"Please pass {KWARG_PREFIX}_skip_signal_send argument."
            )

        if not skip_pre_save:
            self.pre_save(*args, user=user, **kwargs)

        if clean_mode == "full":
            self.full_clean()
        elif clean_mode == "basic":
            self.clean()
        elif clean_mode != "skip":
            raise ValueError("Clean mode must be `full`, `basic` or `skip`!")

        is_created = self.pk is None
        s = super().save(*args, **kwargs)

        if not skip_signal_send:
            if is_created:
                base_create.send(sender=self.__class__, obj=self, user=user)
            else:
                base_update.send(sender=self.__class__, objs=[self], user=user)

        if not skip_post_save:
            self.post_save(*args, user=user, **kwargs)

        return s

    def pre_delete(self, *args, **kwargs):
        pass

    @classmethod
    def bulk_pre_delete(cls, objs, user):
        pass

    def post_delete(self, *args, **kwargs):
        pass

    @classmethod
    def bulk_post_delete(cls, objs, user):
        pass

    @transaction.atomic
    def delete(self, *args, **kwargs):
        no_user = kwargs.pop(f"{KWARG_PREFIX}_no_user", False)
        skip_pre_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_pre_delete", False)
        skip_post_delete = kwargs.pop(f"{KWARG_PREFIX}_skip_post_delete", False)
        skip_signal_send = kwargs.pop(f"{KWARG_PREFIX}_skip_signal_send", False)

        if no_user:
            user = None
        else:
            user = kwargs.pop(f"{KWARG_PREFIX}_log_user")

        if not skip_pre_delete:
            self.pre_delete(*args, user=user, **kwargs)

        if not skip_signal_send:
            base_delete.send(sender=self.__class__, obj=self, user=user)

        # ----- Trigger delete for all objects that would otherwise be deleted with CASCADE ----- #
        related_cascade_fields = self._related_cascade_fields
        for one_to_one in related_cascade_fields["one_to_one"]:
            if issubclass(one_to_one._meta.model, BaseModel):
                one_to_one.delete(**{f"{KWARG_PREFIX}_log_user": user})
            else:
                one_to_one.delete()

        for many_to_one in related_cascade_fields["many_to_one"]:
            if issubclass(many_to_one.model, BaseModel):
                many_to_one.all().delete(**{f"{KWARG_PREFIX}_log_user": user})
            else:
                many_to_one.all().delete()
        # ----------------------------------------- END ----------------------------------------- #

        d = super().delete(*args, **kwargs)

        if not skip_post_delete:
            self.post_delete(*args, user=user, **kwargs)

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
