import base64
import requests
import cv2
from numpy import ndarray


class APICaller:
    __access_url = "https://aip.baidubce.com/oauth/2.0/token"
    __post_urls = [{"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic", "usable": True},
                   {"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/general", "usable": True},
                   {"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/webimage", "usable": True},
                   {"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate", "usable": True}]
    __access_token: str
    image: ndarray
    b_base64: base64

    def __init__(self, api_key: str, secret_key: str):
        """使用 AK, SK 生成鉴权签名(Access Token)"""
        params = {"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key}
        self.__access_token = str(requests.post(self.__access_url, params=params).json().get("access_token"))
        print("APICaller初始化, 生成AccessToken")

    def img_to_base64(self, image: ndarray):
        """获取图像 base64 编码"""
        self.image = image
        retval, buffer = cv2.imencode(".jpg", image)
        self.b_base64 = base64.b64encode(buffer.tobytes())
        # print(f"图像base64编码", end=" ")

    def digital_ocr(self) -> dict:
        """
        向百度云数字ocr发送图片, 接收响应
        技术文档: https://cloud.baidu.com/doc/OCR/index.html
        :return: {"words_result":[] , "words_result_num": int, "log_id"}
        """
        params = {"access_token": self.__access_token}
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        payload = {"image": self.b_base64, "detect_direction": "false"}

        # 发送 POST 请求
        for i, elem in enumerate(self.__post_urls):
            if not elem.get("usable"):
                continue

            res = requests.request("POST", elem.get("url"), params=params, headers=headers, data=payload).json()
            # print("接收百度云ocr响应", end="\t")

            if "error_code" in res:
                print(res.get("error_msg"))
                self.__post_urls[i]["usable"] = False
            else:
                return res
