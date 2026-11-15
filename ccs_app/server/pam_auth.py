"""Comptes Ubuntu : mot de passe vérifié par PAM (service `ccs`, appel direct de libpam par
ctypes) et droit d'accès par le groupe Unix `ccs`. `root` (et tout uid 0) est toujours refusé."""

import ctypes
import ctypes.util
import grp
import logging
import os
import pwd

from . import paths

log = logging.getLogger("ccs.pam")

PAM_SUCCESS = 0
PAM_PROMPT_ECHO_OFF = 1
PAM_PROMPT_ECHO_ON = 2
PAM_CONV_ERR = 19


class PamMessage(ctypes.Structure):
    _fields_ = [("msg_style", ctypes.c_int), ("msg", ctypes.c_char_p)]


class PamResponse(ctypes.Structure):
    # `resp` est alloué par la libc (strdup) : PAM le libère lui-même.
    _fields_ = [("resp", ctypes.c_void_p), ("resp_retcode", ctypes.c_int)]


CONV_FUNC = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int,
                             ctypes.POINTER(ctypes.POINTER(PamMessage)),
                             ctypes.POINTER(ctypes.POINTER(PamResponse)), ctypes.c_void_p)


class PamConv(ctypes.Structure):
    _fields_ = [("conv", CONV_FUNC), ("appdata_ptr", ctypes.c_void_p)]


_libc = ctypes.CDLL(ctypes.util.find_library("c"))
_libc.calloc.restype = ctypes.c_void_p
_libc.calloc.argtypes = (ctypes.c_size_t, ctypes.c_size_t)
_libc.strdup.restype = ctypes.c_void_p
_libc.strdup.argtypes = (ctypes.c_char_p,)
_libc.free.argtypes = (ctypes.c_void_p,)
_libpam = None


def _real_lib():
    global _libpam
    if _libpam is None:
        lib = ctypes.CDLL(ctypes.util.find_library("pam") or "libpam.so.0")
        handle_p = ctypes.POINTER(ctypes.c_void_p)
        lib.pam_start.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(PamConv), handle_p)
        lib.pam_start.restype = ctypes.c_int
        for name in ("pam_authenticate", "pam_acct_mgmt", "pam_end"):
            getattr(lib, name).argtypes = (ctypes.c_void_p, ctypes.c_int)
            getattr(lib, name).restype = ctypes.c_int
        _libpam = lib
    return _libpam


def authenticate(user, password, service="ccs", lib=None):
    """Vrai si PAM accepte ce mot de passe et ce compte. Ne lève jamais."""
    if not user or not password or "\0" in user or "\0" in password:
        return False
    user_b, pass_b = user.encode("utf-8"), password.encode("utf-8")

    def conversation(n, messages, response, _appdata):
        if n <= 0:
            return PAM_CONV_ERR
        block = _libc.calloc(n, ctypes.sizeof(PamResponse))
        if not block:
            return PAM_CONV_ERR
        replies = ctypes.cast(block, ctypes.POINTER(PamResponse))
        for i in range(n):
            style = messages[i].contents.msg_style
            if style == PAM_PROMPT_ECHO_OFF:
                replies[i].resp = _libc.strdup(pass_b)
            elif style == PAM_PROMPT_ECHO_ON:
                replies[i].resp = _libc.strdup(user_b)
            replies[i].resp_retcode = 0
        response[0] = replies
        return PAM_SUCCESS

    conv = PamConv(CONV_FUNC(conversation), None)
    handle = ctypes.c_void_p()
    try:
        lib = lib or _real_lib()
        rc = lib.pam_start(service.encode(), user_b, ctypes.byref(conv), ctypes.byref(handle))
        if rc != PAM_SUCCESS:
            return False
        try:
            rc = lib.pam_authenticate(handle, 0)
            if rc == PAM_SUCCESS:
                rc = lib.pam_acct_mgmt(handle, 0)
            return rc == PAM_SUCCESS
        finally:
            lib.pam_end(handle, rc)
    except Exception:
        log.warning("PAM indisponible pour cette vérification")
        return False


def allowed(user, group="ccs", getpwnam=pwd.getpwnam, getgrnam=grp.getgrnam,
            getgrouplist=os.getgrouplist):
    """Le compte existe, n'est pas root (ni uid 0) et appartient au groupe `group`."""
    try:
        paths.check_user(user)
        pw = getpwnam(user)
        if user == "root" or pw.pw_uid == 0:
            return False
        gid = getgrnam(group).gr_gid
        return gid in getgrouplist(user, pw.pw_gid)
    except (KeyError, ValueError, OSError):
        return False
