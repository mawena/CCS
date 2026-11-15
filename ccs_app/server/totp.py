"""Double authentification : codes TOTP à 6 chiffres (applications comme Aegis ou Google
Authenticator). Les secrets sont gardés par `ccs-auth` (root), un fichier par utilisateur."""

import io
import os
import re

import pyotp

from . import paths

ISSUER = "CCS"
_CODE = re.compile(r"^[0-9]{6}$")


def new_secret():
    return pyotp.random_base32()


def uri(user, secret, host):
    return pyotp.TOTP(secret).provisioning_uri(name=f"{user}@{host}", issuer_name=ISSUER)


def qr_svg(text):
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode("utf-8")


def verify(secret, code, now):
    """Code juste à ±30 s près (un pas de chaque côté)."""
    if not isinstance(code, str) or not _CODE.match(code) or not secret:
        return False
    try:
        return pyotp.TOTP(secret).verify(code, for_time=int(now), valid_window=1)
    except Exception:
        return False


def load(user):
    try:
        text = paths.totp_file(user).read_text(encoding="ascii").strip()
    except (FileNotFoundError, UnicodeDecodeError):
        return None
    return text or None


def save(user, secret):
    f = paths.totp_file(user)
    f.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(f.parent, 0o700)
    tmp = f.with_name(f".{f.name}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="ascii") as out:
        out.write(secret + "\n")
    os.replace(tmp, f)


def reset(user):
    try:
        paths.totp_file(user).unlink()
        return True
    except FileNotFoundError:
        return False
