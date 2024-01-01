import json
from typing import TypedDict


class Decryption(TypedDict):
    yt_index: int
    decrypt_by: str
    script: str
    box_id: str
    button_name: str
    password: str


class ConfigData(TypedDict):
    name: str
    list_url: str
    attrs: dict
    up_date: str
    pattern: str
    nodes_index: int
    decryption: Decryption


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
            json.dump(self.configs, file, indent=2)

    def set_data(self, name: str, data: dict):
        for config in self.configs:
            if config["name"] == name:
                config.update(data)
                break
