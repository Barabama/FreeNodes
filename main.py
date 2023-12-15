import sys
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin

from Config import *
from WebScraper import *
from get_pwd import get_pwd


def scrape(name: str, main_url: str, attrs: dict, up_date: str,
           pattern: str, nodes_index=0, decryption: Decryption = {}):
    """抓取节点内容并保存
    :param name: 保存的文件名
    :param main_url: 主页链接
    :param attrs: 抓取属性
    :param up_date: 更新日期
    :param pattern: 匹配表达式
    :param nodes_index: 节点链接索引
    :param decryption：解密参数
    """

    # 主页内容
    main_text = get_url(main_url)

    # 详情页链接
    detail_url = next(get_elements(main_text, "a", attrs)).get("href")
    detail_url = urljoin(main_url, detail_url)

    # 详情页内容
    print(f"{name}: 访问 {detail_url}")
    detail_text = get_url(detail_url)

    # 不需要更新
    if not is_new(detail_text, up_date):
        print(f"{name}: 无需更新")
        return

    nodes_url = ""
    # 成功搜索 txt 文本链接
    if texts := re.findall(detail_text, pattern):
        print(f"{name}: 无需密码直接获取节点")
        nodes_url = texts[nodes_index]

    # 未搜索到 txt 文本链接, 需要解密
    elif is_locked(detail_text):
        print(f"{name}: 需要解密")

        # 获取详情页所有链接
        hrefs = [str(tag.get("href")) for tag in get_elements(detail_text, "a", {})]
        # 获取 youtube 链接
        yt_urls = [href for href in hrefs if href.startswith("https://youtu.be/")]
        # 取首尾 youtube 链接
        yt_url = yt_urls[decryption["yt_index"]]

        # 虚拟浏览器初始化
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 启用无头模式
        driver = webdriver.Chrome(options)  # 创建浏览器实例
        driver.get(detail_url)  # 打开详情页

        # 获取解密密码
        print(f"{name} 访问 {yt_url}")
        for pwd in get_pwd(yt_url, *args):
            if pwd.strip():
                continue

            result = decrypt_for_text(driver, pwd, decryption)
            # txt 文本链接
            if texts := re.findall(result, pattern):
                print(f"{name}: 解密成功获取节点")
                nodes_url = texts[nodes_index]
                break

        driver.quit()  # 关闭浏览器

    if not nodes_url:
        print(f"{name}: 更新节点失败")
        return

    # 更新节点文本
    print(f"{name}: 更新节点 {nodes_url}")
    nodes_text = get_url(nodes_url)
    write_nodes(nodes_text, f"{name}.txt")

    # 写更新日期
    data = {"up_date": datetime.today().date().strftime("%Y-%m-%d")}
    conf.set_data(name, data)


if __name__ == "__main__":
    script, *args = sys.argv
    conf = Config("config.json")

    # 创建线程池
    with ThreadPoolExecutor() as executor:
        futures = []
        # 提交函数给线程池
        for config in conf.configs:
            future = executor.submit(scrape, **config)
            futures.append(future)
        results = [future.result() for future in futures]

    print("更新记录")
    conf.write_config()

    # # test
    # for c in conf.configs:
    #     scrape(**c)
    #     print("更新记录")
    #     conf.write_config()

    merge_nodes()
