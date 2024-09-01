# pipelines.py

import os
import yaml

from utils.Config import CONFIG
from NodeScrapy.items import GeoLocItem, NodeItem
from utils.GeoLoc import base64decode, Parser


class Pipeline:
    folder: str

    def __init__(self, settings):
        self.folder = settings.get("PRIMARY_FOLDER")

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def open_spider(self, spider):
        if not os.path.exists(self.folder):
            os.mkdir(self.folder)

    def close_spider(self, spider):
        CONFIG.save()

    def process_item(self, item, spider):
        if not isinstance(item, NodeItem):
            return item

        name = item["name"]
        ext = item["ext"]
        filename = f"{name}{ext}"
        spider.logger.info(f"Pipeline processing {filename}")

        with open(os.path.join(self.folder, filename), "w", encoding="utf-8") as file:
            if ext == ".txt":
                file.write(base64decode(item["body"]))

            elif ext == ".yaml":
                data = yaml.safe_load(item["body"])
                yaml.safe_dump(data, file, default_flow_style=False, allow_unicode=True)

            else:
                file.write(item["body"])

        spider.logger.info(f"Pipeline processed {filename}")

        CONFIG.set(name, {"up_date": item["date"]})

        return item


class GeoLocPipeline:
    orig_folder: str
    res_folder: str
    files = {}
    parser = Parser()

    def __init__(self, settings):
        self.orig_folder = settings.get("PRIMARY_FOLDER")
        self.res_folder = settings.get("SECONDARY_FOLDER")

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings)

    def open_spider(self, spider):
        if not os.path.exists(self.orig_folder):
            spider.logger.critical(f"NODE_FOLDER {self.orig_folder} not exists")
            raise FileNotFoundError(f"NODE_FOLDER {self.orig_folder} not exists")

        if not os.path.exists(self.res_folder):
            os.mkdir(self.res_folder)

        for filename in os.listdir(self.orig_folder):
            self.files[filename] = open(os.path.join(self.res_folder, filename), "w", encoding="utf-8")

    def close_spider(self, spider):
        for file in self.files.values():
            file.close()

    def process_item(self, item, spider):
        if not isinstance(item, GeoLocItem):
            return item

        filename = item["filename"]
        geoloc = item["geoloc"]
        node = item["node"]

        if filename.endswith(".txt"):
            renode = self.parser.set_remarks(node, geoloc)
            self.files[filename].write(f"{renode}\n")

        elif filename.endswith(".yaml"):
            with open(os.path.join(self.res_folder, filename), "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)

            orig_name = node["name"]

            for proxy in data["proxies"]:
                if proxy["name"] == orig_name:
                    proxy["name"] = geoloc

            for group in data["proxy-groups"]:
                group["proxies"] = [geoloc if proxy == orig_name else proxy
                                    for proxy in group["proxies"]]

            yaml.safe_dump(data, self.files[filename], default_flow_style=False, allow_unicode=True)

        return item
