from concurrent.futures import ThreadPoolExecutor

from Config import *
from WebScraper import *
from get_pwd import get_pwd


def scrape(name: str, main_url: str, attrs: dict, pattern: str, by_ocr: bool, up_date: str) -> list:
    """抓取节点内容并保存
    :param name: 保存的文件名
    :param main_url: 主页链接
    :param attrs: 抓取属性
    :param pattern: 匹配表达式
    :param by_ocr: 是否通过 ocr
    :param up_date: 更新日期
    """
    # 主页内容
    main_text = get_url(main_url)

    # 详情页链接
    detail_url = next(get_elements(main_text, "a", attrs)).get("href")

    # 详情页内容
    detail_text = get_url(detail_url)

    # 不需要更新
    if not is_new(detail_text, up_date):
        print(f"无需更新 {name}")
        return []

    nodes_url = ""
    # 成功搜索倒一 txt 文本链接
    if texts := [text for text in match_text(detail_text, pattern)]:
        nodes_url = next(reversed(texts))
        print("获取节点")

    # 未搜索到 txt 文本链接, 需要解密
    elif is_locked(detail_text):

        # 获取详情页所有链接
        hrefs = [str(tag.get("href")) for tag in get_elements(detail_text, "a", {})]
        # 最后一个 youtube 链接
        yt_url = next((href for href in reversed(hrefs) if href.startswith("https://youtu.be/")))

        # 虚拟浏览器初始化
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 启用无头模式
        driver = webdriver.Chrome(options)  # 创建浏览器实例
        driver.get(detail_url)  # 打开详情页

        # 获取解密密码
        for pwd in get_pwd(yt_url, by_ocr):
            if result := decrypt_for_text(driver, pwd):
                print(f"\n解密密码 {pwd}")
                # 倒一 txt 文本链接
                nodes_url = next(reversed([text for text in match_text(result, pattern)]))
                break

        driver.quit()  # 关闭浏览器

    # 更新节点文本
    nodes_text = get_url(nodes_url)
    write_nodes(nodes_text, f"{name}.txt")

    return [name, {"up_date": datetime.today().date().strftime("%Y-%m-%d")}]


if __name__ == "__main__":
    # "https://halekj.top"
    conf = Config("config.json")
    # try:
    # 创建线程池
    with ThreadPoolExecutor() as executor:
        futures = []
        # 提交函数给线程池
        for config in conf.configs:
            future = executor.submit(scrape, **config)
            futures.append(future)
            # 写更新日期
            if res := future.result():
                name, data = res
                conf.set_data(name, data)
    # except Exception as e:
    #     print(e)
    # if res := scrape(**conf.configs[3]):
    #     name, data = res
    #     conf.set_data(name, data)
