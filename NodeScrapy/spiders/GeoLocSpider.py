# GeoLocSpider.py

import os
import time
from typing import TypedDict

import scrapy
import scrapy.http
import yaml

from NodeScrapy.items import GeoLocItem
from utils.GeoLoc import Parser


addr_limit = 45
ips_limit = 15
max_ttl = 60
params = "lang=zh-CN&fields=status,country,city,query"


class RespData(TypedDict):
    status: str
    country: str
    city: str
    query: str


class GeoLocSpider(scrapy.Spider):
    name = "geoloc"
    # custom_settings = {"LOG_FILE": "geoloc.log",
    #                    "LOG_FILE_APPEND": False,
    #                    "LOG_LEVEL": "DEBUG"}
    folder: str
    files = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.addr_rl = addr_limit
        self.ips_rl = ips_limit
        self.addr_ttl = max_ttl
        self.ips_ttl = max_ttl
        self.parser = Parser()

    def _req_geolocs(self, filename: str, nodes: list[str], ips: list[str]):
        """Get geolocations of a list of IPs."""
        url = f"http://ip-api.com/batch"
        for i in range(0, len(nodes), 100):
            for nodes, ips in zip(nodes[i:i + 100], ips[i:i + 100]):
                yield scrapy.http.JsonRequest(
                    f"{url}?{params}", self.parse_batch, "POST", data=ips,
                    meta={"file": filename, "nodes": nodes, "ips": ips})

    def _req_geoloc(self, filename: str, node: str, addr: str):
        """Get geolocation of an IP/domain."""
        url = f"http://ip-api.com/json/{addr}"
        yield scrapy.http.JsonRequest(
            f"{url}?{params}", self.parse_single, "GET",
            meta={"file": filename, "node": node, "addr": addr})

    def start_requests(self):
        self.folder = self.settings.get("PRIMARY_FOLDER")
        for filename in os.listdir(self.folder):
            self.files[filename] = {"nodes": [], "addrs": []}

            with open(os.path.join(self.folder, filename), "r", encoding="utf-8") as file:
                self.logger.info(f"reading {filename}")
                if filename.endswith(".txt"):
                    for node in file.readlines():
                        node.strip()
                        try:
                            addr = self.parser.get_addr(node)
                            self.files[filename]["nodes"].append(node)
                            self.files[filename]["addrs"].append(addr)
                        except Exception as e:
                            self.logger.warning(f"{filename}, {node}, {e}")
                            continue
                elif filename.endswith(".yaml"):
                    for node in yaml.safe_load(file)["proxies"]:
                        try:
                            self.files[filename]["nodes"].append(node)
                            self.files[filename]["addrs"].append(node["server"])
                        except Exception as e:
                            self.logger.warning(f"{filename} parsed {node}, got {e}")
                            continue
                else:
                    self.logger.error(f"Invalid file {filename}")

            yield from self._req_geolocs(filename, self.files[filename]["nodes"],
                                         self.files[filename]["addrs"])

    def parse_batch(self, response):
        filename = response.meta["file"]
        nodes = response.meta["nodes"]
        ips = response.meta["ips"]

        # Check requests limits
        self.ips_rl = int(response.headers.get("X-Rl", max_ttl))
        self.ips_ttl = int(response.headers.get("X-Ttl", max_ttl))
        if response.status == 429 or self.ips_rl < 1:
            self.logger.warning(f"Too many requests from batch, sleeping for {self.ips_ttl}s")
            time.sleep(self.ips_ttl)
            self.ips_rl = ips_limit
            yield from self._req_geolocs(filename, nodes, ips)

        for node, resp in zip(nodes, response.json()):
            resp = RespData(**resp)
            if resp["status"] == "success":
                geoloc = f"{resp['country']}_{resp['city']}"
                item = GeoLocItem(filename=filename, geoloc=geoloc, node=node)
                yield item

            elif resp["status"] == "fail":
                yield from self._req_geoloc(filename, nodes, ips)

            else:
                self.logger.error(f"{filename} requested {node}, got {resp}")

    def parse_single(self, response):
        filename = response.meta["file"]
        node = response.meta["node"]
        addr = response.meta["addr"]

        # Check requests limits
        self.addr_rl = int(response.headers.get("X-Rl", max_ttl))
        self.addr_ttl = int(response.headers.get("X-Ttl", max_ttl))
        if response.status == 429 or self.addr_rl < 1:
            self.logger.warning(f"Too many requests from single, sleeping for {self.addr_ttl}s")
            time.sleep(self.addr_ttl)
            self.addr_rl = addr_limit
            yield from self._req_geoloc(filename, node, addr)

        resp = RespData(**response.json())
        geoloc = "Unknown" if resp["status"] == "fail" else \
            f"{resp['country']}_{resp['city']}"
        item = GeoLocItem(filename=filename, geoloc=geoloc, node=node)
        yield item
