# Config.py

import json
import re
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
    readme_path = "README.md"
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
        self._update_readme()

    def _update_readme(self):
        with open(self.readme_path, "r", encoding="utf-8") as file:
            lines = file.readlines()

        table_start = None
        for i, line in enumerate(lines):
            if "订阅列表" in line.strip():
                table_start = i + 3

        if table_start is None:
            return

        for i in range(table_start, len(lines)):
            if lines[i].strip() == "":
                break
            parts = lines[i].split("|")
            match = re.search(r"\[(.+)\]", parts[1].strip())
            if match:
                subscriber = match.group(1)
                if subscriber in self.configs:
                    update_date = self.configs[subscriber].get("up_date", "")
                    parts[-2] = f" {update_date} "
                    lines[i] = "|".join(parts)

        with open(self.readme_path, "w", encoding="utf-8") as file:
            file.writelines(lines)


CONFIG = Config()
