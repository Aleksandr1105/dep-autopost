#!/usr/bin/env python3
"""
Шифрование постов, чтобы репозиторий можно было держать публичным.

Открытый ключ (public_key.pem) лежит в репозитории: им посты шифруют, расшифровать им нельзя.
Закрытый ключ хранится только в секрете GitHub DEP_KEY: им бот расшифровывает посты перед публикацией.

  python crypto_box.py encrypt week-2026-11-16.json cards/*.png   зашифровать (оригиналы удаляются)
  python crypto_box.py decrypt-all                                 расшифровать все *.enc (нужен DEP_KEY)

Формат .enc: «DEP1» | длина ключа (2 байта) | AES-ключ, зашифрованный RSA-OAEP | nonce (12 байт) | AES-256-GCM.
"""
import os
import sys
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

HERE = Path(__file__).resolve().parent
MAGIC = b"DEP1"
OAEP = padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None)


def encrypt_bytes(data: bytes, public_pem: bytes) -> bytes:
    pub = serialization.load_pem_public_key(public_pem)
    key, nonce = AESGCM.generate_key(256), os.urandom(12)
    wrapped = pub.encrypt(key, OAEP)
    return MAGIC + len(wrapped).to_bytes(2, "big") + wrapped + nonce + AESGCM(key).encrypt(nonce, data, None)


def decrypt_bytes(blob: bytes, private_pem: bytes) -> bytes:
    if blob[:4] != MAGIC:
        raise ValueError("не зашифрованный файл")
    n = int.from_bytes(blob[4:6], "big")
    wrapped, nonce, body = blob[6:6 + n], blob[6 + n:18 + n], blob[18 + n:]
    priv = serialization.load_pem_private_key(private_pem, password=None)
    return AESGCM(priv.decrypt(wrapped, OAEP)).decrypt(nonce, body, None)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "encrypt":
        pub = (HERE / "public_key.pem").read_bytes()
        for name in sys.argv[2:]:
            src = Path(name)
            Path(str(src) + ".enc").write_bytes(encrypt_bytes(src.read_bytes(), pub))
            src.unlink()
            print("зашифрован:", src)
    elif cmd == "decrypt-all":
        key = os.environ.get("DEP_KEY", "").strip()
        if not key:
            sys.exit("Не задан секрет DEP_KEY (GitHub → Settings → Secrets and variables → Actions).")
        n = 0
        for enc in sorted(HERE.rglob("*.enc")):
            enc.with_suffix("").write_bytes(decrypt_bytes(enc.read_bytes(), key.encode()))
            n += 1
        print(f"Расшифровано файлов: {n}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
