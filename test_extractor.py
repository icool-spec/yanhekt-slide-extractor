import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import numpy as np
from PIL import Image, ImageDraw

from yanhekt_extract import analyze, parse_playlist, similar


class PlaylistTests(unittest.TestCase):
    def test_variable_segment_lengths(self):
        segments, total = parse_playlist("#EXTM3U\n#EXTINF:2.5,\na.ts\n#EXTINF:1.25,\nb.ts\n#EXT-X-ENDLIST")
        self.assertEqual(segments, [(0, 2.5, "a.ts"), (2.5, 1.25, "b.ts")])
        self.assertEqual(total, 3.75)

    def test_rejects_live_or_empty_playlist(self):
        for text in ("#EXTM3U\n#EXTINF:2,\na.ts", "#EXTM3U\n#EXT-X-ENDLIST"):
            with self.assertRaises(ValueError):
                parse_playlist(text)

    def test_rejects_unsupported_layouts(self):
        for tag in ("#EXT-X-KEY:METHOD=AES-128,URI=key", "#EXT-X-MAP:URI=init", "#EXT-X-BYTERANGE:100", "#EXT-X-DISCONTINUITY", "#EXT-X-STREAM-INF:BANDWIDTH=100"):
            with self.subTest(tag=tag), self.assertRaises(ValueError):
                parse_playlist(f"#EXTM3U\n{tag}\n#EXTINF:2,\na.ts\n#EXT-X-ENDLIST")

    def test_rejects_invalid_duration(self):
        for value in ("0", "-1", "nan", "inf"):
            with self.assertRaises(ValueError):
                parse_playlist(f"#EXTM3U\n#EXTINF:{value},\na.ts\n#EXT-X-ENDLIST")


class ScreenTests(unittest.TestCase):
    def test_cursor_change_vs_content_change(self):
        original = np.full((216,384),255,dtype=np.int16)
        cursor = original.copy()
        cursor[100:103,100:103] = 0
        text = original.copy()
        text[40:50,40:170] = 0
        self.assertTrue(similar(original,cursor))
        self.assertFalse(similar(original,text))

    def test_dedup_and_export(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            samples = output / "samples"
            samples.mkdir()
            # A stable page, one transient frame, a second page, then return to A.
            for index,color in enumerate(("white","white","white","red","blue","blue","blue","white","white"),1):
                image = Image.new("RGB",(640,360),color)
                ImageDraw.Draw(image).rectangle((30,30,100,70),fill="black")
                image.save(samples / f"frame_{index:06d}.jpg")
            result = analyze(output,5)
            self.assertEqual(result["samples"],9)
            self.assertEqual(len(result["candidates"]),2)
            self.assertEqual(result["candidates"][0]["time_seconds"],7.5)
            self.assertIn("持续约 15 秒",(output/"candidates.html").read_text(encoding="utf-8"))
            (output/"report.json").write_text(json.dumps(result | {"sample_interval_seconds":5}),encoding="utf-8")
            command = [sys.executable,str(Path(__file__).with_name("yanhekt_finalize.py")),"--output",str(output),"--exclude","2","--title","<Test>"]
            completed = subprocess.run(command,capture_output=True)
            self.assertEqual(completed.returncode,0,completed.stderr)
            gallery = (output/"index.html").read_text(encoding="utf-8")
            self.assertIn("&lt;Test&gt;",gallery)
            self.assertIn("每 5 秒",gallery)
            self.assertNotIn("1920×1080",gallery)
            with zipfile.ZipFile(output/"slides.zip") as archive:
                self.assertIsNone(archive.testzip())
                self.assertEqual(len([n for n in archive.namelist() if n.endswith(".jpg")]),1)
            # A second export must not silently mix or overwrite previous files.
            repeated = subprocess.run(command,capture_output=True)
            self.assertNotEqual(repeated.returncode,0)

    def test_missing_frames_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                analyze(Path(directory),2)


if __name__ == "__main__":
    unittest.main()
