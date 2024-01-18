import re
import sys
import xml.etree.ElementTree as ET
from typing import Generator

import cv2
import numpy as np
import pytube

from MsgHandler import MsgHandler, CustomError
from RequestHandler import OCRCaller


def find_pwd(text: str) -> str:
    """判断文本中是否包含密码"""
    if "码" in text:
        num_list = re.findall(r"\d+", text)
        word = "".join(num_list)
        return word
    else:
        return ""


class PwdFinder:
    stream: pytube.Stream
    subtitles: list[pytube.Caption]

    def __init__(self, msg_handler: MsgHandler, url: str, api_key: str, secret_key: str):
        self.msg_handler = msg_handler
        yt = pytube.YouTube(url)
        for opt in ["360p", "480p", "720p"]:
            if stream := yt.streams.get_by_resolution(opt):
                self.msg_handler.show_msg(f"获取视频流 {opt}")
                self.stream = stream
                break

        self.subtitles = yt.captions.all()
        if not self.subtitles:
            self.ocr_caller = OCRCaller(api_key, secret_key)

            if not self.ocr_caller.access_token:
                raise CustomError("OCRCaller初始化失败, 无法生成AccessToken")
            else:
                self.msg_handler.show_msg("OCRCaller初始化成功, 生成AccessToken")

    def gen_frame(self) -> Generator[np.ndarray, None, None]:
        """生成视频截图"""
        cap = cv2.VideoCapture(self.stream.url)

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        start_frame = total_frames * 1 // 3  # 从视频1/3处开始
        fps = cap.get(cv2.CAP_PROP_FPS)

        # 密码靠后, 倒序截图
        for i in range(int(total_frames - fps), start_frame, int(-2 * fps)):
            cap.set(cv2.CAP_PROP_POS_FRAMES, i)
            ret, frame = cap.read()
            if ret:
                h, w = frame.shape[:2]
                yield frame[h * 3 // 4:h, w // 8:w * 7 // 8]  # 保留字幕部分

        cap.release()  # 释放视频捕获对象

    def gen_pwd(self) -> Generator[str, None, None]:
        """生成候选密码"""
        if self.subtitles:
            # 遍历字幕
            for caption in self.subtitles:
                root = ET.fromstring(caption.xml_captions)
                # 遍历XML中的所有<p>元素
                for p_elem in root.findall(".//p"):
                    yield find_pwd(p_elem.text)
        else:
            for frame in self.gen_frame():
                self.ocr_caller.img_to_base64(frame)  # 传入截图
                result = self.ocr_caller.digital_ocr()  # 调用ocr
                words_result = result.get("words_result", [])
                num = result.get("words_result_num", 0)

                # 遍历截图中的候选词
                for i in range(num):
                    word = words_result[i].get("words", "")
                    yield find_pwd(word)


if __name__ == "__main__":
    # test
    link_urls = ["https://youtu.be/C7skrsccDQQ", "https://youtu.be/1lIctdmKqa0"]
    script, *args = sys.argv
    msg_handler = MsgHandler("test")
    pwd_finder = PwdFinder(msg_handler, link_urls[1], *args)
    print([pwd for pwd in pwd_finder.gen_pwd() if pwd])
