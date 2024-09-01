# GeoLoc.py

import json
import re

from base64 import b64decode, b64encode
from typing import TypedDict
from urllib.parse import quote, SplitResult, urlsplit, urlunsplit


def base64decode(string: str) -> str:
    """Decodes a base64 string."""
    return string if not bool(re.match(r"^[A-Za-z0-9+/=]+$", string)) \
        else b64decode(string).decode("utf-8")


class VMESS(TypedDict, total=False):
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
    uuid: str  # 用户ID
    addr: str  # 服务器地址
    port: int  # 服务器端口号
    query: str  # 其它参数
    fragment: str  # 服务器别名


class VMESSParser:
    scheme = "vmess"
    body: VMESS

    @classmethod
    def _parse(cls, scheme: str, body: str) -> VMESS:
        cls.scheme = scheme
        body_str = b64decode(body).decode("utf-8")
        cls.body = VMESS(**json.loads(body_str))
        return cls.body

    @classmethod
    def get_addr(cls) -> str:
        return cls.body["add"]

    @classmethod
    def set_remarks(cls, remarks: str):
        cls.body["ps"] = remarks

    @classmethod
    def _pack(cls) -> str:
        body_str = json.dumps(cls.body).encode("utf-8")
        body = b64encode(body_str).decode("utf-8")
        return f"{cls.scheme}://{body}"


class VLESSParser:
    scheme: str
    body: VLESS
    url: SplitResult

    @classmethod
    def _parse(cls, scheme: str, body: str) -> VLESS:
        cls.scheme = scheme

        s1, s2 = body.split("#")
        body = f"{base64decode(s1)}#{s2}"
        cls.url = urlsplit(f"//{body}", scheme)
        uuid, rest = cls.url.netloc.split("@")
        addr, port = rest.split(":")
        cls.body = VLESS(uuid=uuid, addr=addr, port=port,
                         query=cls.url.query, fragment=cls.url.fragment)
        return cls.body

    @classmethod
    def get_addr(cls) -> str:
        return cls.body["addr"]

    @classmethod
    def set_remarks(cls, remarks: str):
        cls.body["fragment"] = quote(remarks)

    @classmethod
    def _pack(cls) -> str:
        return urlunsplit((cls.scheme, cls.url.netloc, cls.url.path,
                           cls.body["query"], cls.body["fragment"]))


parsers = {"vmess": VMESSParser, "vless": VLESSParser,
           "trojan": VLESSParser, "socks": VLESSParser, "ss": VLESSParser}


class Parser(VMESSParser, VLESSParser):
    scheme: str
    body: VMESS | VLESS
    parser: VMESSParser | VLESSParser

    def __init__(self):
        self.scheme = ""
        self.body = {}
        self.parser = None

    def _parse(self, url: str):
        scheme, body = url.split("://")
        self.scheme = scheme
        self.parser = parsers[scheme]()
        self.body = self.parser._parse(scheme, body)

    def _pack(self) -> str:
        return self.parser._pack()

    def get_addr(self, url="") -> str:
        if url:
            self._parse(url)
        return self.parser.get_addr()

    def set_remarks(self, url="", remarks="") -> str:
        if url:
            self._parse(url)
        self.parser.set_remarks(remarks)
        pack = self._pack()
        self.__init__()
        return pack
