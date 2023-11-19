import base64
import json
import requests

import cv2
from numpy import ndarray


class APICaller:
    __url = "https://aip.baidubce.com/oauth/2.0/token"
    __api_key = "oywBfZcck0aG5cwDMcSNWbYL"
    __secret_key = "WXDlfqs4ngT7PMkYQGmkCjzrnm7oErGK"
    __access_token: str
    image: ndarray
    b_base64: base64

    def __init__(self):
        """使用 AK, SK 生成鉴权签名(Access Token)"""
        params = {"grant_type": "client_credentials", "client_id": self.__api_key, "client_secret": self.__secret_key}
        self.__access_token = str(requests.post(self.__url, params=params).json().get("access_token"))
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
        :return: 响应格式 {"words_result":[] , "words_result_num": int, "log_id"}
        """
        post_url = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"
        params = {"access_token": self.__access_token}
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        payload = {"image": self.b_base64, "detect_direction": "false"}

        # 发送 POST 请求
        response = requests.request("POST", post_url, params=params, headers=headers, data=payload)
        # print("接收百度云ocr响应", end="\t")
        return json.loads(response.text)
