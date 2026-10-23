"""给批处理用的探针：9880 有服务就退出码 0，没有就 1。"""

import socket
import sys

s = socket.socket()
s.settimeout(0.8)
try:
    s.connect(("127.0.0.1", 9880))
    s.close()
    sys.exit(0)
except OSError:
    sys.exit(1)
