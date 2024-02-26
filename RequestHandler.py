import base64
from typing import TypedDict

import cv2
import kuser_agent
import requests
from numpy import ndarray
from requests.adapters import HTTPAdapter

from urllib3 import Retry

retries = Retry(connect=3, read=3, backoff_factor=3,
                status_forcelist=[408, 413, 424, 425, 429, 500, 502, 503, 504])
session = requests.Session()
session.keep_alive = False
session.mount('http://', HTTPAdapter(max_retries=retries))
session.mount('https://', HTTPAdapter(max_retries=retries))



def make_request(method: str, url: str,
                 params=None, data=None, headers=None, timeout=None):
    """请求服务器"""
    headers = headers if headers else {"User-Agent": kuser_agent.get()}
    response = session.request(method, url, params, data, headers,
                               timeout=timeout)
    return response


def img2base64(image: ndarray) -> base64:
    """获取图像 base64 编码"""
    retval, buffer = cv2.imencode(".jpg", image)
    return base64.b64encode(buffer.tobytes())


class WordsData(TypedDict):
    words: str


class OCRRes(TypedDict):
    words_result: list[WordsData]
    words_result_num: int
    log_id: int
    error_code: int
    error_msg: str


class OCRCaller:
    """技术文档: https://cloud.baidu.com/doc/OCR/index.html"""
    access_url = "https://aip.baidubce.com/oauth/2.0/token"
    post_urls = [
        {"url"   : "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic",
         "usable": True},
        {"url"   : "https://aip.baidubce.com/rest/2.0/ocr/v1/general",
         "usable": True},
        {"url"   : "https://aip.baidubce.com/rest/2.0/ocr/v1/webimage",
         "usable": True},
        {"url"   : "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate",
         "usable": True}]
    access_token: str
    name: str
    
    def __init__(self, name: str, api_key: str, secret_key: str):
        """使用 AK, SK 生成鉴权签名(Access Token)"""
        params = {"grant_type": "client_credentials",
                  "client_id" : api_key, "client_secret": secret_key}
        response = make_request("POST", self.access_url, params=params)
        self.access_token = response.json().get("access_token")
        self.name = name
    
    def request_ocr(self, image: ndarray) -> OCRRes:
        """向百度云数字ocr发送图片, 接收响应"""
        params = {"access_token": self.access_token}
        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "Accept"      : "application/json"}
        payload = {"image": img2base64(image), "detect_direction": "false"}
        
        # 发送 POST 请求
        for i, item in enumerate(self.post_urls):
            if not item["usable"]: continue
            response = make_request("POST", item.get("url"),
                                    params, payload, headers)
            result = OCRRes(**response.json())
            if "error_code" in result:
                print(result["error_msg"])
                self.post_urls[i]["usable"] = False
                continue
            else: return result
