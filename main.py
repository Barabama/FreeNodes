import re
import requests
from bs4 import BeautifulSoup


def get_url(url: str):
    """发送GET请求获取网页内容"""
    response = requests.get(url)
    html_content = response.text
    return html_content


def main():
    url = "https://www.yudou66.com/search/label/free"

    # 使用BeautifulSoup解析网页内容
    soup = BeautifulSoup(get_url(url), "html.parser")
    article = soup.find("article")
    latest_link = article.find("a").get("href")

    # 使用正则表达式查找匹配的字符串
    # pattern = r".+\.txt"
    pattern = r"http://yy\.yudou66\.top/[^/]+/[^/]+\.txt"
    match = re.search(pattern, get_url(latest_link))

    # 打印匹配的字符串
    if match:
        with open("yudou66.txt", "w") as f:
            f.write(match.group())


if __name__ == '__main__':
    main()
