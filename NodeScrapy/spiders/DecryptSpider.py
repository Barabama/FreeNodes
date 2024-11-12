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

    def closed(self, reason):
        self.driver.quit()
        super().closed(reason)

    def _decrypt(self, url: str, method: dict, pwd: str) -> tuple[bool, str]:
        """Decrypt the page with the given password."""
        self.driver.get(url)
        wait = WebDriverWait(self.driver, 10)
        wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "input")))
        wait.until(EC.presence_of_all_elements_located((By.TAG_NAME, "button")))
        if "script" in method:
            self.driver.execute_script(method["script"], pwd)
        else:
            textbox = self.driver.find_element(*method["textbox"])
            textbox.send_keys(pwd)
            button = self.driver.find_element(*method["button"])
            button.submit()
        try:
            alert = WebDriverWait(self.driver, 2).until(EC.alert_is_present())
            msg = alert.text
            alert.accept()
            return False, msg
        except TimeoutException:
            return True, self.driver.find_element(By.TAG_NAME, "body").text

    def parse_blog(self, response: Response):
        """Parse blog with decryption."""
        # Yield requests from super class, which no need to be decrypted.
        yield_flag = False
        for req in super().parse_blog(response):
            yield_flag = True
            yield req
        if yield_flag:
            return

        # If nothing yielded from super method, parse what needs to be decrypted.
        name = response.meta["name"]
        yt_url = [url for url in response.css("a::attr(href)").getall()
                  if "youtu.be" in url][CONFIG.get(name)["yt_idx"]]
        self.logger.info(f"{name} found yt_url: {yt_url}")
        pwdfinder = PwdFinder(name, self.logger, yt_url)
        if pwdfinder.date != response.meta["date"]:
            self.logger.error(f"{name} found yt_url mismatch the date, exiting")
            return

        old_pwd = self.configs[name]["password"]
        method = {"script": self.configs[name]["script"]}
        for pwd in itertools.chain(iter([old_pwd]), pwdfinder.password_iter("码")):
            ok, msg = self._decrypt(response.url, method, pwd)
            if not ok:
                self.logger.warning(f"{name} {pwd} got {msg}")
                continue

            for link, ext in super()._find_link(name, msg):
                response.meta["ext"] = ext
                yield response.follow(link, self.parse_link, meta=response.meta)

            if old_pwd != pwd:
                CONFIG.set(name, {"password": pwd})
                self.logger.info(f"{name} saved new password {pwd}")
            break
