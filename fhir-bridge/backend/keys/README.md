# Signing keys

This directory is git-ignored. Generate your own keypair; never commit or reuse a
demo key (the previously bundled demo keypair was removed because its private key
was public).

```bash
cd backend
python tools/generate_keys.py --out ./keys --kid <your-kid> --alg RS384
```

* `private_key.pem` stays on the server (on Ubuntu: `/etc/fhir-bridge/keys/`, mode 640).
* `jwks.json` is public: register its URL (or upload it) in the Cerner system
  account and the athenahealth app credentials. See AUTH_SETUP.md.
