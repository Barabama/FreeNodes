# PwdFinder.py

import datetime as dt
import itertools
import logging
import re
import xml.etree.ElementTree as ET
from typing import Generator

import cv2
import numpy as np
import pytubefix
from pytubefix.cli import on_progress
from paddleocr import PaddleOCR
from skimage.metrics import structural_similarity as ssim


def _keyframe_iter(url: str, threshold=0.8) -> Generator[tuple[int, np.ndarray], None, None]:
    """Generate keyframes backwards."""
    cap = cv2.VideoCapture(url)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    prev = None
    for i in range(int(count - fps), 0, int(-1 * fps)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        if not cap.isOpened():
            break
        ret, frame = cap.read()
        if not ret:
            break

        # frame = frame[height * 3 // 4:height, 0:width]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if prev is not None and ssim(prev, gray) < threshold:
            yield i, frame

        prev = gray

    cap.release()


class PwdFinder:
    name: str
    logger: logging.Logger
    date: str
    descriptions: list[str]
    subtitles: pytubefix.CaptionQuery
    stream: pytubefix.Stream
    ocr: PaddleOCR

    def __init__(self, name: str, logger: logging.Logger, url: str):
        self.name = name
        self.logger = logger

        yt = pytubefix.YouTube(url, use_oauth=True, use_po_token=True,
                               allow_oauth_cache=True,
                               on_progress_callback=on_progress)

        # date = yt.publish_date.date() # Not working
        # self.date = date.strftime("%Y-%m-%d")

        match = re.search(r"(?:\d{4}[-年])?(\d{1,2})[-月](\d{1,2})", yt.title)
        if not match:
            self.logger.error(f"{name} found no date")
            return
        date = dt.date(dt.date.today().year, *map(int, match.groups()))
        self.date = date.strftime("%Y-%m-%d")
        self.logger.info(f"{name} found date: {self.date}")

        self.descriptions = yt.description.splitlines()
        self.subtitles = yt.captions
        if not self.subtitles:
            self.logger.warning(f"{name} found no subtitles")

            opt = ["360p", "480p", "720p"]
            self.stream = yt.streams.filter(res=opt).get_lowest_resolution()
            if not self.stream:
                self.logger.error(f"{name} found no video stream")
                return

            self.logger.info(f"{name} found a video stream")
            self.ocr = PaddleOCR(use_angle_cls=True, lang="ch")

    def _xml_caption_iter(self):
        """Generate subtitles."""
        l = len(self.subtitles)
        for i, caption in enumerate(self.subtitles):
            self.logger.info(f"{self.name} reading subtitles {i}/{l}")
            root = ET.fromstring(caption.xml_captions)
            for p_elem in root.findall(".//p"):
                yield p_elem.text

    def _ocr_result_iter(self):
        """Generate OCR results."""
        for i, frame in _keyframe_iter(self.stream.url):
            self.logger.info(f"{self.name} reading keyframes {i}")
            results = self.ocr.ocr(frame)[0]
            if not results:
                continue

            for result in results:
                if result[1][1] > 0.9:
                    yield result[1][0]

    def password_iter(self, key: str):
        """Generate possible passwords."""
        text_iter = self._xml_caption_iter if self.subtitles else self._ocr_result_iter
        for text in itertools.chain(iter(self.descriptions), text_iter()):
            self.logger.debug(f"{self.name} found text: {text}")
            if key not in text:
                continue
            yield from filter(lambda x: x, re.findall(f"\\d+", text))


if __name__ == "__main__":
    logging.disable(logging.DEBUG)
    urls = ['https://www.youtube.com/watch?v=StNJHi5b2oM',
            'https://www.youtube.com/watch?v=is7vn5URVcc']
    logger = logging.getLogger()
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG)
    logger.addHandler(console)
    for url in urls:
        f = PwdFinder('test', logger, url)
