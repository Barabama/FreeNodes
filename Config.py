import json
from typing import TypedDict


class Decryption(TypedDict):
    yt_index: int
    decrypt_by: str
    script: str
    textbox: list
    button: list
    password: str


class ConfigData(TypedDict):
    name: str
    tier: int
    up_date: str
    main_url: str
    attrs: dict
    pattern: str
    nodes_index: int
    decryption: Decryption


class Config:
    file_path: str
    configs: dict[str, ConfigData]

    def __init__(self, file_path: str):
        self.file_path = file_path
        with open(file_path, "r") as file:
            self.configs = json.load(file)

    def get_configs(self):
        yield from self.configs.values()

    def write_config(self):
        with open(self.file_path, "w") as file:
            json.dump(self.configs, file, indent=2)

    def set_data(self, name: str, data: dict):
        self.configs[name].update(data)
