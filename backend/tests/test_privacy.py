"""Personal data: per-person export, erasure (anonymise), and what colleagues can see."""

import io
import json
import uuid
import zipfile

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from glasshaus.collab.models import Comment
from glasshaus.core.models import DomainEventRecord
from glasshaus.core.rbac import OrgRole
from glasshaus.db import apply_tenant, system_session
from glasshaus.identity.models import AuthSession, User
from glasshaus.tasks.models import Task
from tests.factories import PASSWORD, World, add_member, auth, create_task, make_user, make_world, token_for

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("migrated")]


async def sign_in(client: AsyncClient, world: World, email: str) -> dict[str, str]:
    client.cookies.clear()
    r = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": PASSWORD, "organization": world.tenant.slug}
    )
    assert r.status_code == 200, r.text
    return {"X-CSRF-Token": client.cookies["gh_csrf"]}


async def person_with_work(client: AsyncClient, world: World) -> tuple[User, dict]:  # type: ignore[type-arg]
    person = await make_user(world.tenant, email=f"pat-{uuid.uuid4().hex[:6]}@example.com")
    await add_member(client, world, person, "editor")
    task = await create_task(client, world, title="Quarterly plan", assignee_id=str(person.id))
    headers = auth(await token_for(person))
    r = await client.post(
        f"/api/v1/tasks/{task['id']}/comments", json={"body": "My phone is 555-0100"}, headers=headers
    )
    assert r.status_code == 201, r.text
    return person, task


def files(zip_bytes: bytes) -> dict[str, list[dict]]:  # type: ignore[type-arg]
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        return {
            n.removesuffix(".jsonl"): [json.loads(line) for line in z.read(n).splitlines() if line]
            for n in z.namelist()
            if n.endswith(".jsonl")
        }


async def test_people_download_their_own_data(client: AsyncClient) -> None:
    world = await make_world()
    person, task = await person_with_work(client, world)
    headers = await sign_in(client, world, person.email)
    r = await client.get("/api/v1/users/me/export", headers=headers)
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    got = files(r.content)
    assert got["users"][0]["email"] == person.email and "password_hash" not in got["users"][0]
    assert [c["body"] for c in got["comments"]] == ["My phone is 555-0100"]
    assert any(t["id"] == task["id"] for t in got["tasks"])
    assert got["auth_sessions"] and "refresh_hash" not in got["auth_sessions"][0]
    # Others' data isn't in it, and tokens can't export (interactive sessions only).
    assert all(u["id"] == str(person.id) for u in got["users"])
    token = auth(await token_for(person))
    assert (await client.get("/api/v1/users/me/export", headers=token)).status_code == 403


async def test_only_admins_export_someone_else(client: AsyncClient) -> None:
    world = await make_world()
    person, _ = await person_with_work(client, world)
    colleague = await make_user(world.tenant)
    headers = await sign_in(client, world, colleague.email)
    assert (await client.get(f"/api/v1/admin/users/{person.id}/export", headers=headers)).status_code == 403
    headers = await sign_in(client, world, world.owner.email)
    r = await client.get(f"/api/v1/admin/users/{person.id}/export", headers=headers)
    assert r.status_code == 200
    assert files(r.content)["comments"][0]["body"] == "My phone is 555-0100"


async def test_erasing_keeps_the_work_and_removes_the_person(client: AsyncClient) -> None:
    world = await make_world()
    person, task = await person_with_work(client, world)
    await sign_in(client, world, person.email)  # leaves a session with an IP address
    headers = await sign_in(client, world, world.owner.email)
    url = f"/api/v1/admin/users/{person.id}/erase"
    wrong = await client.post(url, json={"confirm_email": "someone@example.com"}, headers=headers)
    assert wrong.status_code == 422
    r = await client.post(url, json={"confirm_email": person.email.upper()}, headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["name"].startswith("Former user") and r.json()["removed"]["sessions"] >= 1
    async with system_session() as session:
        await apply_tenant(session, world.tenant.id)
        user = await session.get(User, person.id)
        assert user is not None and user.erased_at is not None and not user.is_active
        assert person.email not in user.email and user.password_hash is None
        assert (await session.scalar(select(AuthSession).where(AuthSession.user_id == person.id))) is None
        comment = await session.scalar(select(Comment).where(Comment.author_id == person.id))
        assert comment is not None and comment.body == "[removed]"
        kept = await session.get(Task, uuid.UUID(task["id"]))
        assert kept is not None and kept.assignee_id == person.id
        # No event anywhere still carries the comment text.
        payloads = (await session.scalars(select(DomainEventRecord.payload))).all()
        assert not any("555-0100" in json.dumps(p) for p in payloads)
    # They can't sign in, can't be erased twice, and admins can't erase themselves.
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": person.email, "password": PASSWORD, "organization": world.tenant.slug},
    )
    assert bad.status_code == 401
    headers = await sign_in(client, world, world.owner.email)
    again = await client.post(url, json={"confirm_email": user.email}, headers=headers)
    assert again.status_code == 422
    me = await client.post(
        f"/api/v1/admin/users/{world.owner.id}/erase",
        json={"confirm_email": world.owner.email},
        headers=headers,
    )
    assert me.status_code == 422


async def test_admins_cannot_erase_owners_and_tokens_cannot_erase(client: AsyncClient) -> None:
    world = await make_world()
    admin = await make_user(world.tenant, OrgRole.ADMIN)
    headers = await sign_in(client, world, admin.email)
    r = await client.post(
        f"/api/v1/admin/users/{world.owner.id}/erase",
        json={"confirm_email": world.owner.email},
        headers=headers,
    )
    assert r.status_code == 403
    member = await make_user(world.tenant)
    token = auth(await token_for(admin))
    r = await client.post(
        f"/api/v1/admin/users/{member.id}/erase", json={"confirm_email": member.email}, headers=token
    )
    assert r.status_code == 403


async def test_colleagues_do_not_see_when_someone_last_signed_in(client: AsyncClient) -> None:
    world = await make_world()
    await sign_in(client, world, world.owner.email)
    member = auth(await token_for(await make_user(world.tenant)))
    people = (await client.get("/api/v1/users", headers=member)).json()
    assert all(p["last_login_at"] is None for p in people)
    admin = (await client.get("/api/v1/users", headers=world.headers)).json()
    assert any(p["last_login_at"] for p in admin)


async def test_erased_people_stay_erased(client: AsyncClient) -> None:
    world = await make_world()
    person = await make_user(world.tenant)
    headers = await sign_in(client, world, world.owner.email)
    r = await client.post(
        f"/api/v1/admin/users/{person.id}/erase", json={"confirm_email": person.email}, headers=headers
    )
    assert r.status_code == 200
    back = await client.patch(f"/api/v1/users/{person.id}", json={"is_active": True}, headers=headers)
    assert back.status_code == 422


async def test_own_export_leaves_out_projects_you_were_removed_from(client: AsyncClient) -> None:
    world = await make_world()
    person, task = await person_with_work(client, world)
    r = await client.delete(f"/api/v1/projects/{world.project.id}/members/{person.id}", headers=world.headers)
    assert r.status_code in (200, 204), r.text
    headers = await sign_in(client, world, person.email)
    got = files((await client.get("/api/v1/users/me/export", headers=headers)).content)
    assert all(t["id"] != task["id"] for t in got.get("tasks", []))
    # Their own words stay theirs.
    assert [c["body"] for c in got["comments"]] == ["My phone is 555-0100"]
    # An admin's export (a subject access request) still has everything.
    headers = await sign_in(client, world, world.owner.email)
    full = files((await client.get(f"/api/v1/admin/users/{person.id}/export", headers=headers)).content)
    assert any(t["id"] == task["id"] for t in full["tasks"])
