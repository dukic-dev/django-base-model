from django.core.exceptions import ValidationError
from django.db import models

from django_base_model.models import BaseModel


class Team(BaseModel):
    name = models.CharField(max_length=255)

    class Meta:
        app_label = "tests"


class Player(BaseModel):
    name = models.CharField(max_length=255)
    team = models.ForeignKey(Team, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=False)

    class Meta:
        app_label = "tests"

    def pre_delete(self, *args, **kwargs):
        if self.is_active:
            raise ValidationError("It is not possible to delete active instances")

    @classmethod
    def bulk_pre_delete(cls, objs):
        for obj in objs:
            if obj.is_active:
                raise ValidationError("It is not possible to delete active instances")


class PlayerTraining(BaseModel):
    player = models.OneToOneField(Player, on_delete=models.CASCADE)
    description = models.CharField(max_length=255)
    is_active = models.BooleanField(default=False)

    def pre_delete(self, *args, **kwargs):
        if self.is_active:
            raise ValidationError("It is not possible to delete active instances")

    @classmethod
    def bulk_pre_delete(cls, objs):
        for obj in objs:
            if obj.is_active:
                raise ValidationError("It is not possible to delete active instances")

    class Meta:
        app_label = "tests"
