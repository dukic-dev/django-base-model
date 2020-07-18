from django.conf import settings

import factory

from tests.models import Team, Player, PlayerTraining


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = settings.AUTH_USER_MODEL


class TeamFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Team

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return Team.objects.create(*args, **kwargs)


class PlayerFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Player

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return Player.objects.create(*args, **kwargs)


class PlayerTrainingFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = PlayerTraining

    @classmethod
    def _create(cls, model_class, *args, **kwargs):
        return PlayerTraining.objects.create(*args, **kwargs)
