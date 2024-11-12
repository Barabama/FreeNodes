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
                       "LOG_FILE_APPEND": False,
                       "LOG_LEVEL": "INFO"}
    targets = ("clashmeta", "ndnode", "nodev2ray",
               "nodefree", "v2rayshare", "wenode")
    configs: dict[str, ConfigData]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configs = {name: CONFIG.get(name) for name in self.targets}

    def _find_link(self, name: str, text: str):
        """Find links in text and yield them with their extension."""
        for link in re.findall(self.configs[name]["pattern"], text):
            _, ext = os.path.splitext(link.strip())
            if ext not in (".txt", ".yaml"):
                self.logger.warning(f"{name} could not parse {link}, skipping")
                continue
            self.logger.info(f"{name} found {link}")
            yield link, ext

    def _parse_tag(self, name: str, tag: scrapy.Selector) -> tuple[str, dt.date]:
        """Parse tag and yield link and date."""
        link = tag.attrib.get("href", "")
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

        up_date = dt.datetime.strptime(config["up_date"], "%Y-%m-%d").date()
        tag_iter = iter(self._parse_tag(name, tag) for tag in response.css(config["selector"]))

        # First three links are the most recent ones.
        for rel_url, web_date in list(filter(lambda x: x[0], tag_iter))[0:3]:
            if web_date <= up_date and not self.settings.getbool("FORCE"):
                self.logger.info(f"{name} is up to date, exiting")
                continue

            blog_url = urljoin(config["start_url"], rel_url)
            self.logger.info(f"{name} needs update, accessing {blog_url}")
            response.meta["date"] = web_date.strftime("%Y-%m-%d")
            yield response.follow(blog_url, self.parse_blog, meta=response.meta)

    def parse_blog(self, response: Response):
        """Parse blog and yield links of nodes."""
        for link, ext in self._find_link(response.meta["name"], response.text):
            response.meta["ext"] = ext
            yield response.follow(link, self.parse_link, meta=response.meta)

    def parse_link(self, response: Response):
        """Parse link text and pack up as item."""
        item = NodeItem()
        item["name"] = response.meta["name"]
        item["ext"] = response.meta["ext"]
        item["date"] = response.meta["date"]
        item["body"] = response.text
        yield item
