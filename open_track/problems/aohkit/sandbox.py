"""macOS sandbox-exec profiles for validation.

agent_profile(workdir): a contestant agent may read only its own round dir plus system/Python paths, may write only
inside workdir/_scratch, and may only talk to the runner's LLM proxy on localhost.
pi_profile(workdir): pi may read its round dir, its own install and ~/.pi (model auth), write only its round dir,
and use the network (it needs the model API).
pi_profile_v2(workdir, pidir, port): like pi_profile, but network only to the organizer's localhost model relay
(aohkit/pi_proxy.py) on <port>, and no writes outside the round dir / config dir (incl. /private/tmp, /private/var/folders).
Everything else under the user's home — notably the repository's _hidden and other problems — is denied.
"""
import os

HOME = os.path.expanduser("~")


def _q(p):
    return '"' + os.path.realpath(p).replace('"', '') + '"'


def agent_profile(workdir: str) -> str:
    w = _q(workdir)
    return f"""(version 1)
(allow default)
(deny file-read* (subpath {_q(HOME)}) (subpath "/private/tmp") (subpath "/private/var/folders") (subpath "/Volumes"))
(allow file-read* (literal {_q(HOME)}) (subpath {w}))
(deny file-write* (subpath {_q(HOME)}) (subpath "/private/tmp") (subpath "/private/var/folders"))
(allow file-write* (subpath {_q(os.path.join(workdir, '_scratch'))}))
(deny network*)
(allow network-outbound (remote ip "localhost:*"))
(allow network-inbound (local ip "localhost:*"))
"""


def pi_profile(workdir: str, pidir: str) -> str:
    """pi reads/writes only its round dir and its own per-round config dir (a filtered copy of ~/.pi/agent that
    contains just the tokenflux provider with just its default model); network is allowed for the model API."""
    w, pd = _q(workdir), _q(pidir)
    return f"""(version 1)
(allow default)
(deny file-read* (subpath {_q(HOME)}) (subpath "/private/tmp/claude-501") (subpath "/Volumes"))
(allow file-read* (literal {_q(HOME)}) (subpath {w}) (subpath {pd}))
(deny file-write* (subpath {_q(HOME)}))
(allow file-write* (subpath {w}) (subpath {pd}))
"""


def pi_profile_v2(workdir: str, pidir: str, port: int, local_ports=()) -> str:
    """Stricter pi sandbox (2026-10-12): reads only its round dir + config dir (plus system paths), writes only those
    two dirs (TMPDIR must point inside the round dir), and network ONLY to the organizer's localhost relay on <port>,
    which itself admits only tokenflux Deepseek/deepseek-flash. pi's config holds a dummy key; the relay holds the
    real one."""
    w, pd = _q(workdir), _q(pidir)
    return f"""(version 1)
(allow default)
(deny file-read* (subpath {_q(HOME)}) (subpath "/private/tmp") (subpath "/Volumes"))
(allow file-read* (literal {_q(HOME)}) (subpath {w}) (subpath {pd}))
(deny file-write* (subpath {_q(HOME)}) (subpath "/private/tmp") (subpath "/private/var/folders") (subpath "/Volumes"))
(allow file-write* (subpath {w}) (subpath {pd}))
(deny network*)
(allow network-outbound (remote ip "localhost:{int(port)}"))
""" + "".join(f"""(allow network-bind (local ip "localhost:{int(p)}"))
(allow network-inbound (local ip "localhost:{int(p)}"))
(allow network-outbound (remote ip "localhost:{int(p)}"))
""" for p in local_ports)


if __name__ == "__main__":
    import sys
    if sys.argv[1] == "pi2":
        print(pi_profile_v2(sys.argv[2], sys.argv[3], int(sys.argv[4]), [int(x) for x in sys.argv[5].split(",")] if len(sys.argv) > 5 else ()))
    else:
        print(pi_profile(sys.argv[2], sys.argv[3]) if sys.argv[1] == "pi" else agent_profile(sys.argv[2]))
