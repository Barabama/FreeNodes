import re
import requests
import kuser_agent
from bs4 import BeautifulSoup


def _get_url(url: str):
    """发送GET请求获取网页内容"""
    headers = {"User-Agent": kuser_agent.get()}  # 设置请求头信息
    response = requests.get(url, headers=headers)
    html_content = response.text
    return html_content


def _scrape(url: str, element="", ret_all=True):
    """获取网页元素"""
    soup = BeautifulSoup(_get_url(url), "html.parser")
    if element == "":
        return soup
    else:
        return soup.find_all(element) if ret_all else soup.find(element)


def scrape():
    main_url = "https://www.yudou66.com/search/label/free"

    # 使用BeautifulSoup解析网页内容
    article = _scrape(main_url, "article", True)

    article_url = article[2].find("a").get("href")

    # 使用正则表达式匹配链接字符串
    # pattern = r".+\.txt"
    pattern = r"http://yy\.yudou66\.top/[^/]+/[^/]+\.txt"
    match = re.search(pattern, _get_url(article_url))
    if match:
        with open("FreeNodes.txt", "w") as f:
            f.write(_get_url(match.group()))


if __name__ == '__main__':
    scrape()
