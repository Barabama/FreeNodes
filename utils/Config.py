# Config.py

import json
from threading import Lock
from typing import TypedDict


class ConfigData(TypedDict, total=False):
    start_url: str
    up_date: str
    selector: str
    pattern: str
    password: str
    yt_idx: int
    script: str
    textbox: list[str]
    button: list[str]


class Config:
    config_file = "config.json"
    configs: dict[str, ConfigData]
    lock: Lock

    def __init__(self):
        self.lock = Lock()
        with self.lock, open(self.config_file, "r", encoding="utf-8") as file:
            self.configs = {name: ConfigData(**data) for name, data in json.load(file).items()}

    def get(self, name: str) -> ConfigData:
        with self.lock:
            return self.configs.get(name, {})

    def set(self, name: str, data: dict):
        with self.lock:
            self.configs[name].update(data)

    def save(self):
        with self.lock, open(self.config_file, "w", encoding="utf-8") as file:
            json.dump(self.configs, file, ensure_ascii=False, indent=2)


CONFIG = Config()
