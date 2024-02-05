import argparse
import itertools
import os
import threading
import traceback
from concurrent.futures import as_completed, ThreadPoolExecutor

from Config import Config, ConfigData
from NodeHandler import NodeHandler
from NodeScraper import NodeScraper, gen_elem
from PwdFinder import PwdFinder, find_pwd
from RequestHandler import make_request

nodes_path = "nodes"
merged_path = os.path.join(nodes_path, "merged.txt")
lock = threading.Lock()


def write_nodes(text: str, file_name: str):
    """更新节点文本"""
    if not os.path.isdir(nodes_path): os.mkdir(nodes_path)  # 新建文件夹
    node_handler = NodeHandler(text)
    with open(os.path.join(nodes_path, file_name), "w") as file:
        file.write("\n".join(node_handler.set_remarks()))


def main(name: str, config: ConfigData) -> int:
    """抓取节点内容并保存"""
    kwargs = config.copy()
    kwargs.pop("tier")
    
    # scraper初始化
    scraper = NodeScraper(**kwargs)
    
    # 是否需要更新
    if not scraper.is_new(debug): print(f"{name}: 无需更新"); return 0
    
    # 成功搜索txt文本链接
    if nodes_url := scraper.get_nodes_url():
        print(f"{name}: 无需密码直接获取节点")
    
    # 未搜索到txt文本链接, 需要解密
    elif scraper.is_locked():
        print(f"{name}: 需要解密")
        driver = scraper.init_webdriver()
        
        # 获取旧密码
        cur_pwd = scraper.decryption.get("password", "")
        gen_cur_pwd = iter([cur_pwd])
        
        # 获取新密码
        if yt_url := scraper.get_yt_url():
            print(f"{name}: 访问youtube {yt_url}")
            pwd_finder = PwdFinder(name, yt_url, api_key, secret_key)
            gen_new_pwd = pwd_finder.gen_pwd()
        else:
            gen_new_pwd = (find_pwd(e.text) for e in
                           gen_elem(scraper.detail_text, "p"))
        
        # 遍历密码解密
        for pwd in itertools.chain(gen_cur_pwd, gen_new_pwd):
            if not pwd: continue
            
            # 解密
            ret, result = scraper.decrypt_for_text(pwd)
            if not ret: print(f"{name}: {result}")
            # 获取txt文本链接
            elif nodes_url := scraper.get_nodes_url(result):
                print(f"{name}: {pwd} 解密成功")
                
                # 记录新密码
                if cur_pwd != pwd:
                    scraper.decryption["password"] = pwd
                    data = {"decryption": scraper.decryption}
                    conf.set_data(name, data)
                
                break
        
        driver.quit()  # 关闭浏览器
    
    # 无法获取txt文本链接
    if not nodes_url: raise RuntimeError(f"{name}: 无法获取节点")
    
    # 更新节点文本
    print(f"{name}: 节点地址 {nodes_url}")
    nodes_text = make_request("GET", nodes_url).text
    write_nodes(nodes_text, f"{scraper.name}.txt")
    
    # 记录更新日期
    data = {"up_date": scraper.web_date.date().strftime("%Y-%m-%d")}
    conf.set_data(name, data)
    
    # 节点合并
    if config.get("tier", 0):
        print(f"{name}: 合并节点")
        file = open(os.path.join(nodes_path, f"{config["name"]}.txt"), "r")
        with lock: merged_file.write(file.read() + "\n")
        file.close()
    
    print(f"{name}: 更新完成")
    return 0


def subtask(name: str, config: ConfigData) -> tuple[str, int | Exception]:
    try:
        return name, main(name, config)
    except Exception as e:
        traceback.print_exc()
        return name, e


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
