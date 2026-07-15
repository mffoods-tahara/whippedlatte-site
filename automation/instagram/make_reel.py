"""リール動画の生成（GitHub Actions上でffmpegを使う前提）。

既存の投稿画像から4枚を選び、ぼかし背景+テキストオーバーレイの
縦型スライドショー(1080x1920, 約15秒, 無音トラック付き)を生成する。
生成結果は ../../instagram/reels/ に出力し、reel_meta.json に
投稿ジョブ(post_reel.py)へ渡す情報(ファイル名・キャプション)を書く。
"""
import json
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from images import IMAGES
from reel_templates import REEL_CAPTIONS, SLIDE_LINE_SETS, CTA_TEXT

BASE_DIR = Path(__file__).parent
SITE_ROOT = BASE_DIR.parent.parent
REELS_DIR = SITE_ROOT / "instagram" / "reels"
IMAGES_DIR = SITE_ROOT / "instagram"
STATE_FILE = BASE_DIR / "reel_state.json"
META_FILE = BASE_DIR / "reel_meta.json"

SLIDES_PER_REEL = 4
SLIDE_SEC = 3
KEEP_LATEST = 4  # リポジトリ肥大防止のため古いmp4は削除

# リールに使わない画像（QRコード等、動画で見せても意味がないもの）
REEL_EXCLUDE = {"line_qr.jpeg", "mascot.png"}

FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/meiryo.ttc",
]


def find_font():
    for f in FONT_CANDIDATES:
        if Path(f).exists():
            return f
    raise SystemExit("日本語フォントが見つかりません。fonts-noto-cjk をインストールしてください。")


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"image_index": -1, "caption_index": -1}


def run(cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def make_slide(image_path, text, font, out_path, textfile_dir):
    """1枚の画像から3秒のスライド動画を作る（ぼかし背景+中央配置+下部テキスト帯）。"""
    textfile = Path(textfile_dir) / (out_path.stem + ".txt")
    textfile.write_text(text, encoding="utf-8")
    vf = (
        "[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,boxblur=20:2[bg];"
        "[0:v]scale=1000:1600:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2,"
        f"drawtext=fontfile='{font}':textfile='{textfile.as_posix()}':"
        "fontcolor=white:fontsize=72:line_spacing=16:"
        "box=1:boxcolor=black@0.45:boxborderw=28:"
        "x=(w-text_w)/2:y=h-500"
    )
    run([
        "ffmpeg", "-y",
        "-loop", "1", "-t", str(SLIDE_SEC), "-i", str(image_path),
        "-f", "lavfi", "-t", str(SLIDE_SEC), "-i", "anullsrc=r=44100:cl=stereo",
        "-filter_complex", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ])


def make_cta_slide(font, out_path, textfile_dir):
    """最終スライド（単色背景+CTAテキスト）。"""
    textfile = Path(textfile_dir) / "cta.txt"
    textfile.write_text(CTA_TEXT, encoding="utf-8")
    vf = (
        f"drawtext=fontfile='{font}':textfile='{textfile.as_posix()}':"
        "fontcolor=0x7a4b63:fontsize=84:line_spacing=24:"
        "x=(w-text_w)/2:y=(h-text_h)/2"
    )
    run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-t", str(SLIDE_SEC), "-i", "color=c=0xfdf1f7:s=1080x1920:r=30",
        "-f", "lavfi", "-t", str(SLIDE_SEC), "-i", "anullsrc=r=44100:cl=stereo",
        "-vf", vf,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
        "-c:a", "aac", "-shortest",
        str(out_path),
    ])


def main():
    font = find_font()
    pool = [name for name in IMAGES if name not in REEL_EXCLUDE]

    state = load_state()
    start = state.get("image_index", -1) + 1
    picks = [pool[(start + i) % len(pool)] for i in range(SLIDES_PER_REEL)]
    caption_index = (state.get("caption_index", -1) + 1) % len(REEL_CAPTIONS)
    lines = SLIDE_LINE_SETS[caption_index % len(SLIDE_LINE_SETS)]

    REELS_DIR.mkdir(parents=True, exist_ok=True)
    out_name = f"reel_{datetime.now():%Y%m%d_%H%M}.mp4"
    out_path = REELS_DIR / out_name

    with tempfile.TemporaryDirectory() as tmp:
        segments = []
        for i, (img, text) in enumerate(zip(picks, lines)):
            seg = Path(tmp) / f"seg{i}.mp4"
            make_slide(IMAGES_DIR / img, text, font, seg, tmp)
            segments.append(seg)
        cta = Path(tmp) / "cta.mp4"
        make_cta_slide(font, cta, tmp)
        segments.append(cta)

        concat_list = Path(tmp) / "list.txt"
        concat_list.write_text(
            "".join(f"file '{s.as_posix()}'\n" for s in segments), encoding="utf-8"
        )
        run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c", "copy", "-movflags", "+faststart", str(out_path),
        ])

    # 古いmp4を整理（最新KEEP_LATEST本だけ残す）
    reels = sorted(REELS_DIR.glob("reel_*.mp4"))
    for old in reels[:-KEEP_LATEST]:
        old.unlink()

    # 状態とメタ情報を保存（stateのcommitはワークフロー側で行う）
    STATE_FILE.write_text(
        json.dumps({
            "image_index": (start + SLIDES_PER_REEL - 1) % len(pool),
            "caption_index": caption_index,
        }),
        encoding="utf-8",
    )
    META_FILE.write_text(
        json.dumps({"video": out_name, "caption_index": caption_index},
                   ensure_ascii=False),
        encoding="utf-8",
    )
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"生成完了: {out_path.name} ({size_mb:.1f}MB) images={picks} caption#{caption_index}")


if __name__ == "__main__":
    main()
