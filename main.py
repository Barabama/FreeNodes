import os
import re
import requests
from concurrent.futures import ThreadPoolExecutor

import kuser_agent
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By

from get_pwd import get_pwd


def _get_url(url: str) -> str:
    """
    获取网页内容
    :param url: 网页链接
    :return: 网页内容
    """
    headers = {"User-Agent": kuser_agent.get()}  # 设置请求头信息
    response = requests.get(url, headers=headers)
    return response.text


def _get_elements(url: str, element="", attrs={}, ret_all=True):
    """获取网页元素"""
    soup = BeautifulSoup(_get_url(url), "html.parser")
    if not element:
        return soup
    else:
        print(f"找到网页元素 {element}:{attrs}")
        return soup.find_all(element, attrs) if ret_all else soup.find(element, attrs)


def _is_locked(url) -> bool:
    """判断网页中是否存在加密元素"""
    return True if _get_elements(url, "input", {"id": "EPassword"}, False) else False


def _match_text(content: str, is_url: bool, pattern: str) -> str:
    """
    正则表达式匹配字符串
    :param content: 要匹配的内容
    :param is_url: 是否是链接
    :param pattern: 正则表达式
    :return: 匹配成功的最后一个
    """
    content = _get_url(content) if is_url else content
    matches = re.findall(pattern, content)
    return matches[-1] if matches else None


def _decrypt_for_text(driver: webdriver.Chrome, pwd: str) -> str:
    """
    网页解密得到隐藏文本内容
    :param driver: webdriver.Chrome
    :param pwd: 候选密码
    :return: 隐藏的文本内容
    """

    # 传递参数给JavaScript函数
    driver.execute_script("multiDecrypt(arguments[0]);", pwd)
    try:
        alert = WebDriverWait(driver, 2).until(EC.alert_is_present())
        alert.accept()  # 确认alert
    except TimeoutException:
        return driver.find_element(By.ID, "result").text


def _write_nodes(nodes_url: str, file_name: str):
    """更新节点"""
    folder_path = "nodes"
    if not os.path.isdir(folder_path): os.mkdir(folder_path)
    with open(os.path.join(folder_path, file_name), "w") as f:
        print(f"更新 {file_name}")
        f.write(_get_url(nodes_url))


def scrape(name: str, list_url: str, attrs: dict, pattern: r""):
    """抓取节点内容并保存
    :param name: 保存的文件名
    :param list_url: 列表主页链接
    :param attrs: 抓取属性
    :param pattern: 匹配表达式
    """
    # 获得详情界面
    detail_url = _get_elements(list_url, "a", attrs, False).get("href")

    # 搜索 txt 文本链接
    if nodes_url := _match_text(detail_url, True, pattern):
        print("获取节点")
    elif (nodes_url is None) and _is_locked(detail_url):
        # 需要解密
        hrefs = [str(a.get("href")) for a in _get_elements(detail_url, "a", {}, True)]
        yt_url = ""
        for href in reversed(hrefs):
            if href.startswith("https://youtu.be/"):
                yt_url = href
                break

        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 启用无头模式
        driver = webdriver.Chrome(options)  # 创建浏览器实例
        driver.get(detail_url)  # 打开网页
        ocr = True if (name == "yudou66") else False
        for pwd in get_pwd(yt_url, ocr):
            if result := _decrypt_for_text(driver, pwd):
                print(f"\n解密密码 {pwd}")
                nodes_url = _match_text(result, False, pattern)
                break
        driver.quit()  # 关闭浏览器

    _write_nodes(nodes_url, f"{name}.txt")


if __name__ == "__main__":
    webs = [
        {"name": "yudou66", "list_url": "https://www.yudou66.com", "attrs": {"class": "entry-image-wrap is-image"},
         "pattern": r"http.*?\.txt", },
        {"name": "blues", "list_url": "https://blues2022.blogspot.com", "attrs": {"class": "entry-image-wrap is-image"},
         "pattern": r"https://agit\.ai/blue/youlingkaishi/.+", },
        # https://halekj.top/
        {"name": "v2rayshare", "list_url": "https://v2rayshare.com", "attrs": {"class": "media-content"},
         "pattern": r"http.*?\.txt", },
        {"name": "nodefree", "list_url": "https://nodefree.org", "attrs": {"class": "item-img-inner"},
         "pattern": r"http.*?\.txt", },
    ]
    try:
        # 创建线程池
        with ThreadPoolExecutor() as executor:
            futures = []
            # 提交函数给线程池
            for web in webs:
                future = executor.submit(scrape, **web)
                futures.append(future)

            # 等待函数完成
            results = [future.result() for future in futures]
    except Exception as e:
        print(e)
