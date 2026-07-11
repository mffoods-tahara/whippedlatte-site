import json
import logging
import time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv
import os

BASE_DIR = Path(__file__).parent
STATE_FILE = BASE_DIR / "state.json"
LOG_FILE = BASE_DIR / "post_log.txt"
GRAPH_API = "https://graph.instagram.com/v21.0"

load_dotenv(BASE_DIR / ".env")

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"image_index": -1, "caption_index": -1}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state), encoding="utf-8")


def wait_until_ready(creation_id, access_token, timeout=60):
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
        time.sleep(3)
    raise TimeoutError("メディア処理がタイムアウトしました")


def main():
    from images import BASE_URL, IMAGES
    from templates import TEMPLATES

    required = ["IG_ACCESS_TOKEN", "IG_USER_ID"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        logging.error("環境変数が未設定です: %s", ", ".join(missing))
        raise SystemExit(f".envに次のキーを設定してください: {', '.join(missing)}")

    access_token = os.getenv("IG_ACCESS_TOKEN")
    ig_user_id = os.getenv("IG_USER_ID")

    state = load_state()
    image_index = (state.get("image_index", -1) + 1) % len(IMAGES)
    caption_index = (state.get("caption_index", -1) + 1) % len(TEMPLATES)

    image_url = BASE_URL + IMAGES[image_index]
    caption = TEMPLATES[caption_index]

    try:
        create_resp = requests.post(
            f"{GRAPH_API}/{ig_user_id}/media",
            data={
                "image_url": image_url,
                "caption": caption,
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

        save_state({"image_index": image_index, "caption_index": caption_index})
        logging.info(
            "投稿成功 (image=%s, caption#%d, media_id=%s)",
            IMAGES[image_index], caption_index, media_id,
        )
        print(f"[{datetime.now()}] 投稿成功: {IMAGES[image_index]}")
    except requests.HTTPError as e:
        logging.error("投稿失敗 (image=%s): %s / %s", IMAGES[image_index], e, e.response.text)
        raise
    except Exception as e:
        logging.error("投稿失敗 (image=%s): %s", IMAGES[image_index], e)
        raise


if __name__ == "__main__":
    main()
