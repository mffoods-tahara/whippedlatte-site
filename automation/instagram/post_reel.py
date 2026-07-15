"""生成済みリール動画をInstagram Graph APIで投稿する。

前提: make_reel.py が生成した動画が commit & push され、
GitHub Pages (whippedlatte.jp) で公開済みであること。
このスクリプトはURLが200を返すまで待ってから投稿する。
"""
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

from reel_templates import REEL_CAPTIONS

BASE_DIR = Path(__file__).parent
META_FILE = BASE_DIR / "reel_meta.json"
LOG_FILE = BASE_DIR / "post_log.txt"
GRAPH_API = "https://graph.instagram.com/v21.0"
REELS_BASE_URL = "https://whippedlatte.jp/instagram/reels/"

load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def wait_for_url(url, timeout=600, interval=15):
    """GitHub Pagesのデプロイ完了(=動画URLが200を返す)まで待つ。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.head(url, timeout=30)
            if resp.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(interval)
    raise TimeoutError(f"動画URLが公開されませんでした: {url}")


def wait_until_ready(creation_id, access_token, timeout=300):
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = requests.get(
            f"{GRAPH_API}/{creation_id}",
            params={"fields": "status_code", "access_token": access_token},
        )
        resp.raise_for_status()
        status = resp.json().get("status_code")
        if status == "FINISHED":
            return
        if status == "ERROR":
            raise RuntimeError(f"メディア処理が失敗しました: {resp.json()}")
        time.sleep(10)
    raise TimeoutError("メディア処理がタイムアウトしました")


def main():
    required = ["IG_ACCESS_TOKEN", "IG_USER_ID"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        logging.error("環境変数が未設定です: %s", ", ".join(missing))
        raise SystemExit(f"次のキーを設定してください: {', '.join(missing)}")

    access_token = os.getenv("IG_ACCESS_TOKEN")
    ig_user_id = os.getenv("IG_USER_ID")

    meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    video_url = REELS_BASE_URL + meta["video"]
    caption = REEL_CAPTIONS[meta["caption_index"] % len(REEL_CAPTIONS)]

    try:
        wait_for_url(video_url)

        create_resp = requests.post(
            f"{GRAPH_API}/{ig_user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
                "share_to_feed": "true",
                "access_token": access_token,
            },
        )
        create_resp.raise_for_status()
        creation_id = create_resp.json()["id"]

        wait_until_ready(creation_id, access_token)

        publish_resp = requests.post(
            f"{GRAPH_API}/{ig_user_id}/media_publish",
            data={"creation_id": creation_id, "access_token": access_token},
        )
        publish_resp.raise_for_status()
        media_id = publish_resp.json().get("id")

        logging.info(
            "リール投稿成功 (video=%s, caption#%d, media_id=%s)",
            meta["video"], meta["caption_index"], media_id,
        )
        print(f"[{datetime.now()}] リール投稿成功: {meta['video']}")
    except requests.HTTPError as e:
        logging.error("リール投稿失敗 (video=%s): %s / %s", meta["video"], e, e.response.text)
        raise
    except Exception as e:
        logging.error("リール投稿失敗 (video=%s): %s", meta["video"], e)
        raise


if __name__ == "__main__":
    main()
