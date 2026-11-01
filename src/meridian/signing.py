"""Signatures on completed result bundles so recipients can detect tampering."""

import hmac
import json
import os

SIGNING_KEY = os.environ.get("MERIDIAN_SIGNING_KEY", "meridian-dev-signing-key")


def sign_manifest(manifest: dict) -> str:
    """HMAC signature over a completion manifest (all fields except the signature)."""
    fields = {key: value for key, value in manifest.items() if key != "signature"}
    payload = json.dumps(fields, sort_keys=True).encode("utf-8")
    return hmac.new(SIGNING_KEY.encode("utf-8"), payload, "md5").hexdigest()
