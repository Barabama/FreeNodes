import base64
import os
import re
import warnings
from datetime import datetime
from typing import Generator

import kuser_agent
import requests
from bs4 import Tag, BeautifulSoup
from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from Config import Decryption


class WebScraper:
    main_text: str
    detail_text: str

    def __init__(self):
        pass


folder_path = "nodes"


def get_url(url: str) -> str:
    """获取网页内容"""
    headers = {"User-Agent": kuser_agent.get()}  # 设置请求头信息
    response = requests.get(url, headers=headers)
    return response.text if response.status_code < 400 else ""


def get_elements(text: str, element="", attrs={}) -> Generator[Tag, None, None]:
    """获取网页元素"""
    soup = BeautifulSoup(text, "html.parser")
    yield from soup.find_all(element, attrs)


def match_text(text: str, pattern: str):
    """正则表达式匹配字符串"""
    yield from re.findall(pattern, text)


def is_locked(text: str) -> bool:
    """判断网页中是否存在解密元素"""
    elem = [e for e in get_elements(text, "input", {"id": "EPassword"})]
    elem += [e for e in get_elements(text, "input", {"id": "pwbox-426"})]
    return True if elem else False


def is_new(text: str, up_date: str) -> bool:
    """判断网页的是否更新"""
    h1 = "".join(e.text for e in get_elements(text, "h1"))
    if "正在制作" in h1: return False
    date_text = next(match_text(h1, r"\d+月\d+"))
    text_date = datetime.strptime(date_text, "%m月%d")
    text_date = text_date.replace(year=datetime.today().year)

    up_date = datetime.strptime(up_date, "%Y-%m-%d")
    return True if text_date.date() > up_date.date() else False


def decrypt_for_text(driver: webdriver.Chrome, pwd: str, decryption: Decryption) -> str:
    """网页解密得到隐藏文本内容"""
    decrypt_by = decryption["decrypt_by"]

    if decrypt_by not in ("js", "click"):
        warnings.warn(f"解密方法 {decrypt_by} 不支持, 默认 click")

    # 传递参数给JavaScript函数
    elif decrypt_by == "js":
        driver.execute_script(decryption["script"], pwd)

    # 模拟输入提交
    else:
        text_box = driver.find_element(By.ID, decryption["box_id"])  # 使用元素的id属性来定位文本框
        text_box.send_keys(pwd)  # 替换为你要输入的密码
        button = driver.find_element(By.NAME, decryption["button_name"])  # 使用元素的name属性来定位按钮
        button.submit()

    try:
        alert = WebDriverWait(driver, 2).until(EC.alert_is_present())
        print(f"页面提示 {alert.text}")  # 获取弹窗的文本内容
        alert.accept()  # 处理 alert 弹窗
    except TimeoutException:
        return driver.find_element(By.TAG_NAME, "body").text


def write_nodes(text: str, file_name: str):
    """更新节点文本"""
    if not os.path.isdir(folder_path): os.mkdir(folder_path)  # 新建文件夹
    nodes = re.split(r'\n+', base64.b64decode(text).decode("utf-8"))
    with open(os.path.join(folder_path, file_name), "w") as f:
        f.write("\n".join(nodes))


def merge_nodes():
    with open(os.path.join(folder_path, "merged.txt"), "w") as merged_file:
        for file_name in [file for file in os.listdir(folder_path) if file.endswith(".txt")]:
            with open(os.path.join(folder_path, file_name), "r") as file:
                merged_file.write(file.read() + "\n")


if __name__ == "__main__":
    merge_nodes()
