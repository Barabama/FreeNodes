import base64

import cv2
import requests
from numpy import ndarray

access_url = "https://aip.baidubce.com/oauth/2.0/token"
post_urls = [{"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic", "usable": True},
             {"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/general", "usable": True},
             {"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/webimage", "usable": True},
             {"url": "https://aip.baidubce.com/rest/2.0/ocr/v1/accurate", "usable": True}]


class APICaller:
    access_token: str
    image: ndarray
    b_base64: base64

    def __init__(self, api_key: str, secret_key: str):
        """使用 AK, SK 生成鉴权签名(Access Token)"""
        params = {"grant_type": "client_credentials", "client_id": api_key, "client_secret": secret_key}
        self.access_token = requests.post(access_url, params=params).json().get("access_token")
        if not self.access_token:
            print("APICaller初始化失败, 无法生成AccessToken")
            raise ValueError
        print("APICaller初始化成功, 生成AccessToken")

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
        params = {"access_token": self.access_token}
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        payload = {"image": self.b_base64, "detect_direction": "false"}

        # 发送 POST 请求
        for i, elem in enumerate(post_urls):
            if not elem["usable"]:
                continue

            res = requests.request("POST", elem.get("url"), params=params, headers=headers, data=payload).json()
            # print("接收百度云ocr响应", end="\t")

            if "error_code" in res:
                print(res.get("error_msg"))
                post_urls[i]["usable"] = False
            else:
                return res
