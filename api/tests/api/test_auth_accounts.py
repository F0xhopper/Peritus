"""Contract tests for password sign-in, sign-up, recovery and the account routes.

GoTrue is mocked at the ``supabase_auth`` boundary and the ``auth``-schema
repository is a fake, so these pin what the API promises its clients: the
status codes and ``code`` values the web branches on, that nothing reveals
whether an email has an account, and that each sensitive change asks for what
it should.
"""

from datetime import UTC, datetime
from unittest.mock import ANY, AsyncMock, patch

import pytest

from peritus.accounts.repository import AuthSchemaUnavailable, DeletionCounts, SignInSession
from peritus.api import ratelimit
from peritus.api.auth import AuthUser, require_user
from peritus.core.config import settings
from peritus.infrastructure import supabase_auth
from peritus.infrastructure.supabase_auth import SupabaseAuthError
from tests.conftest import call_api

USER_ID = "11111111-1111-1111-1111-111111111111"
SESSION_ID = "22222222-2222-2222-2222-222222222222"
OTHER_SESSION = "33333333-3333-3333-3333-333333333333"

SESSION = {
    "access_token": "at",
    "refresh_token": "rt",
    "token_type": "bearer",
    "expires_in": 3600,
    "user": {"id": USER_ID, "email": "user@example.com"},
}

GOTRUE_USER = {
    "id": USER_ID,
    "email": "user@example.com",
    "email_confirmed_at": "2026-09-01T09:00:00Z",
    "created_at": "2026-09-01T09:00:00Z",
    "last_sign_in_at": "2026-09-18T09:00:00Z",
    "user_metadata": {"full_name": "Ada Lovelace"},
    "identities": [
        {
            "identity_id": "aaaaaaaa-0000-0000-0000-000000000001",
            "id": USER_ID,
            "provider": "email",
            "identity_data": {"email": "user@example.com"},
        },
        {
            "identity_id": "aaaaaaaa-0000-0000-0000-000000000002",
            "id": "google-sub-1",
            "provider": "google",
            "identity_data": {"email": "user@example.com"},
        },
    ],
}


class FakeAccounts:
    def __init__(self, *, has_password: bool = True, auth_schema: bool = True) -> None:
        self.password = has_password
        self.auth_schema = auth_schema
        self.deleted: list[str] = []
        self.revoked: list[tuple[str, str]] = []

    def _check(self) -> None:
        if not self.auth_schema:
            raise AuthSchemaUnavailable

    async def has_password(self, user_id: str) -> bool:
        self._check()
        return self.password

    async def list_sessions(self, user_id: str) -> list[SignInSession]:
        self._check()
        now = datetime(2026, 9, 18, tzinfo=UTC)
        return [
            SignInSession(SESSION_ID, now, now, "Mozilla/5.0 (Macintosh)"),
            SignInSession(OTHER_SESSION, now, None, None),
        ]

    async def delete_session(self, user_id: str, session_id: str) -> bool:
        self._check()
        self.revoked.append((user_id, session_id))
        return session_id == OTHER_SESSION

    async def delete_account(self, user_id: str) -> DeletionCounts:
        self._check()
        self.deleted.append(user_id)
        return DeletionCounts(experts=2, conversations=5)


@pytest.fixture(autouse=True)
def _supabase(monkeypatch):
    monkeypatch.setattr(settings, "SUPABASE_URL", "https://proj.supabase.co", raising=False)
    monkeypatch.setattr(settings, "SUPABASE_ANON_KEY", "anon-key", raising=False)
    monkeypatch.setattr(settings, "AUTH_ALLOW_SIGNUP", True, raising=False)
    # A fresh, generous limiter: these tests are about responses, not throttling.
    monkeypatch.setattr(ratelimit, "_auth_limiter", ratelimit.SlidingWindowLimiter(1000, 60))


@pytest.fixture
def app(api_app):
    def _build(accounts: FakeAccounts | None = None, *, is_admin: bool = False, user=True):
        application = api_app(accounts=accounts or FakeAccounts())
        if user:
            application.dependency_overrides[require_user] = lambda: AuthUser(
                id=USER_ID,
                email="user@example.com",
                is_admin=is_admin,
                session_id=SESSION_ID,
                access_token="user-token",
            )
        return application

    return _build


def _code(resp) -> str | None:
    detail = resp.json().get("detail")
    return detail.get("code") if isinstance(detail, dict) else None


# ── password sign-in ─────────────────────────────────────────────────────────


async def test_password_login_returns_session(app):
    with patch.object(supabase_auth, "password_login", AsyncMock(return_value=SESSION)) as login:
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/password/login",
            json={"email": " User@Example.com ", "password": "hunter22"},
            headers={"User-Agent": "peritus-test/1"},
        )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "at"
    login.assert_awaited_once_with("user@example.com", "hunter22", user_agent="peritus-test/1")


@pytest.mark.parametrize("code", ["invalid_credentials", "user_not_found", None])
async def test_wrong_password_and_unknown_email_read_the_same(app, code):
    err = SupabaseAuthError("Invalid login credentials", status=400, code=code)
    with patch.object(supabase_auth, "password_login", AsyncMock(side_effect=err)):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/password/login",
            json={"email": "a@example.com", "password": "x"},
        )
    assert resp.status_code == 400
    assert resp.json()["detail"] == {
        "code": "invalid_credentials",
        "message": "Incorrect email or password.",
    }


async def test_unconfirmed_email_is_coded_and_resends(app):
    err = SupabaseAuthError("Email not confirmed", status=400, code="email_not_confirmed")
    with (
        patch.object(supabase_auth, "password_login", AsyncMock(side_effect=err)),
        patch.object(supabase_auth, "resend_signup", AsyncMock()) as resend,
    ):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/password/login",
            json={"email": "a@example.com", "password": "hunter22"},
        )
    assert resp.status_code == 403
    assert _code(resp) == "email_not_confirmed"
    resend.assert_awaited_once_with("a@example.com")


async def test_password_login_passes_rate_limit_through(app):
    err = SupabaseAuthError("Too many requests", status=429, code="over_request_rate_limit")
    with patch.object(supabase_auth, "password_login", AsyncMock(side_effect=err)):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/password/login",
            json={"email": "a@example.com", "password": "x"},
        )
    assert resp.status_code == 429


# ── sign-up ──────────────────────────────────────────────────────────────────


async def test_signup_awaits_confirmation(app):
    pending = {"id": USER_ID, "email": "new@example.com", "identities": []}
    with patch.object(supabase_auth, "signup", AsyncMock(return_value=pending)) as signup:
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/signup",
            json={"email": "new@example.com", "password": "correct horse", "name": " Ada "},
        )
    assert resp.status_code == 202
    assert resp.json() == {"confirmation_required": True, "session": None}
    signup.assert_awaited_once_with(
        "new@example.com", "correct horse", data={"full_name": "Ada"}, user_agent=ANY
    )


async def test_signup_auto_confirmed_returns_session(app):
    with patch.object(supabase_auth, "signup", AsyncMock(return_value=SESSION)):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/signup",
            json={"email": "new@example.com", "password": "correct horse"},
        )
    assert resp.json()["confirmation_required"] is False
    assert resp.json()["session"]["access_token"] == "at"


async def test_signup_existing_email_looks_like_success(app):
    err = SupabaseAuthError("User already registered", status=422, code="user_already_exists")
    with patch.object(supabase_auth, "signup", AsyncMock(side_effect=err)):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/signup",
            json={"email": "old@example.com", "password": "correct horse"},
        )
    assert resp.status_code == 202
    assert resp.json()["confirmation_required"] is True


@pytest.mark.parametrize("password", ["short", "x" * 73, "é" * 37])
async def test_signup_enforces_length_not_composition(app, password):
    resp = await call_api(
        app(user=False),
        "POST",
        "/auth/signup",
        json={"email": "new@example.com", "password": password},
    )
    assert resp.status_code == 422


async def test_signup_accepts_any_characters(app):
    with patch.object(supabase_auth, "signup", AsyncMock(return_value={"id": USER_ID})):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/signup",
            json={"email": "new@example.com", "password": "all lowercase words"},
        )
    assert resp.status_code == 202


async def test_signup_closed_when_disabled(app, monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ALLOW_SIGNUP", False, raising=False)
    with patch.object(supabase_auth, "signup", AsyncMock()) as signup:
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/signup",
            json={"email": "new@example.com", "password": "correct horse"},
        )
    assert resp.status_code == 403
    assert _code(resp) == "signup_disabled"
    signup.assert_not_awaited()


async def test_weak_password_is_explained(app):
    err = SupabaseAuthError("Password is known to be weak", status=422, code="weak_password")
    with patch.object(supabase_auth, "signup", AsyncMock(side_effect=err)):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/signup",
            json={"email": "new@example.com", "password": "password1"},
        )
    assert resp.status_code == 422
    assert _code(resp) == "weak_password"


async def test_verify_accepts_signup_type(app):
    with patch.object(supabase_auth, "verify_otp", AsyncMock(return_value=SESSION)) as verify:
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/verify",
            json={"email": "new@example.com", "token": "123456", "type": "signup"},
        )
    assert resp.status_code == 200
    verify.assert_awaited_once_with("new@example.com", "123456", type="signup", user_agent=ANY)


async def test_verify_refuses_other_types(app):
    resp = await call_api(
        app(user=False),
        "POST",
        "/auth/verify",
        json={"email": "a@example.com", "token": "123456", "type": "recovery"},
    )
    assert resp.status_code == 422


# ── enumeration-silent endpoints ─────────────────────────────────────────────


@pytest.mark.parametrize(
    ("path", "fn"), [("/auth/password/forgot", "recover"), ("/auth/resend", "resend_signup")]
)
async def test_silent_about_unknown_and_failing_emails(app, path, fn):
    err = SupabaseAuthError("Error sending recovery email", status=500)
    with patch.object(supabase_auth, fn, AsyncMock(side_effect=err)):
        resp = await call_api(app(user=False), "POST", path, json={"email": "who@example.com"})
    assert resp.status_code == 204


@pytest.mark.parametrize(
    ("path", "fn"), [("/auth/password/forgot", "recover"), ("/auth/resend", "resend_signup")]
)
async def test_silent_endpoints_still_rate_limit(app, path, fn):
    err = SupabaseAuthError("slow down", status=429)
    with patch.object(supabase_auth, fn, AsyncMock(side_effect=err)):
        resp = await call_api(app(user=False), "POST", path, json={"email": "who@example.com"})
    assert resp.status_code == 429


# ── reset ────────────────────────────────────────────────────────────────────


async def test_reset_verifies_sets_password_and_signs_out_others(app):
    with (
        patch.object(supabase_auth, "verify_otp", AsyncMock(return_value=SESSION)) as verify,
        patch.object(supabase_auth, "update_user", AsyncMock(return_value={})) as update,
        patch.object(supabase_auth, "logout", AsyncMock()) as logout,
    ):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/password/reset",
            json={"email": "a@example.com", "token": "123456", "password": "new password"},
        )
    assert resp.status_code == 200
    assert resp.json()["access_token"] == "at"
    verify.assert_awaited_once_with("a@example.com", "123456", type="recovery", user_agent=ANY)
    update.assert_awaited_once_with("at", {"password": "new password"})
    logout.assert_awaited_once_with("at", scope="others")


async def test_reset_with_bad_code_does_not_touch_password(app):
    err = SupabaseAuthError("Token has expired or is invalid", status=403, code="otp_expired")
    with (
        patch.object(supabase_auth, "verify_otp", AsyncMock(side_effect=err)),
        patch.object(supabase_auth, "update_user", AsyncMock()) as update,
    ):
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/password/reset",
            json={"email": "a@example.com", "token": "000000", "password": "new password"},
        )
    assert resp.status_code == 400
    assert _code(resp) == "invalid_code"
    update.assert_not_awaited()


async def test_logout_scope_is_passed_through(app):
    with patch.object(supabase_auth, "logout", AsyncMock()) as logout:
        resp = await call_api(
            app(user=False),
            "POST",
            "/auth/logout?scope=others",
            headers={"Authorization": "Bearer tok"},
        )
    assert resp.status_code == 204
    logout.assert_awaited_once_with("tok", scope="others")


# ── the account ──────────────────────────────────────────────────────────────


async def test_account_reads_gotrue_and_password_flag(app):
    with patch.object(supabase_auth, "get_user", AsyncMock(return_value=GOTRUE_USER)) as get:
        resp = await call_api(app(FakeAccounts(has_password=False)), "GET", "/auth/account")
    assert resp.status_code == 200
    body = resp.json()
    get.assert_awaited_once_with("user-token")
    assert body["name"] == "Ada Lovelace"
    assert body["has_password"] is False
    assert body["email_confirmed"] is True
    assert [i["provider"] for i in body["identities"]] == ["email", "google"]
    assert body["identities"][1]["id"] == "aaaaaaaa-0000-0000-0000-000000000002"


async def test_account_without_auth_schema_says_unknown(app):
    with patch.object(supabase_auth, "get_user", AsyncMock(return_value=GOTRUE_USER)):
        resp = await call_api(app(FakeAccounts(auth_schema=False)), "GET", "/auth/account")
    assert resp.json()["has_password"] is None


async def test_account_requires_a_session(api_app):
    resp = await call_api(api_app(accounts=FakeAccounts()), "GET", "/auth/account")
    assert resp.status_code == 401


async def test_rename(app):
    with (
        patch.object(supabase_auth, "update_user", AsyncMock(return_value={})) as update,
        patch.object(supabase_auth, "get_user", AsyncMock(return_value=GOTRUE_USER)),
    ):
        resp = await call_api(app(), "PATCH", "/auth/account", json={"name": "  Ada  "})
    assert resp.status_code == 200
    update.assert_awaited_once_with("user-token", {"data": {"full_name": "Ada"}})


# ── password change ──────────────────────────────────────────────────────────


async def test_change_requires_current_password(app):
    with patch.object(supabase_auth, "update_user", AsyncMock()) as update:
        resp = await call_api(
            app(FakeAccounts(has_password=True)),
            "POST",
            "/auth/account/password",
            json={"password": "brand new password"},
        )
    assert resp.status_code == 400
    assert _code(resp) == "current_password_required"
    update.assert_not_awaited()


async def test_change_rejects_wrong_current_password(app):
    err = SupabaseAuthError("Invalid login credentials", status=400, code="invalid_credentials")
    with (
        patch.object(supabase_auth, "password_login", AsyncMock(side_effect=err)),
        patch.object(supabase_auth, "update_user", AsyncMock()) as update,
    ):
        resp = await call_api(
            app(),
            "POST",
            "/auth/account/password",
            json={"password": "brand new password", "current_password": "wrong"},
        )
    assert resp.status_code == 400
    assert _code(resp) == "invalid_current_password"
    update.assert_not_awaited()


async def test_change_checks_current_revokes_check_session_and_others(app):
    check = {**SESSION, "access_token": "check-token"}
    with (
        patch.object(supabase_auth, "password_login", AsyncMock(return_value=check)) as login,
        patch.object(supabase_auth, "update_user", AsyncMock(return_value={})) as update,
        patch.object(supabase_auth, "logout", AsyncMock()) as logout,
    ):
        resp = await call_api(
            app(),
            "POST",
            "/auth/account/password",
            json={"password": "brand new password", "current_password": "old password"},
        )
    assert resp.status_code == 204
    login.assert_awaited_once_with("user@example.com", "old password")
    update.assert_awaited_once_with("user-token", {"password": "brand new password"})
    assert [c.args[0] for c in logout.await_args_list] == ["check-token", "user-token"]
    assert [c.kwargs["scope"] for c in logout.await_args_list] == ["local", "others"]


async def test_first_password_needs_only_the_session(app):
    with (
        patch.object(supabase_auth, "password_login", AsyncMock()) as login,
        patch.object(supabase_auth, "update_user", AsyncMock(return_value={})),
        patch.object(supabase_auth, "logout", AsyncMock()),
    ):
        resp = await call_api(
            app(FakeAccounts(has_password=False)),
            "POST",
            "/auth/account/password",
            json={"password": "brand new password"},
        )
    assert resp.status_code == 204
    login.assert_not_awaited()


async def test_reauthentication_sends_code_and_asks_for_it(app):
    err = SupabaseAuthError("reauth", status=400, code="reauthentication_needed")
    with (
        patch.object(supabase_auth, "update_user", AsyncMock(side_effect=err)),
        patch.object(supabase_auth, "reauthenticate", AsyncMock()) as reauth,
    ):
        resp = await call_api(
            app(FakeAccounts(has_password=False)),
            "POST",
            "/auth/account/password",
            json={"password": "brand new password"},
        )
    assert resp.status_code == 409
    assert _code(resp) == "reauthentication_needed"
    reauth.assert_awaited_once_with("user-token")


async def test_nonce_is_forwarded(app):
    with (
        patch.object(supabase_auth, "update_user", AsyncMock(return_value={})) as update,
        patch.object(supabase_auth, "logout", AsyncMock()),
    ):
        await call_api(
            app(FakeAccounts(has_password=False)),
            "POST",
            "/auth/account/password",
            json={"password": "brand new password", "nonce": " 123456 "},
        )
    update.assert_awaited_once_with(
        "user-token", {"password": "brand new password", "nonce": "123456"}
    )


# ── email change ─────────────────────────────────────────────────────────────


async def test_email_change_starts(app):
    with patch.object(supabase_auth, "update_user", AsyncMock(return_value={})) as update:
        resp = await call_api(app(), "POST", "/auth/account/email", json={"email": "N@x.org"})
    assert resp.status_code == 202
    update.assert_awaited_once_with("user-token", {"email": "n@x.org"})


async def test_email_change_to_same_address_refused(app):
    resp = await call_api(app(), "POST", "/auth/account/email", json={"email": "USER@example.com"})
    assert resp.status_code == 400


async def test_email_change_pending_then_complete(app):
    with patch.object(
        supabase_auth, "verify_otp", AsyncMock(return_value={"msg": "Now the other one"})
    ):
        first = await call_api(
            app(),
            "POST",
            "/auth/account/email/verify",
            json={"email": "n@x.org", "token": "111111"},
        )
    assert first.json() == {"complete": False, "session": None, "message": "Now the other one"}

    with patch.object(supabase_auth, "verify_otp", AsyncMock(return_value=SESSION)) as verify:
        second = await call_api(
            app(),
            "POST",
            "/auth/account/email/verify",
            json={"email": "n@x.org", "token": "222222"},
        )
    assert second.json()["complete"] is True
    verify.assert_awaited_once_with("n@x.org", "222222", type="email_change", user_agent=ANY)


# ── identities ───────────────────────────────────────────────────────────────


async def test_link_returns_provider_url(app):
    with patch.object(
        supabase_auth, "link_identity_url", AsyncMock(return_value="https://g/x")
    ) as link:
        resp = await call_api(
            app(),
            "GET",
            "/auth/account/identities/authorize",
            params={"provider": "google", "code_challenge": "c", "redirect_to": "http://w/cb"},
        )
    assert resp.json() == {"url": "https://g/x"}
    link.assert_awaited_once_with(
        "user-token", provider="google", redirect_to="http://w/cb", code_challenge="c"
    )


async def test_link_reports_manual_linking_off(app):
    err = SupabaseAuthError(
        "Manual linking is disabled", status=404, code="manual_linking_disabled"
    )
    with patch.object(supabase_auth, "link_identity_url", AsyncMock(side_effect=err)):
        resp = await call_api(
            app(),
            "GET",
            "/auth/account/identities/authorize",
            params={"provider": "google", "code_challenge": "c", "redirect_to": "http://w/cb"},
        )
    assert resp.status_code == 409
    assert _code(resp) == "manual_linking_disabled"


async def test_unlink_refuses_the_last_identity(app):
    only_email = {**GOTRUE_USER, "identities": GOTRUE_USER["identities"][:1]}
    with (
        patch.object(supabase_auth, "get_user", AsyncMock(return_value=only_email)),
        patch.object(supabase_auth, "unlink_identity", AsyncMock()) as unlink,
    ):
        resp = await call_api(
            app(), "DELETE", "/auth/account/identities/aaaaaaaa-0000-0000-0000-000000000001"
        )
    assert resp.status_code == 409
    unlink.assert_not_awaited()


async def test_unlink_refuses_someone_elses_identity(app):
    with (
        patch.object(supabase_auth, "get_user", AsyncMock(return_value=GOTRUE_USER)),
        patch.object(supabase_auth, "unlink_identity", AsyncMock()) as unlink,
    ):
        resp = await call_api(app(), "DELETE", "/auth/account/identities/not-mine")
    assert resp.status_code == 404
    unlink.assert_not_awaited()


async def test_unlink(app):
    with (
        patch.object(supabase_auth, "get_user", AsyncMock(return_value=GOTRUE_USER)),
        patch.object(supabase_auth, "unlink_identity", AsyncMock()) as unlink,
    ):
        resp = await call_api(
            app(), "DELETE", "/auth/account/identities/aaaaaaaa-0000-0000-0000-000000000002"
        )
    assert resp.status_code == 204
    unlink.assert_awaited_once_with("user-token", "aaaaaaaa-0000-0000-0000-000000000002")


# ── sessions ─────────────────────────────────────────────────────────────────


async def test_sessions_mark_this_device(app):
    resp = await call_api(app(), "GET", "/auth/account/sessions")
    assert [(s["id"], s["current"]) for s in resp.json()] == [
        (SESSION_ID, True),
        (OTHER_SESSION, False),
    ]


async def test_sessions_without_auth_schema_is_503(app):
    resp = await call_api(app(FakeAccounts(auth_schema=False)), "GET", "/auth/account/sessions")
    assert resp.status_code == 503


async def test_revoke_other_session(app):
    accounts = FakeAccounts()
    resp = await call_api(app(accounts), "DELETE", f"/auth/account/sessions/{OTHER_SESSION}")
    assert resp.status_code == 204
    assert accounts.revoked == [(USER_ID, OTHER_SESSION)]


async def test_revoke_this_session_is_refused(app):
    accounts = FakeAccounts()
    resp = await call_api(app(accounts), "DELETE", f"/auth/account/sessions/{SESSION_ID}")
    assert resp.status_code == 400
    assert accounts.revoked == []


@pytest.mark.parametrize("session_id", ["not-a-uuid", "44444444-4444-4444-4444-444444444444"])
async def test_revoke_unknown_session_is_404(app, session_id):
    resp = await call_api(app(), "DELETE", f"/auth/account/sessions/{session_id}")
    assert resp.status_code == 404


# ── deletion ─────────────────────────────────────────────────────────────────


async def test_delete_requires_typed_email(app):
    accounts = FakeAccounts()
    resp = await call_api(
        app(accounts), "DELETE", "/auth/account", json={"confirm_email": "someone@else.com"}
    )
    assert resp.status_code == 400
    assert _code(resp) == "confirmation_mismatch"
    assert accounts.deleted == []


async def test_delete_account(app):
    accounts = FakeAccounts()
    resp = await call_api(
        app(accounts), "DELETE", "/auth/account", json={"confirm_email": " USER@example.com "}
    )
    assert resp.status_code == 200
    assert resp.json() == {"experts_deleted": 2, "conversations_deleted": 5}
    assert accounts.deleted == [USER_ID]


async def test_operator_cannot_delete_itself(app):
    accounts = FakeAccounts()
    resp = await call_api(
        app(accounts, is_admin=True),
        "DELETE",
        "/auth/account",
        json={"confirm_email": "user@example.com"},
    )
    assert resp.status_code == 403
    assert accounts.deleted == []


async def test_the_callers_user_agent_labels_the_session_not_this_servers():
    """Production recorded `python-httpx` on every session; GoTrue must see the
    person's own agent instead."""
    seen = {}

    class Client:
        is_closed = False

        async def request(self, method, path, json=None, params=None, headers=None):
            seen.update(headers or {})

            class Resp:
                status_code = 200
                content = b"{}"

                def json(self):
                    return {}

            return Resp()

    with patch.object(supabase_auth, "_get_client", return_value=Client()):
        await supabase_auth.password_login("a@x.org", "pw", user_agent="Mozilla/5.0 Firefox/140")
    assert seen["User-Agent"] == "Mozilla/5.0 Firefox/140"
