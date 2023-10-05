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


def scrape_66(url: str):
    a = _scrape(url, "a", {"class": "entry-image-wrap is-image"}, True)

    # 前3个需要密码, 多取几个
    a_urls = [a[i].get("href") for i in range(5)]

    # 使用正则表达式匹配链接字符串
    pattern = r"http.*?\.txt"
    # pattern = r"http://yy\.yudou66\.top/[^/]+/[^/]+\.txt
    match = None
    for a_url in a_urls:
        html_text = _get_url(a_url)
        match = re.search(pattern, html_text)
        if match:
            break
    nodes = _get_url(match.group())
    _write_nodes(nodes, "yudou66.txt")


def scrape_share(url: str):
    link = _scrape(url, "a", {"class": "media-content"}, False)

    # 使用正则表达式匹配链接字符串
    pattern = r"http.*?\.txt"

    html_text = _get_url(link.get("href"))
    match = re.search(pattern, html_text)
    if match:
        nodes = _get_url(match.group())
        _write_nodes(nodes, "v2rayshare.txt")


if __name__ == "__main__":

    # 创建线程池
    with ThreadPoolExecutor() as executor:
        futures = []
        # 提交函数给线程池
        future1 = executor.submit(scrape_66, "https://www.yudou66.com/search/label/free")
        futures.append(future1)

        future2 = executor.submit(scrape_share, "https://v2rayshare.com")
        futures.append(future2)

        # 等待函数完成
        results = [future.result() for future in futures]

