from concurrent.futures import ThreadPoolExecutor

from Config import *
from WebScraper import *
from get_pwd import get_pwd


def merge_nodes():
    folder_path = "nodes"
    with open(os.path.join(folder_path, "merged.txt"), "w") as merged_file:
        for file_name in [file for file in os.listdir(folder_path) if file.endswith(".txt")]:
            with open(os.path.join(folder_path, file_name), "r") as file:
                merged_file.write(file.read() + "\n")


def scrape(name: str, main_url: str, attrs: dict, pattern: str, up_date: str) -> list:
    """抓取节点内容并保存
    :param name: 保存的文件名
    :param main_url: 主页链接
    :param attrs: 抓取属性
    :param pattern: 匹配表达式
    :param up_date: 更新日期
    """
    default_res = [name, {"up_date": up_date}]

    # 主页内容
    main_text = get_url(main_url)

    # 详情页链接
    detail_url = next(get_elements(main_text, "a", attrs)).get("href")
    print(f"{name}: 访问 {detail_url}")

    # 详情页内容
    detail_text = get_url(detail_url)

    # 不需要更新
    if not is_new(detail_text, up_date):
        print(f"{name}: 无需更新")
        return default_res

    nodes_url = ""
    # 成功搜索倒一 txt 文本链接
    if texts := [text for text in match_text(detail_text, pattern)]:
        print(f"{name}: 无需密码直接获取节点")
        nodes_url = next(reversed(texts))

    # 未搜索到 txt 文本链接, 需要解密
    elif is_locked(detail_text):
        print(f"{name}: 需要解密")

        # 获取详情页所有链接
        hrefs = [str(tag.get("href")) for tag in get_elements(detail_text, "a", {})]
        # 获取 youtube 链接
        yt_urls = [href for href in hrefs if href.startswith("https://youtu.be/")]
        # 取首尾 youtube 链接
        yt_url = yt_urls[0] if name == "halekj" else yt_urls[-1]

        # 虚拟浏览器初始化
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 启用无头模式
        driver = webdriver.Chrome(options)  # 创建浏览器实例
        driver.get(detail_url)  # 打开详情页

        # 获取解密密码
        print(f"{name} 访问 {yt_url}")
        for pwd in get_pwd(yt_url):
            if pwd and (result := decrypt_for_text(driver, pwd)):
                print(f"{name}: 解密成功获取节点")
                # 倒一 txt 文本链接
                nodes_url = next(reversed([text for text in match_text(result, pattern)]))
                break

        driver.quit()  # 关闭浏览器

    if not nodes_url:
        print(f"{name}: 更新节点失败")
        return default_res

    # 更新节点文本
    nodes_text = get_url(nodes_url)
    print(f"{name}: 更新节点")
    write_nodes(nodes_text, f"{name}.txt")

    return [name, {"up_date": datetime.today().date().strftime("%Y-%m-%d")}]


if __name__ == "__main__":
    conf = Config("config.json")
    # 创建线程池
    with ThreadPoolExecutor() as executor:
        futures = []
        # 提交函数给线程池
        for config in conf.configs:
            future = executor.submit(scrape, **config)
            futures.append(future)
        results = [future.result() for future in futures]

    # 写更新日期
    for name, data in results:
        conf.set_data(name, data)

    # # test
    # conf = Config("test.json")
    # if res := scrape(**conf.configs[0]):
    #     name, data = res
    #     conf.set_data(name, data)

    print("更新记录")
    conf.write_config()

    merge_nodes()
