import os
import re
import requests
import kuser_agent
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
from selenium import webdriver
from selenium.webdriver.common.by import By

from get_pwd import get_pwd


def _get_url(url: str):
    """发送GET请求获取网页内容"""
    headers = {"User-Agent": kuser_agent.get()}  # 设置请求头信息
    response = requests.get(url, headers=headers)
    html_content = response.text
    return html_content


def _get_elements(url: str, element="", attrs: dict = {}, ret_all=True):
    """获取网页元素"""
    soup = BeautifulSoup(_get_url(url), "html.parser")
    if element == "":
        return soup
    else:
        print(f"获取网页元素 {element}:{attrs}")
        return soup.find_all(element, attrs) if ret_all else soup.find(element, attrs)


def _need_pwd(url) -> bool:
    if _get_elements(url, "input", {"id": "EPassword"}, False):
        return True
    else:
        return False


def _match_text(content: str, pattern: r"", is_url: bool):
    # 使用正则表达式匹配链接字符串

    content = _get_url(content) if is_url else content
    matches = re.findall(pattern, content)
    return matches[-1] if matches else None


def _decrypt_for_text(url: str, passwords: list[tuple]):
    options = webdriver.ChromeOptions()
    options.add_argument("--headless")  # 启用无头模式

    driver = webdriver.Chrome(options)  # 创建浏览器实例

    driver.get(url)  # 打开网页

    result = ""
    for pwd, _ in passwords:
        # 传递参数给JavaScript函数
        driver.execute_script("multiDecrypt(arguments[0]);", pwd)
        result = driver.find_element(By.ID, "result").text
        if result:
            print(f"解密密码 {pwd}")
            break

    driver.quit()  # 关闭浏览器
    return result


def _write_nodes(nodes_url: str, file_name: str):
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
    nodes_url = _match_text(detail_url, pattern, True)
    if nodes_url:
        print("获取节点")
    elif (nodes_url is None) and _need_pwd(detail_url):
        hrefs = [str(a.get("href")) for a in _get_elements(detail_url, "a", {}, True)]
        yt_url = ""
        for href in reversed(hrefs):
            if href.startswith("https://youtu.be/"):
                yt_url = href
                break

        ocr = True if name == "yudou66" else False
        pwds = get_pwd(yt_url, ocr)
        result = _decrypt_for_text(detail_url, pwds)
        nodes_url = _match_text(result, pattern, False)

    _write_nodes(nodes_url, f"{name}.txt")


if __name__ == "__main__":
    webs = [
        {"name": "yudou66", "list_url": "https://www.yudou66.com", "attrs": {"class": "entry-image-wrap is-image"},
         "pattern": r"http.*?\.txt", },
        # {"name": "blues", "list_url": "https://blues2022.blogspot.com", "attrs": {"class": "entry-image-wrap is-image"},
        #  "pattern": r"https://agit\.ai/blue/youlingkaishi/.+", },
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
