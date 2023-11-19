import re
import xml.etree.ElementTree as ET
from urllib.error import URLError
from http.client import IncompleteRead
import cv2
import numpy as np
import pytube

from APICaller import APICaller


def __get_frame(video_capture: cv2.VideoCapture) -> np.ndarray:
    """生成视频截图"""
    total_frames = int(video_capture.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = video_capture.get(cv2.CAP_PROP_FPS)
    start_frame = total_frames * 2 // 3  # 从视频2/3处开始

    # 倒序截图
    for i in range(int(total_frames - fps), start_frame, int(-2 * fps)):
        video_capture.set(cv2.CAP_PROP_POS_FRAMES, i)
        ret, frame = video_capture.read()
        if ret:
            # print(f"截图在 {i // fps}s", end="\t")
            h, w = frame.shape[:2]
            yield frame[h // 4:h, w // 8:w * 7 // 8]  # 保留字幕部分


def __find_pwd(text: str) -> str:
    """判断文本中是否包含密码"""
    if "码" in text:
        num_list = re.findall(r"\d+", text)
        word = "".join(num_list)
        print(f"候选 {word}")
        return word


def _get_stream(yt: pytube.YouTube):
    """获取视频流"""
    for opt in ["360p", "480p", "720p"]:
        for i in range(3):
            try:
                if stream := yt.streams.get_by_resolution(opt):
                    print(f"获取视频流 {opt}")
                    return stream
            except (URLError, IncompleteRead) as e:
                print(e)
    raise "无法获取视频流"


def _get_pwd_by_ocr(apicaller: APICaller, image: np.ndarray) -> str:
    """调用ocr获得密码"""
    apicaller.img_to_base64(image)  # 传入截图
    result = apicaller.digital_ocr()  # 调用ocr
    words_result = result.get("words_result")
    num = result.get("words_result_num")

    # 遍历截图中的候选词
    for i in range(int(num)):
        text = words_result[i]["words"]
        yield __find_pwd(text)


def _get_pwd_from_caption(subtitles: list[pytube.Caption]) -> str:
    """遍历字幕获得密码"""
    for caption in subtitles:
        # 遍历字幕
        xml_str = caption.xml_captions

        root = ET.fromstring(xml_str)
        # 遍历XML中的所有<p>元素
        for p_element in root.findall(".//p"):
            # 获取文本内容和时间属性
            text = p_element.text
            time = int(p_element.get("t"))
            duration = int(p_element.get("d"))
            yield __find_pwd(text)


def get_pwd(url: str) -> str:
    """获取候选密码"""
    # 创建 YouTube 对象
    yt = pytube.YouTube(url)

    # 获取视频流
    stream = _get_stream(yt)

    # 通过字幕获取密码
    if subtitles := yt.captions.all():
        yield from (pwd for pwd in _get_pwd_from_caption(subtitles) if pwd)

    # 调用ocr获得密码
    else:
        apicaller = APICaller()  # apicaller 实例
        cap = cv2.VideoCapture(stream.url)  # VideoCapture 实例获取截图
        for frame in __get_frame(cap):
            yield from (pwd for pwd in _get_pwd_by_ocr(apicaller, frame) if pwd)

        cap.release()  # 释放视频捕获对象


if __name__ == "__main__":
    # test
    link_urls = ["https://youtu.be/pOudt0bNR-E", "https://youtu.be/iSjIqpII2AY"]

    for PWD in get_pwd(link_urls[0]):
        print(PWD)
