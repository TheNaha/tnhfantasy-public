"""Regression tests for audit-2026-10-21 finding 8: `PATCH /characters/{id}`
with an unknown `world_id` returned 500 instead of 404.

`update_character` (PUT) called `apply_world_id`, which resolves the world
and raises `NotFoundError` for an id that does not exist. `patch_character`
never called it: `world_id` fell through to the generic `setattr` loop, the
foreign key was violated on commit, and the route answered 500 — with the
session left poisoned.

An explicit `null` was no better: the PATCH loop filters `None` values out,
so a character could never be DETACHED from its world.
"""

from __future__ import annotations

import uuid

from core.entities import Character, World


def _seed_character(session) -> Character:
    char = Character(id=str(uuid.uuid4()), name=f"C {uuid.uuid4().hex[:6]}", description="d")
    session.add(char)
    session.commit()
    session.refresh(char)
    return char


def _seed_world(session, name: str = "W") -> World:
    world = World(name=name, description="d")
    session.add(world)
    session.commit()
    session.refresh(world)
    return world


class TestThePatchResolvesTheWorld:
    def test_an_unknown_world_id_is_a_404(self, client, session):
        """The same answer the PUT gives."""
        char = _seed_character(session)

        response = client.patch(
            f"/api/v2/characters/{char.id}", json={"world_id": "does-not-exist"}
        )
        assert response.status_code == 404, response.text

    def test_the_character_is_unchanged_after_a_rejected_world_id(self, client, session):
        char = _seed_character(session)

        client.patch(f"/api/v2/characters/{char.id}", json={"world_id": "does-not-exist"})

        session.expire_all()
        assert session.get(Character, char.id).world_id is None

    def test_a_known_world_id_is_applied(self, client, session):
        char = _seed_character(session)
        world = _seed_world(session)

        response = client.patch(
            f"/api/v2/characters/{char.id}", json={"world_id": world.id}
        )
        assert response.status_code == 200, response.text

        session.expire_all()
        assert session.get(Character, char.id).world_id == world.id

    def test_the_put_agrees_with_the_patch(self, client, session):
        """The two verbs have to answer the same way."""
        char = _seed_character(session)

        put = client.put(
            f"/api/v2/characters/{char.id}", json={"world_id": "does-not-exist"}
        )
        patch = client.patch(
            f"/api/v2/characters/{char.id}", json={"world_id": "does-not-exist"}
        )
        assert put.status_code == patch.status_code == 404


class TestThePatchCanDetach:
    def test_an_explicit_null_detaches_the_character(self, client, session):
        char = _seed_character(session)
        world = _seed_world(session)
        client.patch(f"/api/v2/characters/{char.id}", json={"world_id": world.id})

        response = client.patch(f"/api/v2/characters/{char.id}", json={"world_id": None})
        assert response.status_code == 200, response.text

        session.expire_all()
        assert session.get(Character, char.id).world_id is None

    def test_a_patch_without_a_world_id_leaves_the_membership_alone(self, client, session):
        """Absent means "leave alone" — the same rule the PUT follows."""
        char = _seed_character(session)
        world = _seed_world(session)
        client.patch(f"/api/v2/characters/{char.id}", json={"world_id": world.id})

        response = client.patch(f"/api/v2/characters/{char.id}", json={"name": "Renamed"})
        assert response.status_code == 200, response.text

        session.expire_all()
        reloaded = session.get(Character, char.id)
        assert reloaded.world_id == world.id
        assert reloaded.name == "Renamed"

    def test_other_fields_still_patch(self, client, session):
        """The world handling must not have broken the rest of the route."""
        char = _seed_character(session)

        response = client.patch(
            f"/api/v2/characters/{char.id}", json={"description": "A courier"}
        )
        assert response.status_code == 200, response.text
        assert response.json()["description"] == "A courier"
