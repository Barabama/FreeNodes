# DecryptedSpider.py

import itertools

from selenium import webdriver
from selenium.common import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from scrapy.http import Response

from NodeScrapy.spiders.SimpleSpider import SimpleSpider
from utils.Config import CONFIG, ConfigData
from utils.PwdFinder import PwdFinder


class DecryptSpider(SimpleSpider):
    name = "decrypt"
    custom_settings = {"LOG_FILE": "scrapy.log",
                       "LOG_FILE_APPEND": True,
                       "LOG_LEVEL": "INFO"}
    targets = ("yudou66", "blues")
    configs: dict[str, ConfigData]
    driver: webdriver.Chrome

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.configs = {name: CONFIG.get(name) for name in self.targets}

        options = webdriver.ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--page-load-strategy=eager")
        self.driver = webdriver.Chrome(options=options)

    def start_requests(self):
        yield from super().start_requests()

    def parse(self, response: Response):
        yield from super().parse(response)

    def _decrypt(self, name: str, url: str, pwd: str) -> tuple[bool, str]:
        config = self.configs[name]

        self.driver.get(url)
        wait = WebDriverWait(self.driver, 10)
        wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "input")))

        self.driver.execute_script(config["script"], pwd)
        # by, val = self.configs[name]["textbox"]
        # textbox = self.driver.find_element(by, val)
        # textbox.send_keys(pwd)
        # by, val = self.configs[name]["button"]
        # button = self.driver.find_element(by, val)
        # button.submit()

        try:
            alert = WebDriverWait(self.driver, 2).until(EC.alert_is_present())
            msg = alert.text
            alert.accept()
            return False, msg
        except TimeoutException:
            return True, self.driver.find_element(By.TAG_NAME, "body").text

    def parse_detail(self, response: Response):
        name = response.meta["name"]
        config = self.configs[name]

        yt_url = [url for url in response.css("a::attr(href)").getall()
                  if "youtu.be" in url][CONFIG.get(name)["yt_idx"]]

        pwdfinder = PwdFinder(name, self.logger, yt_url)
        if pwdfinder.date != response.meta["date"]:
            self.logger.error(f"{name} found yt_url: {yt_url} mismatch the date, exiting")
            return

        old_pwd = config["password"]
        for pwd in itertools.chain(iter([old_pwd]), pwdfinder.password_iter("码")):
            ok, msg = self._decrypt(name, response.url, pwd)
            if not ok:
                self.logger.warning(f"{name} {pwd} got {msg}")
                continue

            for link, ext in super()._find_link(name, msg):
                response.meta["ext"] = ext
                yield response.follow(link, self.parse_link, meta=response.meta)

            if old_pwd != pwd:
                CONFIG.set(name, {"password": pwd})
                self.logger.info(f"{name} saved new password {pwd}")

    def parse_link(self, response: Response):
        yield from super().parse_link(response)

    def closed(self, reason):
        super().closed(reason)
        self.driver.quit()
