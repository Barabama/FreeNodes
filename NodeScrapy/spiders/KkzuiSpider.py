# KkzuiSpider.py

import re

from selenium.webdriver.common.by import By
from scrapy.http import Response

from NodeScrapy.spiders.DecryptSpider import DecryptSpider
from utils.Config import CONFIG, ConfigData


class KkzuiSpider(DecryptSpider):
    name = "kkzui"
    custom_settings = {"LOG_FILE": "scrapy.log",
                       "LOG_FILE_APPEND": True,
                       "LOG_LEVEL": "INFO"}

    targets = ("kkzui",)
    configs: dict[str, ConfigData]

    def _find_link(self, name: str, text: str):
        """Find links in text and yield links with extensions."""
        pattern = re.compile(f"([^<>\r\n]*)({self.configs[name].get("pattern", {})})")
        for match in pattern.finditer(text):
            if "v2ray" in match.group(1):
                yield match.group(2), ".txt"
            elif "clash" in match.group(1):
                yield match.group(2), ".yaml"
            else:
                self.logger.warning(f"{name} could not parse {match.group()}, skipping")

    def parse_blog(self, response: Response):
        """Parse blog with decryption."""
        name = response.meta["name"]
        old_pwd = self.configs[name].get("password", "")
        pwd = response.meta.get("pwd")
        method = {"textbox": self.configs[name].get("textbox", ""),
                  "button": self.configs[name].get("button", "")}
        for pwd in [old_pwd, pwd]:
            ok, msg = self._decrypt(response.url, method, pwd)
            if not ok:
                self.logger.warning(f"{name} {pwd} got {msg}")
                continue

            for link, ext in self._find_link(name, msg):
                response.meta["ext"] = ext
                yield response.follow(link, callback=self.parse_link, meta=response.meta)

            if old_pwd != pwd:
                CONFIG.set(name, {"password": pwd})
                self.logger.info(f"{name} saved new password {pwd}")
            break

        # First time without pwd
        if not pwd:
            tag = response.xpath("//strong[contains(text(), '不需要代理')]").get()
            pwd_url = tag.css("a::attr(href)").get()
            pwd = tag.re(r"密码(\d+)")[0]
            self.logger.info(f"{name} found pwd_url: {pwd_url}, pwd: {pwd}")

            response.meta["blog_url"] = response.url
            response.meta["pwd"] = pwd
            yield response.follow(pwd_url, callback=self.parse_pwd, meta=response.meta)

    def parse_pwd(self, response: Response):
        name = response.meta["name"]
        url = response.meta["blog_url"]
        method = {"textbox": (By.ID, "passworddecrypt"),
                  "button": (By.TAG_NAME, "button")}
        ok, msg = self._decrypt(response.url, method, response.meta["pwd"])
        if not ok:
            self.logger.error(f"{name} failed to get pwd, {msg}")
            return
        text_parts = [part.strip() for part in response.text.split("><")]
        filtered_parts = [part for part in text_parts if part]
        if match := re.search(r"密码：(\d+)", "".join(filtered_parts)):
            response.meta["pwd"] = match.group(1)
            yield response.follow(url, self.parse_blog, meta=response.meta)
