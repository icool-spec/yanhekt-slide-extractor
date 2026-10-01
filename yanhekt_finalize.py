"""Build the final ordered image set after reviewing candidate thumbnails."""
import argparse
import html
import json
from pathlib import Path
import shutil
import zipfile

from PIL import Image, ImageDraw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="output-course")
    parser.add_argument("--title", default="课件截图", help="Title shown in the gallery")
    parser.add_argument("--exclude", default="", help="Reviewed candidate IDs: e.g. 3,5,8")
    args = parser.parse_args()
    output = Path(args.output).resolve()
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    exclusions = {int(item) for item in args.exclude.split(",") if item.strip()}
    available = {item["id"] for item in report["candidates"]}
    if exclusions - available:
        raise ValueError("Unknown candidate ID")
    directory = output / "slides"
    directory.mkdir(exist_ok=True)
    if any(directory.iterdir()):
        raise ValueError("Final slide folder already contains files; choose a new run")
    final, rejected = [], []
    for item in report["candidates"]:
        if item["id"] in exclusions:
            rejected.append(item | {"reason":"Excluded after visual review: non-slide or transition"})
            continue
        number = len(final)+1
        seconds = item["time_seconds"]
        name = f"slide_{number:03d}_{int(seconds)//60:02d}m{int(seconds)%60:02d}s.jpg"
        shutil.copyfile(output/item["file"], directory/name)
        final.append(item | {"number":number,"file":"slides/"+name})
    report["final_slides"] = final
    report["excluded_after_review"] = rejected
    report["review_note"] = "User-reviewed exclusions; general-purpose automatic slide classification is not implemented. At least two stable samples are required; brief pages may be missed."
    (output/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    cards = ''.join(f'<a href="{html.escape(item["file"])}"><figure><img loading="lazy" src="{html.escape(item["file"])}"><figcaption>第 {item["number"]} 张 · 约 {int(item["time_seconds"])//60:02d}:{int(item["time_seconds"])%60:02d}</figcaption></figure></a>' for item in final)
    title = html.escape(args.title)
    interval = report["sample_interval_seconds"]
    (output/"index.html").write_text(f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>{title}</title><style>body{{font:16px sans-serif;background:#eef2f5;padding:24px;color:#24344b}}main{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}a{{color:inherit;text-decoration:none}}figure{{margin:0;background:white;border-radius:8px;overflow:hidden}}img{{width:100%}}figcaption{{padding:12px}}</style><h1>{title}</h1><p>{len(final)} 张 · 保留采样原尺寸</p><p>点击查看原图。每 {interval:g} 秒采样，极短页面可能遗漏；非课件排除范围由提供的候选编号决定。</p><main>'+cards+'</main></html>',encoding="utf-8")
    for page in range((len(final)+23)//24):
        items=final[page*24:(page+1)*24]
        sheet=Image.new("RGB",(1280,((len(items)+3)//4)*205),"#eef2f5")
        draw=ImageDraw.Draw(sheet)
        for cell,item in enumerate(items):
            x,y=(cell%4)*320,(cell//4)*205
            with Image.open(output/item["file"]) as image:
                image.thumbnail((316,178))
                sheet.paste(image,(x+2,y+25))
            seconds=int(item["time_seconds"])
            draw.text((x+5,y+7),f'{item["number"]:03d}  {seconds//60:02d}:{seconds%60:02d}',fill="black")
        sheet.save(output/f"slides_preview_{page+1:02d}.jpg",quality=92)
    with zipfile.ZipFile(output/"slides.zip","w",zipfile.ZIP_DEFLATED) as archive:
        archive.write(output/"index.html","index.html")
        for item in final:
            archive.write(output/item["file"],item["file"])
    print(json.dumps({"slides":len(final),"review_excluded":len(rejected),"zip_bytes":(output/"slides.zip").stat().st_size}))


if __name__ == "__main__":
    main()
