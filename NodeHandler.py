import base64
import json
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

import requests


def get_geo(add: str) -> str:
    """获取 IP 地理位置"""
    api_url = f"http://ip-api.com/json/{add}"
    response = requests.get(api_url)
    data = response.json()

    if data["status"] == "success":
        country = data["country"]
        city = data["city"]

        return f"{country}({city})"


def get_nodes(text: str) -> str:
    """遍历文本处理节点信息"""
    for node in text.strip().splitlines():
        # scheme, body = node.split("://")
        #
        # if scheme == "vmess":
        #     body_str = base64.b64decode(body).decode("utf-8")
        #     node_dict = json.loads(body_str)
        #     node_dict["ps"] = get_geo(node_dict["add"])
        #     body_str = json.dumps(node_dict).encode("utf-8")
        #     body = base64.b64encode(body_str).decode("utf-8")
        #     node = f"{scheme}://{body}"
        #
        # elif scheme == "ssr":
        #     body_str = base64.b64decode(body).decode("utf-8")
        #     remarks = get_geo(body_str.split(":")[0]).encode("utf-8")
        #     remarks = base64.b64encode(remarks).decode("utf-8")
        #     url = urlsplit(scheme + body_str)
        #     params = parse_qs(url.query)
        #     params.update({"remarks": [remarks]})
        #     components = tuple([url.scheme, url.netloc, url.path,
        #                         urlencode(params), url.fragment])
        #     body_str = urlunsplit(components).encode("utf-8")
        #     body = base64.b64encode(body_str).decode("utf-8")
        #     node = f"{scheme}://{body}"
        #
        # elif scheme in ("trojan", "ss", "vless"):
        #     url = urlsplit(node)
        #     add = url.netloc.split("@")[-1].split(":")[0]
        #     fragment = get_geo(add)
        #     components = tuple([url.scheme, url.netloc, url.path,
        #                         url.query, quote(fragment)])
        #     node = urlunsplit(components)
        yield node
