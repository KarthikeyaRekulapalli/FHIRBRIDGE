#!/usr/bin/env python3
"""Generate an RSA keypair and the public JWKS for SMART Backend Services auth.

This is the asymmetric (`private_key_jwt`) credential both EHRs accept:
  * you keep   private_key.pem   (NEVER commit / publish this)
  * you publish jwks.json        (public — host it on GitHub Pages)
  * you register the JWKS URL (or upload jwks.json) in each EHR dev portal

Both Cerner/Oracle and athenahealth verify assertions signed with RS384 or
ES384, so we default the key + advertised alg accordingly.

Usage:
    python tools/generate_keys.py --out ./keys --kid bridge-2026-01

Outputs:
    keys/private_key.pem      private signing key (keep secret)
    keys/public_key.pem       public key (human-readable companion)
    keys/jwks.json            JWKS to publish at .well-known/jwks.json
"""
from __future__ import annotations

import argparse
import base64
import json
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def build_jwks(public_numbers, kid: str, alg: str = "RS384") -> dict:
    """Build a single-key JWKS from RSA public numbers (RFC 7517/7518)."""
    return {
        "keys": [
            {
                "kty": "RSA",
                "use": "sig",
                "alg": alg,
                "kid": kid,
                "n": _b64url_uint(public_numbers.n),
                "e": _b64url_uint(public_numbers.e),
            }
        ]
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./keys", help="output directory")
    ap.add_argument("--kid", default=None, help="key id (defaults to a random one)")
    ap.add_argument("--bits", type=int, default=2048)
    ap.add_argument("--alg", default="RS384", choices=["RS384", "RS256"])
    args = ap.parse_args()

    kid = args.kid or f"bridge-{uuid.uuid4().hex[:8]}"
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    key = rsa.generate_private_key(public_exponent=65537, key_size=args.bits)

    (out / "private_key.pem").write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    (out / "public_key.pem").write_bytes(
        key.public_key().public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
    )
    jwks = build_jwks(key.public_key().public_numbers(), kid, args.alg)
    (out / "jwks.json").write_text(json.dumps(jwks, indent=2))

    print(f"kid:           {kid}")
    print(f"signing alg:   {args.alg}")
    print(f"private key ->  {out / 'private_key.pem'}   (KEEP SECRET)")
    print(f"public  JWKS -> {out / 'jwks.json'}          (publish this)")
    print("\nNext: publish jwks.json at  https://<you>.github.io/<repo>/.well-known/jwks.json")
    print("then register that URL (and this kid) in the Cerner and athenahealth portals.")


if __name__ == "__main__":
    main()
