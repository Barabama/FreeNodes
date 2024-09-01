# SimpleSpider.py

import os
import re
import datetime as dt
from urllib.parse import urljoin

import scrapy
from scrapy.http import Response

from NodeScrapy.items import NodeItem
from utils.Config import CONFIG, ConfigData


class SimpleSpider(scrapy.Spider):
    name = "simple"
    custom_settings = {"LOG_FILE": "scrapy.log",
                       "LOG_FILE_APPEND": False}
    targets = ("freenode", "wenode", "v2rayshare", "nodefree",)
    configs: dict[str, ConfigData]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configs = {name: CONFIG.get(name) for name in self.targets}

    def _find_link(self, name: str, text: str):
        for link in re.findall(self.configs[name]["pattern"], text):
            _, ext = os.path.splitext(link)
            if ext not in [".txt", ".yaml"]:
                self.logger.warning(f"{name} could not parse {link}, skipping")
                continue
            self.logger.info(f"{name} found {link}")
            yield link, ext

    def _parse_tag(self, name: str, tag: scrapy.Selector) -> tuple[str, dt.date]:
        link = tag.attrib.get("href")
        date = dt.date.today()
        if not link:
            return link, date
        pattern = re.compile(r"(?:\d{4}[-年])?(\d{1,2})[-月](\d{1,2})")
        for match in pattern.finditer(tag.get()):
            if not match:
                continue
            month, day = map(int, match.groups())
            if not 0 < month < 12 or not 0 < day < 32:
                continue
            date = dt.date(dt.date.today().year, month, day)
            self.logger.info(f"{name} found {link} on {date}")
            break
        return link, date

    def closed(self, reason):
        pass

    def start_requests(self):
        for name, config in self.configs.items():
            if not config:
                self.logger.error(f"{name} is not configured, exiting")
                continue
            self.logger.info(f"{name} start")
            yield scrapy.Request(config["start_url"], self.parse, meta={"name": name})

    def parse(self, response: Response):
        name = response.meta["name"]
        config = self.configs[name]
        css_selector = "a" + "".join(f"[{k}='{v}']" for k, v in config["attrs"].items())

        # Find the detail url and web_date
        relative_url = ""
        web_date = dt.date.today()
        for tag in response.css(css_selector):
            relative_url, web_date = self._parse_tag(name, tag)
            if not relative_url:
                continue
            break
        if not relative_url:
            self.logger.error(f"{name} could not found detail url, exiting")
            return
        detail_url = urljoin(config["start_url"], relative_url)

        # Compare web_date with up_date, DEBUG force update
        up_date = dt.datetime.strptime(config["up_date"], "%Y-%m-%d").date()
        if web_date <= up_date and not self.settings.getbool("FORCE"):
            self.logger.info(f"{name} is up to date, exiting")
            return

        self.logger.info(f"{name} needs update, accessing {detail_url}")
        response.meta.update({"date": web_date.strftime("%Y-%m-%d")})
        yield response.follow(detail_url, self.parse_detail, meta=response.meta)

    def parse_detail(self, response: Response):
        for link, ext in self._find_link(response.meta["name"], response.text):
            response.meta["ext"] = ext
            yield response.follow(link, self.parse_link, meta=response.meta)

    def parse_link(self, response: Response):
        item = NodeItem()
        item["name"] = response.meta["name"]
        item["ext"] = response.meta["ext"]
        item["date"] = response.meta["date"]
        item["body"] = response.text
        yield item
