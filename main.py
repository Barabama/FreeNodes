#!/usr/bin/env python
# coding=utf-8
import argparse
import os
import threading
import traceback
from concurrent.futures import as_completed, ThreadPoolExecutor

from Config import Config, ConfigData
from MsgHandler import CustomError, MsgHandler
from NodeHandler import NodeHandler
from NodeScraper import NodeScraper, gen_elem
from PwdFinder import PwdFinder, find_pwd
from RequestHandler import make_request

nodes_path = "nodes"
merged_path = os.path.join(nodes_path, "merged.txt")
merge_lock = threading.Lock()


def write_nodes(text: str, file_name: str):
    """更新节点文本"""
    if not os.path.isdir(nodes_path): os.mkdir(nodes_path)  # 新建文件夹
    node_handler = NodeHandler(text)
    with open(os.path.join(nodes_path, file_name), "w") as file:
        file.writelines(node_handler.set_remarks())


def main(config: ConfigData) -> int:
    """抓取节点内容并保存"""
    kwargs = config.copy()
    kwargs.pop("tier")

    msg_handler = MsgHandler(kwargs["name"])

    # scraper初始化
    scraper = NodeScraper(**kwargs)
    if not scraper.detail_text:
        msg_handler.show_error(CustomError(f"无法访问 {scraper.detail_url}"))
        return 0
    else:
        msg_handler.show_msg(f"访问 {scraper.detail_url}")

    # 是否需要更新
    if not scraper.is_new(debug):
        msg_handler.show_msg("无需更新")
        return 0

    # 成功搜索txt文本链接
    if nodes_url := scraper.get_nodes_url():
        msg_handler.show_msg("无需密码直接获取节点")

    # 未搜索到txt文本链接, 需要解密
    elif scraper.is_locked():
        msg_handler.show_msg("需要解密")
        driver = scraper.init_webdriver()

        # 获取旧密码
        cur_pwd = scraper.decryption.get("password", "")

        # 旧密码解密
        ret, result = scraper.decrypt_for_text(cur_pwd)
        if ret:
            msg_handler.show_msg(f"{cur_pwd} 解密成功")
            # 获取txt文本链接
            nodes_url = scraper.get_nodes_url(result)
        else:
            # 获取新密码
            if yt_url := scraper.get_yt_url():
                msg_handler.show_msg(f"访问youtube {yt_url}")
                pwd_finder = PwdFinder(msg_handler, yt_url, api_key, secret_key)
                gen_new_pwd = pwd_finder.gen_pwd()
            else:
                gen_new_pwd = (find_pwd(e.text) for e in gen_elem(scraper.detail_text, "p"))

            # 遍历密码解密
            for pwd in gen_new_pwd:
                if not pwd: continue

                # 解密
                ret, result = scraper.decrypt_for_text(pwd)
                if not ret:
                    msg_handler.show_msg(result)
                # 获取txt文本链接
                elif nodes_url := scraper.get_nodes_url(result):
                    msg_handler.show_msg(f"{pwd} 解密成功")

                    # 记录新密码
                    if cur_pwd != pwd:
                        scraper.decryption["password"] = pwd
                        data = {"decryption": scraper.decryption}
                        conf.set_data(scraper.name, data)
                    break

        driver.quit()  # 关闭浏览器

    # 无法获取txt文本链接
    if not nodes_url:
        msg_handler.show_error(CustomError("无法获取节点"))
        return 0

    # 更新节点文本
    print(f"{scraper.name}: 更新节点 {nodes_url}")
    nodes_text = make_request("GET", nodes_url).text
    write_nodes(nodes_text, f"{scraper.name}.txt")

    # 记录更新日期
    data = {"up_date": scraper.web_date.date().strftime("%Y-%m-%d")}
    conf.set_data(scraper.name, data)

    # 节点合并
    if config.get("tier", 0):
        with merge_lock:
            with open(os.path.join(nodes_path, f"{config["name"]}.txt"), "r") as file:
                merged_file.writelines(file.readlines())

    msg_handler.show_msg("更新完成")
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

    with open(merged_path, "w") as merged_file:
        merged_file.truncate(0)  # 清空文件内容
    merged_file = open(merged_path, "a")

    conf = Config("config.json")  # 读取配置文件

    results = []
    if debug:
        results = [main(config) for config in conf.get_configs()]
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(main, config) for config in conf.get_configs()]
            try:
                results = [future.result() for future in as_completed(futures)]
            except Exception:
                traceback.print_exc()
                results.append(1)

    merged_file.close()
    print(f"{sum(results)} 个线程出现错误, 更新记录")
    conf.write_config()
