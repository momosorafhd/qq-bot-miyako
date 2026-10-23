"""Probe a TCP port for batch scripts.

Usage:  port_check.py PORT [host]
Exit code 0 = something is listening, 1 = nothing there, 2 = bad usage.
"""

import socket
import sys


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: port_check.py PORT [host]")
        return 2
    try:
        port = int(sys.argv[1])
    except ValueError:
        print("bad port: %s" % sys.argv[1])
        return 2
    host = sys.argv[2] if len(sys.argv) > 2 else "127.0.0.1"

    s = socket.socket()
    s.settimeout(0.8)
    try:
        rc = s.connect_ex((host, port))
    except OSError:
        rc = 1
    finally:
        s.close()
    return 0 if rc == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
