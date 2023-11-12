import os
import re
from datetime import datetime
from typing import Generator

import requests
from concurrent.futures import ThreadPoolExecutor

import kuser_agent
from bs4 import BeautifulSoup
from bs4.element import Tag
from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from get_pwd import get_pwd
from Config import *


def get_url(url: str) -> str:
    """获取网页内容"""
    headers = {"User-Agent": kuser_agent.get()}  # 设置请求头信息
    response = requests.get(url, headers=headers)
    return response.text


def get_elements(url: str, element="", attrs={}) -> Generator[Tag, None, None]:
    """获取网页元素"""
    soup = BeautifulSoup(get_url(url), "html.parser")
    print(f"寻找网页元素 {element}:{attrs}")
    yield from soup.find_all(element, attrs)


def is_new(url: str, up_date: str) -> bool:
    """判断网页的是否更新"""
    h1 = next(get_elements(url, "h1")).text
    date_text = next(match_text(h1, False, r"\d{2}月\d{2}日"))
    text_date = datetime.strptime(date_text, "%m月%d日")
    text_date = text_date.replace(year=datetime.today().year)

    up_date = datetime.strptime(up_date, "%Y-%m-%d")
    return True if text_date.date() > up_date.date() else False


def is_locked(url) -> bool:
    """判断网页中是否存在加密元素"""
    return True if next(get_elements(url, "input", {"id": "EPassword"})) else False


def match_text(content: str, is_url: bool, pattern: str) -> Generator[str, None, None]:
    """正则表达式匹配字符串"""
    content = get_url(content) if is_url else content
    yield from re.findall(pattern, content)


def decrypt_for_text(driver: webdriver.Chrome, pwd: str) -> str:
    """网页解密得到隐藏文本内容"""
    # 传递参数给JavaScript函数
    driver.execute_script("multiDecrypt(arguments[0]);", pwd)
    try:
        alert = WebDriverWait(driver, 2).until(EC.alert_is_present())
        alert.accept()  # 处理 alert 弹窗
    except TimeoutException:
        return driver.find_element(By.ID, "result").text


def write_nodes(nodes_url: str, file_name: str):
    """更新节点文本"""
    folder_path = "nodes"
    if not os.path.isdir(folder_path): os.mkdir(folder_path)  # 新建文件夹
    with open(os.path.join(folder_path, file_name), "w") as f:
        print(f"更新 {file_name}")
        f.write(get_url(nodes_url))


def scrape(name: str, list_url: str, attrs: dict, pattern: str, by_ocr: bool, up_date: str) -> list:
    """抓取节点内容并保存
    :param name: 保存的文件名
    :param list_url: 列表主页链接
    :param attrs: 抓取属性
    :param pattern: 匹配表达式
    :param by_ocr: 是否通过 ocr
    :param up_date: 更新日期
    """

    # detail_url 为详情页链接
    detail_url = next(get_elements(list_url, "a", attrs)).get("href")

    # 不需要更新
    if not is_new(detail_url, up_date):
        print(f"无需更新 {name}")
        return []

    nodes_url = ""
    # 成功搜索倒一 txt 文本链接
    if texts := [text for text in match_text(detail_url, True, pattern)]:
        nodes_url = next(reversed([texts]))
        print("获取节点")

    # 未搜索到 txt 文本链接, 需要解密
    elif is_locked(detail_url):

        # hrefs 获取详情页所有链接
        hrefs = [str(tag.get("href")) for tag in get_elements(detail_url, "a", {})]
        # yt_url 为最后一个 youtube 链接
        yt_url = next((href for href in reversed(hrefs) if href.startswith("https://youtu.be/")))

        # 虚拟浏览器初始化
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 启用无头模式
        driver = webdriver.Chrome(options)  # 创建浏览器实例
        driver.get(detail_url)  # 打开详情页

        # 获取解密密码
        for pwd in get_pwd(yt_url, by_ocr):
            if result := decrypt_for_text(driver, pwd):
                print(f"\n解密密码 {pwd}")
                # nodes_url 为倒一 txt 文本链接
                nodes_url = next(reversed([text for text in match_text(result, False, pattern)]))
                break

        driver.quit()  # 关闭浏览器

    # 更新节点文本
    write_nodes(nodes_url, f"{name}.txt")

    return [name, {"up_date": datetime.today().date().strftime("%Y-%m-%d")}]


if __name__ == "__main__":
    # "https://halekj.top"
    conf = Config("config.json")
    try:
        # 创建线程池
        with ThreadPoolExecutor() as executor:
            futures = []
            # 提交函数给线程池
            for config in conf.configs:
                future = executor.submit(scrape, **config)
                futures.append(future)
                # 写更新日期
                if res := future.result():
                    name, data = res
                    conf.set_data(name, data)
    except Exception as e:
        print(e)
