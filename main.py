import re
import requests
import kuser_agent
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor


def _get_url(url: str):
    """发送GET请求获取网页内容"""
    headers = {"User-Agent": kuser_agent.get()}  # 设置请求头信息
    response = requests.get(url, headers=headers)
    html_content = response.text
    return html_content


def _scrape(url: str, element="", attrs: dict = {}, ret_all=True):
    """获取网页元素"""
    soup = BeautifulSoup(_get_url(url), "html.parser")
    if element == "":
        return soup
    else:
        return soup.find_all(element, attrs) if ret_all else soup.find(element, attrs)


def _write_nodes(content: str, file_name: str):
    with open(file_name, "w") as f:
        f.write(content)


def scrape(name: str, url: str, attrs: dict):
    """抓取节点内容并保存
    :param name: 保存的文件名
    :param url: 网页链接
    :param attrs: 抓取属性
    """
    a = _scrape(url, "a", attrs, True)

    # 前3个需要密码, 多取几个
    a_urls = [a[i].get("href") for i in range(5)]

    # 使用正则表达式匹配链接字符串
    pattern = r"http.*?\.txt"

    match = None
    for a_url in a_urls:
        html_text = _get_url(a_url)
        match = re.search(pattern, html_text)
        if match:
            break
    nodes = _get_url(match.group())
    _write_nodes(nodes, f"{name}.txt")


if __name__ == "__main__":
    webs = [
        {"name": "yudou66", "url": "https://www.yudou66.com", "attrs": {"class": "entry-image-wrap is-image"}},
        {"name": "v2rayshare", "url": "https://v2rayshare.com", "attrs": {"class": "media-content"}},
        {"name": "nodefree", "url": "https://nodefree.org/", "attrs": {"class": "item-img-inner"}},
    ]

    # 创建线程池
    with ThreadPoolExecutor() as executor:
        futures = []
        # 提交函数给线程池
        for web in webs:
            future = executor.submit(scrape, **web)
            futures.append(future)

        # 等待函数完成
        results = [future.result() for future in futures]
