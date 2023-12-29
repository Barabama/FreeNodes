import argparse
import base64
import os
import traceback

from Config import *
from WebScraper import *
from get_pwd import get_pwd

folder_path = "nodes"


def is_base64(s: str) -> bool:
    """判断字符串是否为base64"""
    return (bool(re.match(r'^[A-Za-z0-9+/=]+$', s))) and (len(s) % 4 == 0)


def get_nodes(text: str):
    yield from text.strip().splitlines()


def write_nodes(text: str, file_name: str):
    """更新节点文本"""
    if not os.path.isdir(folder_path): os.mkdir(folder_path)  # 新建文件夹
    text = base64.b64decode(text).decode("utf-8") if is_base64(text) else text

    with open(os.path.join(folder_path, file_name), "w") as f:
        f.write("\n".join(get_nodes(text)))


def merge_nodes():
    with open(os.path.join(folder_path, "merged.txt"), "w") as merged_file:
        for file_name in [file for file in os.listdir(folder_path) if file.endswith(".txt")]:
            with open(os.path.join(folder_path, file_name), "r") as file:
                merged_file.write(file.read() + "\n")


def main():
    """抓取节点内容并保存"""

    scraper = NodeScraper(**config)
    print(f"{scraper.name}: 访问 {scraper.detail_url}")

    # 是否需要更新
    if not (debug or scraper.is_new()):
        print(f"{scraper.name}: 无需更新")
        return

    # 成功搜索 txt 文本链接
    if nodes_url := scraper.get_nodes_url():
        print(f"{scraper.name}: 无需密码直接获取节点")

    # 未搜索到 txt 文本链接, 需要解密
    elif scraper.is_locked():
        print(f"{scraper.name}: 需要解密")

        yt_url = scraper.get_yt_url()

        driver = scraper.webdriver_init()

        # 获取解密密码
        print(f"{scraper.name} 访问 {yt_url}")
        for pwd in get_pwd(yt_url, api_key, secret_key):
            if not pwd.strip():
                continue

            result = scraper.decrypt_for_text(pwd)
            # txt 文本链接
            if nodes_url := scraper.get_nodes_url(result):
                print(f"{scraper.name}: 解密成功获取节点")
                break

        driver.quit()  # 关闭浏览器

    if not nodes_url:
        print(f"{scraper.name}: 更新节点失败")
        return

    # 更新节点文本
    print(f"{scraper.name}: 更新节点 {nodes_url}")
    nodes_text = get_url(nodes_url)
    write_nodes(nodes_text, f"{scraper.name}.txt")

    # 写更新日期
    data = {"up_date": scraper.text_date.date().strftime("%Y-%m-%d")}
    conf.set_data(scraper.name, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", default=False, help="For Debug")
    parser.add_argument("--api_key", default="", help="API key")
    parser.add_argument("--secret_key", default="", help="Secret key")
    args = parser.parse_args()

    debug = args.debug
    api_key = args.api_key
    secret_key = args.secret_key

    conf = Config("config.json")

    for config in conf.configs:
        try:
            main()
            print(f"{config["name"]} 更新记录")
            conf.write_config()
        except Exception as e:
            traceback.print_exc()
            print(f"{config["name"]} ERROR: {e}")

    # merge_nodes()
