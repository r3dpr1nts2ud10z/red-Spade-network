import json
from datetime import datetime, timezone
from pathlib import Path


def build_channel_feed(base_dir: Path, out_file: Path) -> dict:
    out_root = base_dir / "out"
    items: list[dict] = []

    if out_root.exists():
        for item_path in sorted(out_root.glob("*/feed_item.json")):
            with open(item_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            items.append(data)

    items.sort(key=lambda x: x.get("updated_at", ""), reverse=True)

    feed = {
        "network": "Red Spade Network",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_episodes": len(items),
        "episodes": items,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(feed, f, indent=2)

    return feed


if __name__ == "__main__":
    engine_dir = Path(__file__).resolve().parent
    feed_path = engine_dir / "out" / "channel_feed.json"
    result = build_channel_feed(engine_dir, feed_path)
    print(f"Built {feed_path} with {result['total_episodes']} episode(s).")
