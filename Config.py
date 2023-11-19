import json
from typing import TypedDict


class ConfigData(TypedDict):
    name: str
    list_url: str
    attrs: dict
    pattern: str
    date: str


class Config:
    file_path: str
    configs: list[ConfigData]

    def __init__(self, file_path: str):
        self.file_path = file_path
        with open(file_path, "r") as file:
            self.configs = json.load(file)

    def get_configs(self):
        return self.configs

    def write_config(self):
        with open(self.file_path, "w") as file:
            json.dump(self.configs, file, indent=4)

    def set_data(self, name: str, data: dict):
        for config in self.configs:
            if config["name"] == name:
                config.update(data)
                break

