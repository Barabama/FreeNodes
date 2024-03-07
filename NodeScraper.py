import re
from datetime import datetime
from urllib.parse import parse_qsl, urljoin, urlsplit

from bs4 import BeautifulSoup
from pyyoutube import Api
from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

from Config import Decryption
from PwdFinder import find_pwd
from RequestHandler import make_request


# def gen_elem(markup: str, element="", attrs=None) -> Generator[Tag, None, None]:
#     """获取网页元素"""
#     if attrs is None: attrs = {}
#     soup = BeautifulSoup(markup, "html.parser")
#     yield from soup.find_all(element, attrs)


class NodeScraper:
    name: str
    up_date: str
    web_date: datetime
    detail_url: str
    detail_text: str
    detail_soup: BeautifulSoup
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
        
        if main_url.startswith("https://www.youtube.com"):
            self.init_webdriver()
            self.driver.get(main_url)
            main_text = self.driver.page_source
        else:
            main_text = make_request("GET", main_url).text
        
        main_soup = BeautifulSoup(main_text, "html.parser")
        
        # 选择最新的有日期的
        for tag in main_soup.find_all("a", attrs):
            match = re.search(r"\d+月\d+", tag.prettify())
            if not match: continue
            web_date = datetime.strptime(str(match.group()), "%m月%d")
            self.web_date = web_date.replace(year=datetime.today().year)
            self.detail_url = urljoin(main_url, tag.get("href", ""))  # 获得完整地址
            break
    
    def init_webdriver(self):
        """虚拟浏览器初始化"""
        options = webdriver.ChromeOptions()
        options.add_argument("--headless")  # 启用无头模式
        self.driver = webdriver.Chrome(options)  # 创建浏览器实例
    
    def get_detail(self):
        """获取详情页"""
        if detail_text := make_request("GET", self.detail_url).text:
            print(f"{self.name}: 访问 {self.detail_url}")
            self.detail_text = detail_text
            self.detail_soup = BeautifulSoup(self.detail_text, "html.parser")
        
        else:
            raise RuntimeError(f"{self.name}: 无法访问 {self.detail_url}")
    
    def is_locked(self) -> bool:
        """判断网页中是否存在解密元素"""
        locked_elems = [{"name": "input", "attrs": {"id": "EPassword"}},
                        {"name": "input", "attrs": {"id": "pwbox-426"}},
                        {"name": "input", "attrs": {"name": "secret-key"}}]
        elems = [e for le in locked_elems for e in
                 self.detail_soup.find_all(**le)]
        return any(elems)
    
    def is_latest(self) -> bool:
        """判断已经是最新的"""
        # if "正在制作" in h1: return False
        up_date = datetime.strptime(self.up_date, "%Y-%m-%d")
        return False if self.web_date.date() > up_date.date() else True
    
    def get_nodes_url(self, text="") -> str:
        """匹配txt文本链接"""
        text = text if text else self.detail_text
        texts = re.findall(self.pattern, text)
        return texts[self.nodes_index] if texts else ""
    
    def get_yt_url(self) -> str:
        """获取 youtube 视频链接"""
        # 获取详情页所有链接
        hrefs = [str(tag.get("href")) for tag in
                 self.detail_soup.find_all(attrs="a")]
        # 获取youtube链接
        yt_urls = [href for href in hrefs if
                   href.startswith("https://youtu.be")]
        # 根据yt_index取链接
        return yt_urls[self.decryption.get("yt_index", 0)] if yt_urls else ""
    
    def decrypt_for_text(self, pwd: str, url="") -> tuple[bool, str]:
        """网页解密得到隐藏文本内容"""
        url = url if url else self.detail_url
        print(f"{self.name}: 访问 {url}")
        self.driver.get(url)
        wait = WebDriverWait(self.driver, 10)
        wait.until(EC.presence_of_element_located((By.TAG_NAME, "form")))
        
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
    
    def get_description(self, yt_key="") -> tuple[str, str]:
        """从视频描述中获取密码和下载链接"""
        id = dict(parse_qsl(urlsplit(self.detail_url).query))["v"]
        api = Api(api_key=yt_key)
        response = api.get_video_by_id(video_id=id, parts="snippet")
        
        snippet = response.items[0].to_dict().get("snippet", {})
        description = snippet.get("description", "")
        ls = [s for s in description.splitlines() if s.strip()]
        
        pwd = ""
        link = ""
        for i, s in enumerate(ls):
            if p := find_pwd(s): pwd = p
            if "下载" not in s: continue
            elif match := re.search(r"https://[^\r\n\s]+",
                                    f"{ls[i]}\n{ls[i + 1]}"):
                link = match.group()
                break
        return pwd, link
