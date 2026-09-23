"""Interactive server setup. Never print or package API/bot secrets."""
import getpass
import json
import os
from pathlib import Path
import sys
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from discord_sync import app
from discord_sync.briefing import DEFAULT_MODEL, DEFAULT_SOURCE, KST, OpenAISummarizer, read_key, snowflake, audience_signature


def main():
    if not app.CONFIG.exists():
        raise RuntimeError("Run 09-SETUP-DISCORD.bat first")
    config = json.loads(app.CONFIG.read_text(encoding="utf-8"))
    client = app.Client(config["token"])
    print("Daily lab briefing setup (09:00 Korea time). Ctrl+C cancels.")
    print("Only the selected lounge's text is sent to OpenAI. Files and DMs are not collected.")
    source = input(f"Lounge channel ID [{DEFAULT_SOURCE}]: ").strip() or DEFAULT_SOURCE
    if not snowflake(source):
        raise ValueError("Invalid source channel ID")
    info = app.validate(client, source)
    if info["guild_id"] != config["guild"]:
        raise ValueError("Source channel belongs to a different server")
    destination = input("Briefing channel ID (blank: create/reuse lab-briefing): ").strip()
    if not destination:
        channels = client.get(f"/guilds/{config['guild']}/channels")
        existing = next((c for c in channels if c.get("name") in ("lab-briefing", "☀️・아침-브리핑") and c.get("type") == 0), None)
        if existing:
            destination = existing["id"]
        else:
            if input("Create lab-briefing channel in this server? [y/N]: ").strip().lower() != "y":
                print("Cancelled. No scheduled job enabled.")
                return
            # Copy source overrides to avoid expanding the conversation's audience.
            destination = client.post(f"/guilds/{config['guild']}/channels", {
                "name": "lab-briefing", "type": 0, "parent_id": info.get("parent_id"),
                "permission_overwrites": info.get("permission_overwrites", []),
                "topic": "매일 오전 9시(KST) 전날 라운지 요약과 공동 일정. 개인 할 일은 DM 또는 ‘내 할 일’ 버튼에서 확인합니다. AI 정리는 원문을 확인해 주세요."})["id"]
    if not snowflake(destination) or destination == source:
        raise ValueError("Use a separate valid briefing channel")
    target = client.get(f"/channels/{destination}")
    if target.get("guild_id") != config["guild"] or target.get("type") not in (0, 5):
        raise ValueError("Destination must be a text channel in the same server")
    if sorted(target.get("permission_overwrites", []), key=lambda x: x["id"]) != sorted(info.get("permission_overwrites", []), key=lambda x: x["id"]):
        print("Source and destination permissions differ. Ensure briefing readers can access the lounge.")
        if input("Confirm intended briefing audience? [y/N]: ").strip().lower() != "y":
            return
    try:
        read_key()
        print("Existing OpenAI key found (hidden).")
    except RuntimeError:
        key = getpass.getpass("OpenAI API key (hidden; saved to .env.local): ").strip()
        if not key.startswith("sk-") or len(key) < 30 or any(c.isspace() for c in key):
            raise ValueError("Invalid key format")
        path = app.ROOT / ".env.local"
        if path.is_symlink():
            raise ValueError("Refusing symlink env file")
        lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
        lines = [line for line in lines if not line.strip().startswith("OPENAI_API_KEY=")]
        path.write_text("\n".join(lines + ["OPENAI_API_KEY=" + key]) + "\n", encoding="utf-8")
        if os.name != "nt":
            path.chmod(0o600)
    model = input(f"OpenAI model [{DEFAULT_MODEL}]: ").strip() or DEFAULT_MODEL
    if not model or len(model) > 100:
        raise ValueError("Invalid model")
    print("Checking a tiny synthetic summary; no lab conversations sent.")
    OpenAISummarizer(model)([], {})
    old_path = app.STATE / "briefing-config.json"
    old = json.loads(old_path.read_text()) if old_path.exists() else {}
    if old and (old.get("source") != source or old.get("destination") != destination):
        raise RuntimeError("Existing briefing channels differ. Back up and migrate the private ledger before changing channels.")
    first_day = old.get("start_date") or datetime.now(KST).date().isoformat()
    app.atomic_json(old_path, {"enabled": True, "source": source, "destination": destination,
                              "model": model, "start_date": first_day,
                              "audience_signature": audience_signature(info, target)})
    print("Saved. Restart 10-START-DISCORD-SYNC.bat. First report covers today, sent tomorrow at 09:00 KST.")
    print("The server and 10 window must stay running. Credentials are NOT included in GitHub updates.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Cancelled")
    except Exception as exc:
        print("Setup failed:", str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__)
        sys.exit(1)
