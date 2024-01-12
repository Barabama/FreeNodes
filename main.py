#!/usr/bin/env python
# coding=utf-8
import argparse
import itertools
import os
import traceback
from concurrent.futures import as_completed, ThreadPoolExecutor

from Config import *
from NodeHandler import *
from NodeScraper import *
from get_pwd import find_pwd, get_pwd

nodes_path = "nodes"
merge_lock = threading.Lock()


def is_base64(string: str) -> bool:
    """判断字符串是否为 base64"""
    return bool(re.match(r"^[A-Za-z0-9+/=]+$", string))


def write_nodes(text: str, file_name: str):
    """更新节点文本"""
    if not os.path.isdir(nodes_path): os.mkdir(nodes_path)  # 新建文件夹
    text = base64.b64decode(text).decode("utf-8") if is_base64(text) else text
    nodes = [node for node in text.strip().splitlines()]  # 节点列表

    geos = get_geos([get_address(node) for node in nodes])  # geo列表

    def iterator():
        for i, geo in enumerate(geos):
            if geo.get("status", "fail") == "fail":
                geo = get_geo(geo["query"])  # 域名再识别

            remarks = f"{geo["country"]}_{geo["city"]}" \
                if geo["status"] == "success" else "Unknown"
            nodes[i] = write_remarks(nodes[i], remarks)
            yield nodes[i]

    with open(os.path.join(nodes_path, file_name), "w") as file:
        file.write("\n".join(iterator()))


def main(config: ConfigData) -> int:
    """抓取节点内容并保存"""
    kwargs = config.copy()
    kwargs.pop("tier")
    scraper = NodeScraper(**kwargs)

    if not scraper.detail_text:
        raise f"{scraper.name}: 无法访问 {scraper.detail_url}"
    print(f"{scraper.name}: 访问 {scraper.detail_url}")

    # 是否需要更新
    if not (scraper.is_new() or debug):
        print(f"{scraper.name}: 无需更新")
        return 0

    # 成功搜索 txt 文本链接
    if nodes_url := scraper.get_nodes_url():
        print(f"{scraper.name}: 无需密码直接获取节点")

    # 未搜索到 txt 文本链接, 需要解密
    elif scraper.is_locked():
        print(f"{scraper.name}: 需要解密")

        driver = scraper.init_webdriver()

        # 获取解密密码
        cur_pwd = scraper.decryption.get("password", "")
        iter_cur_pwd = iter([cur_pwd])

        if yt_url := scraper.get_yt_url():
            print(f"{scraper.name}: 访问 {yt_url}")
            gen_new_pwd = get_pwd(yt_url, api_key, secret_key)
        else:
            elems = [e for e in gen_elem(scraper.detail_text, "p")]
            gen_new_pwd = iter([find_pwd(e.text) for e in elems])

        for pwd in itertools.chain(iter_cur_pwd, gen_new_pwd):
            if not pwd.strip():
                continue

            result = scraper.decrypt_for_text(pwd)
            # 获取 txt 文本链接
            if nodes_url := scraper.get_nodes_url(result):
                print(f"{scraper.name}: 解密成功获取节点")
                # 记录解密密码
                if cur_pwd != pwd:
                    scraper.decryption["password"] = pwd
                    data = {"decryption": scraper.decryption}
                    conf.set_data(scraper.name, data)
                break

        driver.quit()  # 关闭浏览器

    if not nodes_url:
        raise f"{scraper.name}: 无法获取节点"

    # 更新节点文本
    print(f"{scraper.name}: 更新节点 {nodes_url}")
    nodes_text = get_url(nodes_url)
    write_nodes(nodes_text, f"{scraper.name}.txt")

    # 记录更新日期
    data = {"up_date": scraper.text_date.date().strftime("%Y-%m-%d")}
    conf.set_data(scraper.name, data)

    # 节点合并
    if config.get("tier", 0):
        with merge_lock:
            with open(os.path.join(nodes_path, f"{config["name"]}.txt"), "r") as file:
                merged_file.write(file.read() + "\n")

    print(f"{scraper.name}: 更新完成")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", default=False, help="For Debug")
    parser.add_argument("--api_key", default="", help="API key")
    parser.add_argument("--secret_key", default="", help="Secret key")
    args = parser.parse_args()

    debug = args.debug
    api_key = args.api_key
    secret_key = args.secret_key

    merged_path = os.path.join(nodes_path, "merged.txt")
    with open(merged_path, "w") as merged_file:
        merged_file.truncate(0)  # 清空文件内容
    merged_file = open(merged_path, "a")

    # 读取配置文件
    conf = Config("config.json")

    # 创建线程池
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(main, config) for config in conf.configs]
        results = []
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception:
                traceback.print_exc()
                results.append(1)

    merged_file.close()

    print(f"代码 {sum(results)}, 更新记录")
    conf.write_config()
