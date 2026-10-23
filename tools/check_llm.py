"""DeepSeek 连通性自检：DNS -> TCP -> TLS -> API。

用法（双击 check-llm.bat 即可，不用手敲）：
    local\\venv\\Scripts\\python.exe check_llm.py
"""

import io
import json
import os
import socket
import ssl
import sys
import time

HOST = "api.deepseek.com"
PROXY = "http://127.0.0.1:7892"


def read_env(path=".env"):
    d = {}
    with io.open(path, encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip()
    return d


def step(title):
    print(f"\n[{title}]")


def check_key_hygiene(path=".env"):
    """Key 里混入空白字符会让 HTTP 头非法，表现为 "APIConnectionError"。

    这个检查放在最前面，因为它是唯一一个"网络全绿但机器人就是不通"的原因。
    """
    step("0/4 API Key 字符串检查")
    try:
        with io.open(path, encoding="utf-8") as f:
            for line in f:
                if line.startswith("DEEPSEEK_API_KEY="):
                    raw = line.split("=", 1)[1].rstrip("\n").rstrip("\r")
                    tail = len(raw) - len(raw.rstrip())
                    if raw != raw.strip():
                        print(f"  WARN  行尾有 {tail} 个空白字符")
                        print("        AstrBot 会把它拼进 Authorization 头，被判为非法请求头，")
                        print("        报出来就是 APIConnectionError: Connection error.")
                        print("        修法：.env 里这行删掉重打，末尾不要留空格。")
                        return False
                    print(f"  OK    无空白字符，长度 {len(raw)}")
                    return True
    except FileNotFoundError:
        print("  FAIL  找不到 .env")
        return False
    print("  FAIL  .env 里没有 DEEPSEEK_API_KEY 这一行")
    return False


def check_dns():
    step("1/4 DNS 解析")
    try:
        t0 = time.time()
        infos = socket.getaddrinfo(HOST, 443, socket.AF_UNSPEC, socket.SOCK_STREAM)
        ips = sorted({i[4][0] for i in infos})
        print(f"  OK  {HOST} -> {', '.join(ips)}  ({time.time() - t0:.2f}s)")
        return True
    except Exception as e:
        print(f"  FAIL  {type(e).__name__}: {e}")
        print("        可能是 DNS 污染或断网。换 DNS / 关掉代理软件的 Tun 模式再试。")
        return False


def check_tcp():
    step("2/4 TCP 443 连接")
    try:
        t0 = time.time()
        with socket.create_connection((HOST, 443), timeout=10):
            pass
        print(f"  OK  建连成功  ({time.time() - t0:.2f}s)")
        return True
    except Exception as e:
        print(f"  FAIL  {type(e).__name__}: {e}")
        print("        端口被挡。检查防火墙 / 代理软件规则。")
        return False


def check_tls():
    step("3/4 TLS 握手")
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((HOST, 443), timeout=10) as raw:
            with ctx.wrap_socket(raw, server_hostname=HOST) as s:
                cert = s.getpeercert()
                cn = ""
                for part in cert.get("subject", ()):
                    for k, v in part:
                        if k == "commonName":
                            cn = v
                print(f"  OK  握手成功  证书 CN={cn}  协议={s.version()}")
        return True
    except ssl.SSLCertVerificationError as e:
        print(f"  FAIL  证书校验失败: {e}")
        print("        有软件在做 TLS 中间人。把这个软件的根证书装进系统信任区，或关掉它。")
        return False
    except Exception as e:
        print(f"  FAIL  {type(e).__name__}: {e}")
        print("        握手被重置，通常是中间设备按域名拦截。")
        return False


def check_api(key, proxy=None):
    from openai import OpenAI
    import httpx

    label = f"经代理 {proxy}" if proxy else "直连"
    step(f"4/4 API 调用（{label}）")
    try:
        kwargs = {"api_key": key, "base_url": "https://api.deepseek.com/v1", "timeout": 45}
        if proxy:
            kwargs["http_client"] = httpx.Client(proxy=proxy, timeout=45)
        c = OpenAI(**kwargs)
        t0 = time.time()
        r = c.chat.completions.create(
            model="deepseek-flash",
            messages=[{"role": "user", "content": "只回答两个字：在线"}],
            max_tokens=16,
            extra_body={"thinking": {"type": "disabled"}},
        )
        print(f"  OK  {r.choices[0].message.content!r}  ({time.time() - t0:.2f}s)")
        return True
    except Exception as e:
        msg = str(e)[:200]
        print(f"  FAIL  {type(e).__name__}: {msg}")
        cause = e.__cause__
        if cause:
            print(f"        底层原因: {type(cause).__name__}: {str(cause)[:200]}")
        if "401" in msg or "Authentication" in msg:
            print("        Key 无效或已失效，去 platform.deepseek.com 重新生成。")
        elif "402" in msg or "Insufficient" in msg:
            print("        账户余额不足。")
        elif "404" in msg:
            print("        模型名或 api_base 不对。")
        return False


def main():
    os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print("=" * 56)
    print(" DeepSeek 连通性自检")
    print("=" * 56)

    env = read_env()
    key = env.get("DEEPSEEK_API_KEY", "")
    if not key:
        print("\n[!] .env 里 DEEPSEEK_API_KEY 是空的，先填上再测。")
        return 2

    key_ok = check_key_hygiene()

    dns_ok = check_dns()
    tcp_ok = dns_ok and check_tcp()
    tls_ok = tcp_ok and check_tls()

    if tls_ok:
        if check_api(key):
            print("\n=> 结论：直连正常，机器人应该能正常回复。")
            if not key_ok:
                print("   [重要] 但上面的 Key 检查没通过：直接用 AstrBot 启动仍会报")
                print("   APIConnectionError。先按提示修好 .env，再启动。")
                return 1
            return 0
        print("\n=> 直连失败，改试本机 Clash 代理 ...")
        if check_api(key, PROXY):
            print(f"\n=> 结论：需要走代理。在 AstrBot 后台把 provider 的 proxy 填 {PROXY}")
            return 0
        print("\n=> 结论：直连和代理都不通，检查网络或换节点。")
        return 1

    print("\n=> 结论：网络层就不通，先解决 DNS/TLS，再看 API。")
    return 1


if __name__ == "__main__":
    sys.exit(main())
