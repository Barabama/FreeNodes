import argparse
import io
import itertools
import os
import threading
import traceback
import zipfile
from concurrent.futures import as_completed, ThreadPoolExecutor

from Config import Config, ConfigData
from NodeHandler import NodeHandler
from NodeScraper import NodeScraper
from PwdFinder import PwdFinder, find_pwd
from RequestHandler import make_request

nodes_path = "nodes"
merged_path = os.path.join(nodes_path, "merged.txt")
lock = threading.Lock()


def get_nodes_url_from_blog(name: str, scraper: NodeScraper) -> str:
    scraper.get_detail()
    
    # 成功搜索txt文本链接
    if nodes_url := scraper.get_nodes_url():
        print(f"{name}: 无需密码直接获取节点")
    
    # 未搜索到txt文本链接, 需要解密
    elif scraper.is_locked():
        print(f"{name}: 需要解密")
        scraper.init_webdriver()
        
        # 获取旧密码
        cur_pwd = scraper.decryption.get("password", "")
        gen_cur_pwd = iter([cur_pwd])
        
        # 获取新密码
        if yt_url := scraper.get_yt_url():
            print(f"{name}: 访问youtube {yt_url}")
            new_pwd, _ = scraper.get_description(yt_url, yt_key)
            gen_cur_pwd = iter([cur_pwd, new_pwd])
            pwd_finder = PwdFinder(name, yt_url, api_key, secret_key)
            gen_new_pwd = pwd_finder.gen_pwd()
        else:
            gen_new_pwd = (find_pwd(e.text) for e in
                           scraper.detail_soup.select("p:-soup-contains('码')"))
        
        # 遍历密码解密
        for pwd in itertools.chain(gen_cur_pwd, gen_new_pwd):
            if not pwd.strip(): continue
            ret, result = scraper.decrypt_for_text(pwd)  # 解密
            if not ret: print(f"{name}: {result}"); continue
            # 获取txt文本链接
            elif nodes_url := scraper.get_nodes_url(result):
                print(f"{name}: {pwd} 解密成功")
                
                if cur_pwd != pwd:  # 记录新密码
                    scraper.decryption["password"] = pwd
                    data = {"decryption": scraper.decryption}
                    conf.set_data(name, data)
                break
        
        scraper.driver.quit()  # 关闭浏览器
    
    return nodes_url


def get_nodes_url_from_yt(name: str, scraper: NodeScraper) -> str:
    # 获取旧密码
    cur_pwd = scraper.decryption.get("password", "")
    
    # 获取新密码
    new_pwd, download_link = scraper.get_description(yt_key=yt_key)
    gen_cur_pwd = iter([cur_pwd, new_pwd])
    pwd_finder = PwdFinder(name, scraper.detail_url, api_key, secret_key)
    gen_new_pwd = pwd_finder.gen_pwd()
    
    nodes_url = ""
    
    # 处理加密的zip文件
    if download_link.endswith("zip"):
        print(f"{name}: 下载 {download_link}")
        res = make_request("GET", download_link)
        zip_file = zipfile.ZipFile(io.BytesIO(res.content),
                                   metadata_encoding="gbk")
        file_name = [n for n in zip_file.namelist() if "节点" in n][0]
        for pwd in itertools.chain(gen_cur_pwd, gen_new_pwd):
            if not pwd.strip(): continue
            try: file = zip_file.open(file_name, "r", bytes(pwd, "utf-8"))
            except RuntimeError: continue
            print(f"{name}: {pwd} 解密成功")
            
            text = file.read().decode("utf-8")
            nodes_url = scraper.get_nodes_url(text)  # 获取txt文本链接
            file.close()
            
            if cur_pwd != pwd:  # 记录新密码
                scraper.decryption["password"] = pwd
                data = {"decryption": scraper.decryption}
                conf.set_data(name, data)
            break
        
        zip_file.close()
    
    else:
        for pwd in itertools.chain(gen_cur_pwd, gen_new_pwd):
            if not pwd.strip(): continue
            ret, result = scraper.decrypt_for_text(pwd, download_link)  # 解密
            if not ret: print(f"{name}: {result}"); continue
            # 获取txt文本链接
            elif nodes_url := scraper.get_nodes_url(result):
                print(f"{name}: {pwd} 解密成功")
                
                if cur_pwd != pwd:  # 记录新密码
                    scraper.decryption["password"] = pwd
                    data = {"decryption": scraper.decryption}
                    conf.set_data(name, data)
                break
        
        scraper.driver.quit()  # 关闭浏览器
    
    return nodes_url


def get_nodes(name: str, config: ConfigData) -> list[str]:
    """抓取节点内容并保存"""
    kwargs = config.copy()
    kwargs.pop("tier")
    
    # scraper初始化
    scraper = NodeScraper(**kwargs)
    
    # 是否需要更新
    if scraper.is_latest() and not debug:
        print(f"{name}: 无需更新")
        with open(os.path.join(nodes_path, f"{scraper.name}.txt"), "r") as file:
            nodes = file.readlines()
    else:
        if scraper.detail_url.startswith("https://www.youtube.com"):
            nodes_url = get_nodes_url_from_yt(name, scraper)
        else: nodes_url = get_nodes_url_from_blog(name, scraper)
        
        # 无法获取txt文本链接
        if not nodes_url: raise RuntimeError(f"{name}: 无法获取节点")
        
        # 获取节点文本
        print(f"{name}: 节点地址 {nodes_url}")
        node_handler = NodeHandler(make_request("GET", nodes_url).text)
        nodes = [node + "\n" for node in node_handler.set_remarks()]
        
        # 记录更新日期
        data = {"up_date": scraper.web_date.date().strftime("%Y-%m-%d")}
        conf.set_data(name, data)
    
    return nodes


def subtask(name: str, config: ConfigData) -> tuple[str, int | Exception]:
    """处理异常"""
    try:
        nodes = get_nodes(name, config)
        if not os.path.isdir(nodes_path): os.mkdir(nodes_path)  # 新建文件夹
        with open(os.path.join(nodes_path, f"{name}.txt"), "w") as file:
            file.writelines(nodes)
        
        # 节点合并
        if config.get("tier", 0):
            print(f"{name}: 合并节点")
            with lock: merged_file.writelines(nodes)
        
        print(f"{name}: 更新完成")
        return name, 0
    except Exception as e:
        traceback.print_exc()
        return name, e


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--debug", default=False, help="For Debug")
    parser.add_argument("--api_key", default="", help="API key")
    parser.add_argument("--secret_key", default="", help="Secret key")
    parser.add_argument("--yt_key", default="", help="YouTube api key")
    args = parser.parse_args()
    debug = args.debug
    api_key = args.api_key
    secret_key = args.secret_key
    yt_key = args.yt_key
    
    with open(merged_path, "w") as merged_file:
        merged_file.truncate(0)  # 清空文件内容
    
    conf = Config("config.json")  # 读取配置文件
    
    merged_file = open(merged_path, "a")
    
    results: list[tuple[str, int | Exception]] = []
    if debug:
        results = [subtask(name, config) for name, config in conf.gen_configs()]
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(subtask, name, config)
                       for name, config in conf.gen_configs()]
            results = [future.result() for future in as_completed(futures)]
    
    merged_file.close()
    
    fails = [name for name, result in results if isinstance(result, Exception)]
    print(f"{fails} 线程出现错误, 更新config")
    
    conf.write_config()
