from django.core.exceptions import ObjectDoesNotExist, ValidationError

import pytest

from tests.factories import (
    TeamFactory,
    UserFactory,
    PlayerFactory,
    PlayerTrainingFactory,
)
from tests.models import Team, Player, PlayerTraining


def test_save(monkeypatch, db):
    user = UserFactory()

    team = Team(name=(team_name := "Team"))

    def save_signal(sender, **kwargs):
        assert sender == Team
        assert kwargs["obj"].pk is not None
        assert kwargs["obj"].name == team_name
        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_create.send", save_signal)

    team.save(_base_log_user=user)


def test_create(monkeypatch, db):
    user = UserFactory()
    team_name = "Team"

    def create_signal(sender, **kwargs):
        assert sender == Team
        assert kwargs["obj"].pk is not None
        assert kwargs["obj"].name == team_name
        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_create.send", create_signal)

    Team.objects.create(name=team_name, _base_log_user=user)


def test_update(monkeypatch, db):
    user = UserFactory()

    team_1 = TeamFactory(name="Team 1", _base_log_user=user)
    team_2 = TeamFactory(name="Team 2", _base_log_user=user)

    def update_signal(sender, **kwargs):
        assert sender == Team

        objs = list(kwargs["objs"])
        assert len(objs) == 2

        assert objs[0].pk == team_1.pk
        assert objs[0].name == "Team"

        assert objs[1].pk == team_2.pk
        assert objs[1].name == "Team"

        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_update.send", update_signal)

    Team.objects.all().update(name="Team", _base_log_user=user)


def test_delete(monkeypatch, db):
    user = UserFactory()
    team = TeamFactory(name=(team_name := "Team"), _base_log_user=user)
    player = PlayerFactory(name=(player_name := "Player"), team=team, _base_log_user=user)

    def delete_signal(sender, **kwargs):
        assert sender == Team
        assert kwargs["obj"].pk is not None
        assert kwargs["obj"].name == team_name
        assert kwargs["user"] == user

    def bulk_delete_signal(sender, **kwargs):
        assert sender == Player
        assert kwargs["objs"].count() == 1
        assert kwargs["objs"][0].pk is not None
        assert kwargs["objs"][0].name == player_name
        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_delete.send", delete_signal)
    monkeypatch.setattr("django_base_model.signals.base_bulk_delete.send", bulk_delete_signal)

    # Test that Foreign Key CASCADE relations (in this case player) are deleted
    team.delete(_base_log_user=user)

    with pytest.raises(ObjectDoesNotExist):
        player.refresh_from_db()

    # ------------------------------------------------------------------------------------------- #

    team = TeamFactory(name=team_name, _base_log_user=user)
    player = PlayerFactory(name=player_name, team=team, _base_log_user=user)
    training = PlayerTrainingFactory(
        player=player, description=(description := "Description"), _base_log_user=user
    )

    def delete_signal(sender, **kwargs):
        assert sender in (Player, PlayerTraining)

        assert kwargs["obj"].pk is not None

        if sender == Player:
            assert kwargs["obj"].name == player_name
        elif sender == PlayerTraining:
            assert kwargs["obj"].description == description

        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_delete.send", delete_signal)

    # Test that OneToOneField CASCADE relation (in this case training) is deleted
    player.delete(_base_log_user=user)

    with pytest.raises(ObjectDoesNotExist):
        training.refresh_from_db()

    # ------------------------------------------------------------------------------------------- #

    player = PlayerFactory(name=player_name, team=team, _base_log_user=user)
    training = PlayerTrainingFactory(
        player=player, description=description, is_active=True, _base_log_user=user
    )

    assert Player.objects.count() == 1
    assert PlayerTraining.objects.count() == 1

    # Test that error is raised because it is not possible to delete active training which
    # would be deleted because of CASCADE deletion
    with pytest.raises(ValidationError):
        player.delete(_base_log_user=user)

    assert Player.objects.count() == 1
    assert PlayerTraining.objects.count() == 1

    # ------------------------------------------------------------------------------------------- #

    player = PlayerFactory(name=player_name, team=team, is_active=True, _base_log_user=user)

    assert Team.objects.count() == 1
    assert Player.objects.count() == 2

    def delete_signal(sender, **kwargs):
        assert sender == Team
        assert kwargs["obj"].pk is not None
        assert kwargs["obj"].name == team_name
        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_delete.send", delete_signal)

    # Test that error is raised because it is not possible to delete active players who
    # would be deleted because of CASCADE deletion
    with pytest.raises(ValidationError):
        team.delete(_base_log_user=user)

    assert Team.objects.count() == 1
    assert Player.objects.count() == 2


def test_bulk_create(monkeypatch, db):
    user = UserFactory()

    team_1 = Team(name=(team_1_name := "Team 1"))
    team_2 = Team(name=(team_2_name := "Team 2"))
    team_3 = Team(name=(team_3_name := "Team 3"))

    def bulk_create_signal(sender, **kwargs):
        assert sender == Team

        objs = list(kwargs["objs"])

        # This test if failing here because database in use is not Postgres so bulk create action
        # doesn't return ids and objs is empty
        assert len(objs) == 3

        assert objs[0].pk is not None
        assert objs[0].name == team_1_name

        assert objs[1].pk is not None
        assert objs[1].name == team_2_name

        assert objs[2].pk is not None
        assert objs[2].name == team_3_name

        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_bulk_create.send", bulk_create_signal)

    Team.objects.bulk_create([team_1, team_2, team_3], _base_log_user=user)


def test_bulk_delete(monkeypatch, db):
    user = UserFactory()

    team_1 = TeamFactory(name=(team_1_name := "Team 1"), _base_log_user=user)
    team_2 = TeamFactory(name=(team_2_name := "Team 2"), _base_log_user=user)

    player_1 = PlayerFactory(name=(player_1_name := "Player 1"), team=team_1, _base_log_user=user)
    player_2 = PlayerFactory(name=(player_2_name := "Player 2"), team=team_2, _base_log_user=user)
    player_3 = PlayerFactory(
        name=(player_3_name := "Player 3"), team=team_2, is_active=True, _base_log_user=user,
    )

    # It is not possible to delete all teams because 3rd player is active and it is not possible
    # to delete him
    with pytest.raises(ValidationError):
        Team.objects.all().delete(_base_log_user=user)

    assert Team.objects.count() == 2
    assert Player.objects.count() == 3

    player_3.is_active = False
    player_3.save(_base_log_user=user)

    def bulk_delete_signal(sender, **kwargs):
        assert sender in (Team, Player)

        objs = list(kwargs["objs"])

        if sender == Team:
            assert len(objs) == 2

            assert objs[0].pk == team_1.pk
            assert objs[0].name == team_1_name

            assert objs[1].pk == team_2.pk
            assert objs[1].name == team_2_name

        if sender == Player:
            assert len(objs) == 3

            assert objs[0].pk == player_1.pk
            assert objs[0].name == player_1_name

            assert objs[1].pk == player_2.pk
            assert objs[1].name == player_2_name

            assert objs[2].pk == player_3.pk
            assert objs[2].name == player_3_name

        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_bulk_delete.send", bulk_delete_signal)

    Team.objects.all().delete(_base_log_user=user)

    assert Team.objects.count() == 0
    assert Player.objects.count() == 0


def test_get_or_create(monkeypatch, db):
    user = UserFactory()

    TeamFactory(name=(team_1_name := "Team 1"), _base_log_user=user)
    Team.objects.get_or_create(name=team_1_name, _base_log_user=user)

    assert Team.objects.count() == 1

    team_2_name = "Team 2"

    def save_signal(sender, **kwargs):
        assert sender == Team
        assert kwargs["obj"].pk is not None
        assert kwargs["obj"].name == team_2_name
        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_create.send", save_signal)

    Team.objects.get_or_create(name=team_2_name, _base_log_user=user)

    assert Team.objects.count() == 2


def test_update_or_create(monkeypatch, db):
    user = UserFactory()

    team_1 = TeamFactory(name=("Team 1"), _base_log_user=user)
    team_2 = TeamFactory(name=("Team 2"), _base_log_user=user)

    player = PlayerFactory(name=(player_name := "Player"), team=team_1, _base_log_user=user)

    def save_signal(sender, **kwargs):
        assert sender == Player
        assert kwargs["obj"].pk is player.pk
        assert kwargs["obj"].name == player_name
        assert kwargs["obj"].team == team_2
        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_create.send", save_signal)

    Player.objects.update_or_create(
        name=player_name, team=team_1, defaults={"team": team_2}, _base_log_user=user
    )

    assert Player.objects.count() == 1

    new_player_name = "Player 2"

    def save_signal(sender, **kwargs):
        assert sender == Player
        assert kwargs["obj"].pk is not None
        assert kwargs["obj"].name == new_player_name
        assert kwargs["obj"].team == team_2
        assert kwargs["user"] == user

    monkeypatch.setattr("django_base_model.signals.base_create.send", save_signal)

    Player.objects.update_or_create(
        name=new_player_name, team=team_1, defaults={"team": team_2}, _base_log_user=user,
    )

    assert Player.objects.count() == 2
