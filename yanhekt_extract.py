"""Download an authorized VGA HLS stream and collect distinct stable screens.

Signed URL is read from a private text file; report never includes its query.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import html
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
from urllib.parse import urljoin, urlsplit, urlunsplit

import numpy as np
from PIL import Image, ImageDraw
import requests

from yanhekt_common import HEADERS
import imageio_ffmpeg


def parse_playlist(text):
    segments, clock, length = [], 0.0, None
    if not text.lstrip().startswith("#EXTM3U") or "#EXT-X-ENDLIST" not in text:
        raise ValueError("A completed media playlist is required")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(("#EXT-X-MAP:", "#EXT-X-BYTERANGE:", "#EXT-X-DISCONTINUITY", "#EXT-X-STREAM-INF:")):
            raise ValueError("Only a continuous MPEG-TS media playlist is supported")
        if line.startswith("#EXT-X-KEY:") and "METHOD=NONE" not in line:
            raise ValueError("Encrypted media is unsupported")
        if line.startswith("#EXTINF:"):
            length = float(line.split(":", 1)[1].split(",")[0])
            if not np.isfinite(length) or length <= 0:
                raise ValueError("Invalid segment duration")
        elif line and not line.startswith("#") and length is not None:
            segments.append((clock, length, line))
            clock += length
            length = None
    if not segments:
        raise ValueError("No media segments")
    return segments, clock


def signature(path):
    with Image.open(path) as image:
        return np.asarray(image.convert("L").resize((384, 216)), dtype=np.int16)


def similar(a, b):
    delta = np.abs(a - b)
    return float(delta.mean()) < 1.3 and float((delta > 22).mean()) < 0.006


def timestamp(seconds):
    return f"{int(seconds)//60:02d}:{int(seconds)%60:02d}"


def build_gallery(output, candidates, interval):
    for page in range((len(candidates) + 31) // 32):
        items = candidates[page*32:(page+1)*32]
        sheet = Image.new("RGB", (1280, ((len(items)+3)//4)*205), "#eeeeee")
        draw = ImageDraw.Draw(sheet)
        for cell, item in enumerate(items):
            x, y = (cell % 4)*320, (cell//4)*205
            with Image.open(output / item["file"]) as source:
                source.thumbnail((316, 178))
                sheet.paste(source, (x+2, y+25))
            draw.text((x+5, y+7), f"{item['id']:03d}  {timestamp(item['time_seconds'])}  {item['stable_samples']} samples", fill="black")
        sheet.save(output / f"contact_{page+1:02d}.jpg", quality=92)
    cards = ''.join(f'<a href="{html.escape(c["file"])}"><figure><img loading="lazy" src="{html.escape(c["file"])}"><figcaption>{c["id"]:03d} · {timestamp(c["time_seconds"])} · 持续约 {c["stable_samples"]*interval:g} 秒</figcaption></figure></a>' for c in candidates)
    (output / "candidates.html").write_text('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>课件候选截图</title><style>body{font:16px sans-serif;background:#eef2f5;padding:24px}main{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}a{color:#24344b;text-decoration:none}figure{margin:0;background:white;border-radius:8px;overflow:hidden}img{width:100%}figcaption{padding:12px}</style><h1>课件候选截图</h1><p>已按画面稳定性与相似度筛选；点击查看原尺寸。时间为采样点的近似位置。</p><main>'+cards+'</main></html>', encoding="utf-8")


def analyze(output, interval):
    paths = sorted((output / "samples").glob("frame_*.jpg"))
    if not paths:
        raise ValueError("No sampled frames found")
    runs, run, reference = [], [], None
    for index, path in enumerate(paths):
        current = signature(path)
        if reference is not None and not similar(reference, current):
            runs.append(run)
            run = []
            reference = None
        if reference is None:
            reference = current
        run.append((index, path))
    if run:
        runs.append(run)
    accepted, known = [], []
    candidate_dir = output / "candidates"
    candidate_dir.mkdir(exist_ok=True)
    for run in runs:
        # Reject single sampled frames, usually transitions or moving footage.
        if len(run) < 2:
            continue
        index, path = run[len(run)//2]
        current = signature(path)
        if any(similar(current, previous) for previous in known):
            continue
        identifier = len(accepted)+1
        target = candidate_dir / f"candidate_{identifier:03d}.jpg"
        shutil.copyfile(path, target)
        accepted.append({"id":identifier, "file":target.relative_to(output).as_posix(), "time_seconds":round((index+0.5)*interval,3), "stable_samples":len(run), "sample_file":path.relative_to(output).as_posix()})
        known.append(current)
    build_gallery(output, accepted, interval)
    return {"samples":len(paths), "stable_runs":sum(len(r)>=2 for r in runs), "candidates":accepted}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url-file")
    parser.add_argument("--output", default="output-course")
    parser.add_argument("--interval", type=float, help="Sampling interval in seconds (default: 2)")
    parser.add_argument("--analyze-only", action="store_true")
    args = parser.parse_args()
    if args.interval is not None and (not np.isfinite(args.interval) or args.interval <= 0):
        raise ValueError("Sample interval must be positive")
    output = Path(args.output).resolve()
    output.mkdir(exist_ok=True)
    started = time.monotonic()
    if args.analyze_only:
        report = json.loads((output / "report.json").read_text(encoding="utf-8"))
        saved_interval = report["sample_interval_seconds"]
        if args.interval is not None and args.interval != saved_interval:
            raise ValueError("Existing frames cannot be resampled; keep the original interval")
        args.interval = saved_interval
        # A new candidate analysis invalidates the old reviewed selection.
        report.pop("final_slides", None)
        report.pop("excluded_after_review", None)
    else:
        if not args.url_file:
            parser.error("--url-file is required unless --analyze-only is used")
        args.interval = args.interval or 2.0
        if any(output.iterdir()):
            raise ValueError("Output is not empty; choose a new directory or use --analyze-only")
        source = Path(args.url_file).read_text(encoding="utf-8").strip()
        if urlsplit(source).scheme not in {"https", "http"} or not urlsplit(source).netloc:
            raise ValueError("URL file must contain one HTTP(S) playlist URL")
        response = requests.get(source, headers=HEADERS, timeout=25)
        if response.status_code != 200:
            raise RuntimeError(f"Playlist HTTP {response.status_code}; refresh signed URL")
        segments, duration = parse_playlist(response.text)
        with tempfile.TemporaryDirectory(prefix="yanhekt-course-") as temporary:
            temporary = Path(temporary)
            def download(index):
                uri = urljoin(source, segments[index][2])
                parsed = urlsplit(uri)
                if not parsed.query:
                    uri = urlunsplit(parsed._replace(query=urlsplit(source).query))
                for attempt in range(3):
                    try:
                        result = requests.get(uri, headers=HEADERS, timeout=40)
                        if result.status_code != 200:
                            raise RuntimeError(f"Segment {index} HTTP {result.status_code}")
                        target = temporary / f"{index:04d}.ts"
                        target.write_bytes(result.content)
                        return len(result.content)
                    except requests.RequestException:
                        if attempt == 2:
                            raise RuntimeError(f"Segment {index} download failed") from None
            downloaded, completed = 0, 0
            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = [executor.submit(download, i) for i in range(len(segments))]
                for future in as_completed(futures):
                    downloaded += future.result()
                    completed += 1
                    if completed % 20 == 0 or completed == len(segments):
                        print(json.dumps({"stage":"download", "completed":completed, "total":len(segments), "mb":round(downloaded/1e6,1)}), flush=True)
            combined = temporary / "course.ts"
            with combined.open("wb") as destination:
                for index in range(len(segments)):
                    with (temporary / f"{index:04d}.ts").open("rb") as part:
                        shutil.copyfileobj(part, destination)
            samples = output / "samples"
            samples.mkdir(exist_ok=True)
            if any(samples.glob("frame_*.jpg")):
                raise RuntimeError("Output already contains samples; use --analyze-only or a new output directory")
            print(json.dumps({"stage":"decode", "interval_seconds":args.interval}), flush=True)
            command = [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-threads", "2", "-i",str(combined), "-vf",f"setpts=PTS-STARTPTS,fps=1/{args.interval}", "-q:v","2",str(samples/"frame_%06d.jpg")]
            process = subprocess.run(command, capture_output=True, timeout=900)
            if process.returncode:
                raise RuntimeError(process.stderr.decode(errors="replace")[:1000])
        report = {"source_path":urlsplit(source).path, "duration_seconds":round(duration,3), "segments_downloaded":len(segments), "downloaded_bytes":downloaded, "sample_interval_seconds":args.interval, "time_accuracy":"approximate sampling-bin center"}
    report.update(analyze(output, args.interval))
    report["last_operation_seconds"] = round(time.monotonic()-started,2)
    if not args.analyze_only:
        report["elapsed_seconds"] = report["last_operation_seconds"]
    (output / "report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({k:v for k,v in report.items() if k!='candidates'} | {"candidate_count":len(report['candidates'])}), flush=True)


if __name__ == "__main__":
    import sys
    try:
        main()
    except Exception as exc:
        print(json.dumps({"error":str(exc) if not isinstance(exc, requests.RequestException) else type(exc).__name__}), flush=True)
        sys.exit(1)
