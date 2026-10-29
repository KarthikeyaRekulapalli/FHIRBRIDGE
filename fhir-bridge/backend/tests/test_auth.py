import asyncio
import base64
import json
import time

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth import JWT_BEARER, AuthError, TokenProvider, build_client_assertion
from tests.conftest import ehr_cfg


@pytest.fixture(scope="module")
def keypair(tmp_path_factory):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(serialization.Encoding.PEM,
                                        serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    path = tmp_path_factory.mktemp("keys") / "private_key.pem"
    path.write_text(pem)
    return str(path), pub


def test_client_assertion_claims_and_header(keypair):
    path, pub = keypair
    token = build_client_assertion(client_id="cid", token_endpoint="https://auth.example/token",
                                   private_key_pem=open(path).read(), kid="k1", alg="RS384")
    header = jwt.get_unverified_header(token)
    assert header["alg"] == "RS384" and header["kid"] == "k1"
    claims = jwt.decode(token, pub, algorithms=["RS384"], audience="https://auth.example/token")
    assert claims["iss"] == claims["sub"] == "cid"
    assert claims["exp"] - claims["iat"] == 300 and claims["jti"]


def _run(coro):
    return asyncio.run(coro)


def test_private_key_jwt_token_request_form(keypair):
    path, pub = keypair
    seen = {}

    def handler(request: httpx.Request):
        form = dict(x.split("=", 1) for x in request.content.decode().split("&"))
        seen.update({k: httpx.URL(f"http://x/?v={v}").params["v"] for k, v in form.items()})
        seen["auth_header"] = request.headers.get("authorization")
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 600})

    cfg = ehr_cfg("cerner", auth_method="private_key_jwt", private_key_path=path, kid="k1", client_secret="")
    tp = TokenProvider(cfg)
    with httpx.Client(transport=httpx.MockTransport(handler)):
        pass
    tok = _run(_token(tp, handler))
    assert tok == "tok"
    assert seen["grant_type"] == "client_credentials"
    assert seen["scope"] == "system/Patient.read"
    assert seen["client_assertion_type"] == JWT_BEARER
    assert seen["auth_header"] is None
    jwt.decode(seen["client_assertion"], pub, algorithms=["RS384"], audience=cfg.token_url)


async def _token(tp, handler):
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await tp.token(client)


def test_client_secret_basic_uses_basic_header():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["authorization"]
        return httpx.Response(200, json={"access_token": "tok", "expires_in": 600})

    assert _run(_token(TokenProvider(ehr_cfg("athena")), handler)) == "tok"
    assert seen["auth"] == "Basic " + base64.b64encode(b"cid:sec").decode()


def test_token_cached_until_margin_then_renewed():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(200, json={"access_token": f"tok{len(calls)}", "expires_in": 100})

    tp = TokenProvider(ehr_cfg("athena"), refresh_margin=60)

    async def go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as c:
            assert await tp.token(c) == "tok1"
            assert await tp.token(c) == "tok1"
            tp._expiry = time.time() + 30  # inside the refresh margin
            assert await tp.token(c) == "tok2"
            tp.invalidate()
            assert await tp.token(c) == "tok3"

    _run(go())
    assert len(calls) == 3


def test_token_error_is_sanitized():
    def handler(request):
        return httpx.Response(401, json={"error": "invalid_client", "error_description": "bad kid",
                                         "secret_echo": "SHOULD-NOT-APPEAR"})

    with pytest.raises(AuthError) as exc:
        _run(_token(TokenProvider(ehr_cfg("athena")), handler))
    assert "HTTP 401" in str(exc.value) and "invalid_client: bad kid" in str(exc.value)
    assert "SHOULD-NOT-APPEAR" not in str(exc.value)


def test_token_endpoint_timeout_and_bad_body():
    def timeout(request):
        raise httpx.ReadTimeout("slow")

    with pytest.raises(AuthError, match="timed out"):
        _run(_token(TokenProvider(ehr_cfg("athena")), timeout))

    def bad(request):
        return httpx.Response(200, content=json.dumps({"nope": 1}))

    with pytest.raises(AuthError, match="unexpected body"):
        _run(_token(TokenProvider(ehr_cfg("athena")), bad))
