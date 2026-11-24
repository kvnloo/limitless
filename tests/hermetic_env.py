"""Keep every test, in-process or child process, off the host's real Limitless config, state and audit log.

Every tests/test_*.py imports this module as its first import (test_hermetic_guard.py enforces it), so the
isolation is in place for a full `discover` run and for a single-file run alike:

- every LIMITLESS_* variable (but the test-only LIMITLESS_GLIDE_SRC) is dropped and HOME points at an empty temp dir;
- Path.home(), Path.expanduser() and os.path.expanduser() resolve "~" to that dir even while a test has
  cleared os.environ (without HOME they would fall back to the passwd entry, which is the real home);
- child_env() builds the env= of every subprocess a test starts, so a child interpreter, where none of the
  in-process patches exist, still gets a HOME that is never the real one.
"""
import os
import posixpath
import tempfile
from pathlib import Path

try:
    import pwd
except ImportError:  # not POSIX
    pwd = None

# LIMITLESS_GLIDE_SRC only points test_glide_contract at a Glide checkout; the library never reads it.
KEEP = {"LIMITLESS_GLIDE_SRC"}
for _k in [k for k in os.environ if k.startswith("LIMITLESS_") and k not in KEEP]:
    del os.environ[_k]
TEST_HOME = Path(tempfile.mkdtemp(prefix="limitless-test-home-"))
os.environ["HOME"] = str(TEST_HOME)

_real_expanduser = posixpath.expanduser


def _passwd_home():
    if pwd is None:
        return None
    try:
        return pwd.getpwuid(os.getuid()).pw_dir
    except (KeyError, OSError):
        return None


def _expanduser(path):
    """os.path.expanduser, except "~" and "~/..." never fall back to the passwd entry when HOME is unset."""
    s = os.fspath(path)
    tilde, sep = ("~", "/") if isinstance(s, str) else (b"~", b"/")
    if os.environ.get("HOME") or not (s == tilde or s.startswith(tilde + sep)):
        return _real_expanduser(path)
    home = str(TEST_HOME) if isinstance(s, str) else os.fsencode(str(TEST_HOME))
    return home + s[1:]


def _path_expanduser(self):
    if not (self.drive or self.root) and self.parts and self.parts[0][:1] == "~":
        return type(self)(_expanduser(str(self)))
    return self


posixpath.expanduser = _expanduser  # os.path is posixpath here; pathlib on 3.12+ calls it too
Path.home = classmethod(lambda cls: cls(TEST_HOME))
Path.expanduser = _path_expanduser


def child_env(base=None, **extra):
    """The env= for a subprocess: a copy of `base` (os.environ when None) plus `extra`, with HOME set.

    A HOME the caller already chose (a test's own temp dir) is kept; a missing or empty one becomes the test
    home. A HOME that is the passwd home is refused, so a child can never read the real config.
    """
    env = dict(os.environ if base is None else base)
    env.update(extra)
    if not env.get("HOME"):
        env["HOME"] = str(TEST_HOME)
    real = _passwd_home()
    if real and os.path.realpath(env["HOME"]) == os.path.realpath(real):
        raise RuntimeError("a test child process would run with the real HOME")
    return env
