import base64
import json

import cv2
import numpy as np
import requests
import pytube


def _get_stream(url: str) -> str:
    """
    获取视频流链接
    :param url: 视频链接
    :return: 视频流链接
    """
    # 创建 YouTube 对象
    yt = pytube.YouTube(url)

    # 获取视频流
    stream = None
    for opt in ["360p", "480p", "720p"]:
        stream = yt.streams.get_by_resolution(opt)
        if stream:
            print(f"获取视频流 {opt}")
            return stream.url


def _get_frame(stream_url: str) -> np.ndarray:
    """
    生成视频截图
    :param stream_url: 视频流链接
    :return: 截图
    """
    # 使用 VideoCapture 获取截图
    cap = cv2.VideoCapture(stream_url)

    for i in range(76, 79):
        cap.set(cv2.CAP_PROP_POS_MSEC, i * 1000)
        ret, frame = cap.read()
        if ret:
            print(f"截图在 {i} s")
            yield frame

    # 释放视频捕获对象
    cap.release()


def _get_img_as_base64(image: np.ndarray) -> base64:
    """
    获取图片 base64 编码
    :param image: ndarray 图片
    :return: base64 编码信息
    """
    retval, buffer = cv2.imencode(".jpg", image)
    content = base64.b64encode(buffer.tobytes())
    print(f"对图像 base64 编码")
    return content


def _get_access_token() -> str:
    """
    使用 AK, SK 生成鉴权签名(Access Token)
    :return: access_token, 或 None (如果错误)
    """
    API_KEY = "oywBfZcck0aG5cwDMcSNWbYL"
    SECRET_KEY = "WXDlfqs4ngT7PMkYQGmkCjzrnm7oErGK"

    url = "https://aip.baidubce.com/oauth/2.0/token"
    params = {"grant_type": "client_credentials", "client_id": API_KEY, "client_secret": SECRET_KEY}
    access_token = str(requests.post(url, params=params).json().get("access_token"))

    return access_token


def _digital_ocr(b_base64: base64) -> dict:
    post_url = "https://aip.baidubce.com/rest/2.0/ocr/v1/numbers"
    params = {
        "access_token": _get_access_token()
    }
    headers = {
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json"
    }
    payload = {
        "image": b_base64,
        "detect_direction": "false"
    }

    # 发送 POST 请求
    response = requests.request("POST", post_url, params=params, headers=headers, data=payload)
    print("接收百度云ocr响应")
    return json.loads(response.text)


def _ocr_pwd(stream_url: str) -> list[tuple]:
    passwords = {}  # 密码出现频率字典
    # 遍历截图
    for frame in _get_frame(stream_url):
        b_64 = _get_img_as_base64(frame)
        result = _digital_ocr(b_64)
        words_result = result.get("words_result")
        num = result.get("words_result_num")

        # 遍历截图中的候选词
        for i in range(int(num)):
            words = words_result[i]["words"]
            passwords[words] = (passwords[words] + 1) if words in passwords else 1

    # 频率降序排列的元组列表
    return sorted(passwords.items(), key=lambda x: x[1], reverse=True)


def get_pwd(url: str, ocr: bool):
    passwords = []

    stream_url = _get_stream(url)
    if ocr:
        passwords = _ocr_pwd(stream_url)
    else:
        # TODO: 通过字幕获取密码

        pass
    return passwords


if __name__ == "__main__":
    link_url = ["https://youtu.be/bAaIa0KDSZ8","https://youtu.be/Iw7vlPCYO28"]

    pwds = get_pwd(link_url[1], True)

    print(pwds)
