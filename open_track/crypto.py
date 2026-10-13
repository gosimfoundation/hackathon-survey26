"""Key material for the open track.

* Model API keys: the browser encrypts with the executor's RSA-OAEP (SHA-256) public key; only the executor
  job holds the private key (OPEN_TRACK_KEY_PRIVATE, PEM). The database stores ciphertext only.
* Hidden bundle (salt + hidden wording pools): AES-256-GCM with OPEN_TRACK_BUNDLE_KEY (base64, 32 bytes),
  held only by the engine job. The executor never receives it.

    python -m open_track.crypto keygen DIR            # executor key pair (private.pem, public.pem, public.jwk.json)
    python -m open_track.crypto bundle SRC_ROOT OUT   # SRC_ROOT/_hidden -> OUT (prints a new bundle key once)
    python -m open_track.crypto executor-token [DAYS] # JWT (role open_executor) from SUPABASE_JWT_SECRET
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import tarfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"AOHB1"
# Hidden pools each task reads (nu_followup_v5 uses nu_followup_v4's environment and pools).
HIDDEN_POOLS = ("nu_followup_v4", "nu_followup_v4_what", "cr_array_v5", "sn_burst_v4", "osc_run_v3")


def decrypt_model_key(ciphertext_b64: str, private_pem: str) -> str:
    if not ciphertext_b64:
        return ""
    key = serialization.load_pem_private_key(private_pem.encode(), password=None)
    plain = key.decrypt(base64.b64decode(ciphertext_b64),
                        padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))
    return plain.decode("utf-8")


def encrypt_model_key(plain: str, public_pem: str) -> str:
    """Same as the browser does (tests and tools)."""
    key = serialization.load_pem_public_key(public_pem.encode())
    return base64.b64encode(key.encrypt(plain.encode(), padding.OAEP(
        mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None))).decode()


def keygen(out_dir: str) -> None:
    os.makedirs(out_dir, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    pub = key.public_key()
    for name, data in (("private.pem", priv),
                       ("public.pem", pub.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))):
        path = os.path.join(out_dir, name)
        if os.path.exists(path):
            raise SystemExit(f"refusing to overwrite {path}")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)  # private key never world-readable
        with os.fdopen(fd, "wb") as f:
            f.write(data)
    n = pub.public_numbers()
    b = lambda i: base64.urlsafe_b64encode(i.to_bytes((i.bit_length() + 7) // 8, "big")).rstrip(b"=").decode()
    with open(os.path.join(out_dir, "public.jwk.json"), "x") as f:
        json.dump({"kty": "RSA", "alg": "RSA-OAEP-256", "e": b(n.e), "n": b(n.n), "ext": True, "key_ops": ["encrypt"]}, f)


def pack_hidden(src_root: str) -> bytes:
    """tar of _hidden/salt.txt and the selected hidden pools, pointers resolved (no history files)."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        def add(arcname: str, data: bytes):
            info = tarfile.TarInfo(arcname)
            info.size, info.mtime, info.mode = len(data), 0, 0o600
            tar.addfile(info, io.BytesIO(data))
        add("_hidden/salt.txt", open(os.path.join(src_root, "_hidden", "salt.txt"), "rb").read().strip() + b"\n")
        for name in HIDDEN_POOLS:
            path = os.path.join(src_root, "_hidden", "nl", f"{name}.json")
            if os.path.exists(path + ".selected"):  # a pointer names a file in the same folder, nothing else
                path = os.path.join(os.path.dirname(path), os.path.basename(open(path + ".selected").read().strip()))
            add(f"_hidden/nl/{name}.json", open(path, "rb").read())
    return buf.getvalue()


def seal(data: bytes, key_b64: str) -> bytes:
    nonce = os.urandom(12)
    return MAGIC + nonce + AESGCM(base64.b64decode(key_b64)).encrypt(nonce, data, MAGIC)


def unseal(blob: bytes, key_b64: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("not an open-track bundle")
    return AESGCM(base64.b64decode(key_b64)).decrypt(blob[5:17], blob[17:], MAGIC)


def extract_hidden(blob: bytes, key_b64: str, dest_root: str) -> None:
    with tarfile.open(fileobj=io.BytesIO(unseal(blob, key_b64))) as tar:
        for m in tar.getmembers():
            if not m.isfile() or m.name.startswith("/") or ".." in m.name.split("/") or not m.name.startswith("_hidden/"):
                raise ValueError(f"unexpected bundle member {m.name}")
        tar.extractall(dest_root, filter="data")


def executor_token(jwt_secret: str, days: int = 400) -> str:
    """HS256 JWT for the executor job: role open_executor (only the four executor functions)."""
    import hashlib
    import hmac
    import time as _t
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    head = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = b64(json.dumps({"role": "open_executor", "iss": "open-track", "iat": int(_t.time()),
                           "exp": int(_t.time()) + days * 86400}, separators=(",", ":")).encode())
    sig = b64(hmac.new(jwt_secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())
    return f"{head}.{body}.{sig}"


def main(argv: list[str]) -> None:
    if argv[:1] == ["keygen"] and len(argv) == 2:
        keygen(argv[1])
        print(f"wrote {argv[1]}/private.pem (executor secret), public.pem, public.jwk.json (site)")
    elif argv[:1] == ["bundle"] and len(argv) == 3:
        if os.path.exists(argv[2]):
            raise SystemExit(f"refusing to overwrite {argv[2]}")
        key = base64.b64encode(os.urandom(32)).decode()
        with open(argv[2], "wb") as f:
            f.write(seal(pack_hidden(argv[1]), key))
        print("OPEN_TRACK_BUNDLE_KEY (store as the engine job secret; shown once):")
        print(key)
    elif argv[:1] == ["executor-token"] and len(argv) in (1, 2):
        secret = os.environ.get("SUPABASE_JWT_SECRET") or sys.stdin.readline().strip()
        print(executor_token(secret, int(argv[1]) if len(argv) == 2 else 400))
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
