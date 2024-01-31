import json
import re
import threading
from base64 import b64decode, b64encode
from typing import TypedDict, Generator
from urllib.parse import quote, SplitResult, urlsplit, urlunsplit

from RequestHandler import make_request

prot_sep = "://"

add_rl = add_limits = 45
ips_rl = ips_limits = 15
add_ttl = ips_ttl = 60

params = {"lang": "zh-CN",
          "fields": "status,country,city,query"}


class ResData(TypedDict):
    status: str  # 状态
    country: str  # 国家
    city: str  # 城市
    query: str  # 地址


lock = threading.Lock()
event = threading.Event()
event.set()


def get_geo(add: str) -> ResData:
    """获取 IP 域名 地理位置"""
    global add_rl, add_ttl
    url = f"http://ip-api.com/json/{add}"

    if add_rl <= 0:
        event.clear()
        event.wait(timeout=add_ttl)
        add_rl = add_limits  # 重置
        event.set()

    event.wait()
    # 检查速率限制
    with lock:
        response = make_request("GET", url, params, timeout=20)
        add_rl -= 1  # = int(response.headers.get("X-Rl", 60))
        add_ttl = int(response.headers.get("X-Ttl", 60))

    return response.json() if response.text else {}


def get_geos(ips: list[str]) -> list[ResData]:
    """获取 IP 地理位置"""
    global ips_rl, ips_ttl
    url = "http://ip-api.com/batch"

    res: list[ResData] = []
    for subs in [ips[i:i + 100] for i in range(0, len(ips), 100)]:
        if ips_rl <= 0:
            event.clear()
            event.wait(timeout=ips_ttl)
            ips_rl = ips_limits  # 重置
            event.set()

        event.wait()
        # 检查速率限制
        with lock:
            response = make_request("POST", url, params,
                                    json.dumps(subs), timeout=5)
            ips_rl -= 1  # = int(response.headers.get("X-Rl", 60))
            ips_ttl = int(response.headers.get("X-Ttl", 60))

        data = response.json() if response.text else []
        res.extend(data)

    return res


def is_base64(string: str) -> bool:
    """判断字符串是否为 base64"""
    return bool(re.match(r"^[A-Za-z0-9+/=]+$", string))


class VMESS(TypedDict):
    v: str  # 协议版本号
    ps: str  # 服务器别名
    add: str  # 服务器地址
    port: int  # 服务器端口号
    id: str  # 用户ID
    aid: int  # 额外ID
    scy: str  # 加密方式, auto/aes-128-gcm
    net: str  # 传输协议, tcp/kcp/ws
    type: str  # 伪装类型
    host: str  # 伪装域名
    path: str  # 路径
    tls: str  # 启用TLS加密, tls


class VLESS(TypedDict):
    id: str  # 用户ID
    add: str  # 服务器地址
    port: int  # 服务器端口号
    query: str  # 其它参数
    fragment: str  # 服务器别名


class VMESSParser:
    scheme = "vmess"
    body: VMESS

    @classmethod
    def parse(cls, scheme: str, body: str) -> VMESS:
        cls.scheme = scheme
        body_str = b64decode(body).decode("utf-8")
        body_dict: dict = json.loads(body_str)
        cls.body = VMESS(**body_dict)
        return cls.body

    @classmethod
    def get_add(cls) -> str:
        return cls.body["add"]

    @classmethod
    def set_remarks(cls, remarks: str):
        cls.body["ps"] = remarks

    @classmethod
    def pack(cls) -> str:
        body_str = json.dumps(cls.body).encode("utf-8")
        body = b64encode(body_str).decode("utf-8")
        return cls.scheme + prot_sep + body


class VLESSParser:
    scheme: str
    body: VLESS
    url: SplitResult

    @classmethod
    def parse(cls, scheme: str, body: str) -> VLESS:
        cls.scheme = scheme
        cls.url = urlsplit("//" + body, scheme)
        id, rest = cls.url.netloc.split("@")
        add, port = rest.split(":")
        cls.body = VLESS(id=id,
                         add=add,
                         port=port,
                         query=cls.url.query,
                         fragment=cls.url.fragment)
        return cls.body

    @classmethod
    def get_add(cls) -> str:
        return cls.body["add"]

    @classmethod
    def set_remarks(cls, remarks: str):
        cls.body["fragment"] = quote(remarks)

    @classmethod
    def pack(cls) -> str:
        components = tuple([
            cls.scheme,
            cls.url.netloc,
            cls.url.path,
            cls.body["query"],
            quote(cls.body["fragment"])])
        return urlunsplit(components)


class Parser(VMESSParser, VLESSParser):
    scheme: str
    parsers = {"vmess": VMESSParser,
               "vless": VLESSParser,
               "trojan": VLESSParser,
               "socks": VLESSParser,
               "ss": VLESSParser}
    parser: VMESSParser | VLESSParser
    body: VMESS | VLESS

    def parse(self, scheme: str, body: str) -> VMESS | VLESS:
        self.scheme = scheme
        self.parser = self.parsers[scheme]()
        self.body = self.parser.parse(scheme, body)
        return self.body

    def get_add(self) -> str:
        return self.parser.get_add()

    def set_remarks(self, remarks: str):
        self.parser.set_remarks(remarks)

    def pack(self) -> str:
        return self.parser.pack()


class NodeHandler:
    nodes: list[list[str]]
    adds: list[str]
    parser = Parser()

    def __init__(self, nodes_str: str):
        nodes_str = nodes_str if not is_base64(nodes_str) \
            else b64decode(nodes_str).decode("utf-8")

        for node in nodes_str.strip().splitlines():
            if prot_sep not in node: continue

            scheme, body = node.split(prot_sep)
            self.parser.parse(scheme, body)
            self.adds.append(self.parser.get_add())
            self.nodes.append([scheme, body])

    def set_remarks(self) -> Generator[str, None, None]:
        """生成处理后的节点"""
        geos = get_geos(self.adds)
        for i, geo in enumerate(geos):
            if geo.get("status", "fail") == "fail":
                geo = get_geo(geo["query"])  # 域名再识别

            remarks = "Unknown" if geo["status"] == "fail" \
                else f"{geo["country"]}_{geo["city"]}"

            scheme, body = self.nodes[i]
            self.parser.parse(scheme, body)
            self.parser.set_remarks(remarks)
            yield self.parser.pack()
