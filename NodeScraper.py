import re
from datetime import datetime
from typing import Generator
from urllib.parse import urljoin

from bs4 import Tag, BeautifulSoup
from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from Config import Decryption
from RequestHandler import make_request


def gen_elem(markup: str, element="", attrs=None) -> Generator[Tag, None, None]:
    """获取网页元素"""
    if attrs is None: attrs = {}
    soup = BeautifulSoup(markup, "html.parser")
    yield from soup.find_all(element, attrs)


class NodeScraper:
    name: str
    up_date: str
    web_date: datetime
    detail_url: str
    detail_text: str
    pattern: str
    nodes_index: int
    decryption: Decryption
    driver: webdriver.Chrome
    
    def __init__(self, name: str, up_date: str, main_url: str, attrs: dict,
                 pattern: str, nodes_index=0, decryption=None):
        """
        :param name: 保存的文件名
        :param up_date: 更新日期
        :param main_url: 主页链接
        :param attrs: 抓取属性
        :param pattern: 节点链接匹配表达式
        :param nodes_index: 节点链接索引
        :param decryption: 解密参数
        """
        self.name = name
        self.up_date = up_date
        self.pattern = pattern
        self.nodes_index = nodes_index
        self.decryption = decryption if decryption is not None \
            else Decryption(**{})
        
        main_text = make_request("GET", main_url).text
        a_tag_iter = (e for e in gen_elem(main_text, "a", attrs))
        detail_url = next(a_tag_iter, {}).get("href", "")
        self.detail_url = urljoin(main_url, detail_url)
        self.detail_text = make_request("GET", self.detail_url).text
        
        if self.detail_text: print(f"{self.name}: 访问 {self.detail_url}")
        else: raise RuntimeError(f"{self.name}: 无法访问 {self.detail_url}")
    
    def init_webdriver(self) -> webdriver.Chrome:
        """虚拟浏览器初始化"""
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 启用无头模式
        self.driver = webdriver.Chrome(options)  # 创建浏览器实例
        self.driver.get(self.detail_url)  # 打开详情页
        return self.driver
    
    def is_locked(self) -> bool:
        """判断网页中是否存在解密元素"""
        locked_elems = [{"element": "input", "attrs": {"id": "EPassword"}},
                        {"element": "input", "attrs": {"id": "pwbox-426"}},
                        {"element": "input", "attrs": {"name": "secret-key"}}]
        return any(gen_elem(self.detail_text, **e) for e in locked_elems)
    
    def is_new(self, force=True) -> bool:
        """判断网页的是否更新"""
        h1 = "".join(e.text for e in gen_elem(self.detail_text, "h1"))
        if "正在制作" in h1: return False
        if match := re.search(r"\d+月\d+", h1):
            web_date = datetime.strptime(str(match.group()), "%m月%d")
            self.web_date = web_date.replace(year=datetime.today().year)
            up_date = datetime.strptime(self.up_date, "%Y-%m-%d")
            return True if self.web_date.date() > up_date.date() or force else False
    
    def get_nodes_url(self, text="") -> str:
        """匹配txt文本链接"""
        text = text if text else self.detail_text
        texts = re.findall(self.pattern, text)
        return texts[self.nodes_index] if texts else ""
    
    def get_yt_url(self) -> str:
        """获取 youtube 视频链接"""
        # 获取详情页所有链接
        hrefs = [str(tag.get("href")) for tag in
                 gen_elem(self.detail_text, "a")]
        # 获取youtube链接
        yt_urls = [href for href in hrefs if
                   href.startswith("https://youtu.be/")]
        # 根据yt_index取链接
        return yt_urls[self.decryption.get("yt_index", 0)] if yt_urls else ""
    
    def decrypt_for_text(self, pwd: str) -> tuple[bool, str]:
        """网页解密得到隐藏文本内容"""
        decrypt_by = self.decryption.get("decrypt_by", "click")
        
        # 传递参数给JavaScript函数
        if decrypt_by == "js":
            self.driver.execute_script(self.decryption["script"], pwd)
        
        # 模拟输入提交
        else:
            # 定位文本框
            by, value = self.decryption["textbox"]
            textbox = self.driver.find_element(by, value)
            textbox.send_keys(pwd)
            # 定位按钮
            by, value = self.decryption["button"]
            button = self.driver.find_element(by, value)
            button.submit()
        
        try:
            alert = WebDriverWait(self.driver, 2).until(EC.alert_is_present())
            msg = alert.text
            alert.accept()  # 处理alert弹窗
            return False, msg
        except TimeoutException:
            return True, self.driver.find_element(By.TAG_NAME, "body").text
