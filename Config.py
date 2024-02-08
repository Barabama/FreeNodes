import json
from typing import Generator, TypedDict


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
    
    def get_config(self, name: str) -> tuple[str, ConfigData]:
        return name, self.configs[name]
    
    def gen_configs(self, names=None) -> Generator[tuple, None, None]:
        if names is None: names = []
        if names: yield from (self.get_config(name) for name in names)
        else: yield from self.configs.items()
    
    def write_config(self):
        with open(self.file_path, "w") as file:
            json.dump(self.configs, file, indent=2)
    
    def set_data(self, name: str, data: dict):
        self.configs[name].update(data)
