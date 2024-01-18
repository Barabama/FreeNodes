import base64
import json
import threading
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from RequestHandler import make_request

add_rl = add_limits = 45
ips_rl = ips_limits = 15
add_ttl = ips_ttl = 60

params = {
    "lang": "zh-CN",
    "fields": "status,country,city,query"
}

add_lock = threading.Lock()
ips_lock = threading.Lock()
add_event = threading.Event()
ips_event = threading.Event()
add_event.set()
ips_event.set()


def get_geo(add: str) -> dict:
    """获取 IP 域名 地理位置"""
    global add_rl, add_ttl
    add_url = f"http://ip-api.com/json/{add}"

    if add_rl <= 0:
        add_event.clear()
        add_event.wait(timeout=add_ttl)
        add_rl = add_limits  # 重置
        add_event.set()

    add_event.wait()
    # 检查速率限制
    with add_lock:
        response = make_request("GET", add_url, params, timeout=20)
        add_rl -= 1  # = int(response.headers.get("X-Rl", 60))
        add_ttl = int(response.headers.get("X-Ttl", 60))

    return response.json() if response.text else {}


def get_geos(ips: list[str]) -> list[dict]:
    """获取 IP 地理位置"""
    global ips_rl, ips_ttl
    ips_url = "http://ip-api.com/batch"

    res = []
    for subs in [ips[i:i + 100] for i in range(0, len(ips), 100)]:

        if ips_rl <= 0:
            ips_event.clear()
            ips_event.wait(timeout=ips_ttl)
            ips_rl = ips_limits  # 重置
            ips_event.set()

        ips_event.wait()
        # 检查速率限制
        with ips_lock:
            response = make_request("POST", ips_url, params, json.dumps(subs))
            ips_rl -= 1  # = int(response.headers.get("X-Rl", 60))
            ips_ttl = int(response.headers.get("X-Ttl", 60))

        data = response.json() if response.text else []
        res.extend(data)

    return res


def get_address(node: str) -> str:
    """解析协议返回代理地址"""
    scheme, body = node.split("://")
    if scheme == "vmess":
        body_str = base64.b64decode(body).decode("utf-8")
        node_dict = json.loads(body_str)
        return node_dict["add"]
    elif scheme == "ssr":
        body_str = base64.b64decode(body).decode("utf-8")
        return body_str.split(":")[0]
    elif scheme in ("trojan", "ss", "vless"):
        url = urlsplit(node)
        return url.netloc.split("@")[-1].split(":")[0]


def write_remarks(node: str, remarks: str) -> str:
    """遍历文本处理节点信息"""
    scheme, body = node.split("://")

    if scheme == "vmess":
        body_str = base64.b64decode(body).decode("utf-8")
        node_dict = json.loads(body_str)
        node_dict["ps"] = remarks
        body_str = json.dumps(node_dict).encode("utf-8")
        body = base64.b64encode(body_str).decode("utf-8")
        node = f"{scheme}://{body}"

    elif scheme == "ssr":
        body_str = base64.b64decode(body).decode("utf-8")
        remarks = base64.b64encode(remarks.encode("utf-8")).decode("utf-8")
        url = urlsplit(scheme + body_str)
        query = parse_qs(url.query)
        query.update({"remarks": [remarks]})
        components = tuple([url.scheme, url.netloc, url.path,
                            urlencode(query), url.fragment])
        body_str = urlunsplit(components).encode("utf-8")
        body = base64.b64encode(body_str).decode("utf-8")
        node = f"{scheme}://{body}"

    elif scheme in ("trojan", "ss", "vless"):
        url = urlsplit(node)
        components = tuple([url.scheme, url.netloc, url.path,
                            url.query, quote(remarks)])
        node = urlunsplit(components)

    return node
