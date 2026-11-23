"""Offline pipeline test: fake MTProto client, real download loop.

Run:  python tests\test_offline.py
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import tg_audio_export as app  # noqa: E402
from telethon import types as t  # noqa: E402

WHEN = datetime(2024, 11, 2, 18, 45, 1, tzinfo=timezone.utc)
PAYLOADS = {  # message id -> bytes written by the fake downloader
    11: b"VOICE-ONE" * 100,
    12: b"VOICE-TWO" * 100,
    13: b"SONG" * 100,
}
CHAT_ID = -1001234567890

ORIG_MAKE = app.make_client
ORIG_RESOLVE = app.resolve_entity


def doc(mid, mime, attrs, size):
    return t.Document(
        id=mid, access_hash=0, file_reference=b"", date=WHEN,
        mime_type=mime, size=size, dc_id=2, attributes=attrs,
    )


def build_messages():
    voice = lambda mid: SimpleNamespace(
        id=mid, date=WHEN, chat_id=CHAT_ID,
        media=t.MessageMediaDocument(document=doc(
            mid, "audio/ogg", [t.DocumentAttributeAudio(duration=5, voice=True)], len(PAYLOADS[mid]))),
    )
    song = SimpleNamespace(
        id=13, date=WHEN, chat_id=CHAT_ID,
        media=t.MessageMediaDocument(document=doc(
            13, "audio/mpeg",
            [t.DocumentAttributeAudio(duration=200, title="Papa Song", performer="Kid")],
            len(PAYLOADS[13]))),
    )
    text = SimpleNamespace(id=14, date=WHEN, chat_id=CHAT_ID, media=None)
    return [text, song, voice(12), voice(11)]  # newest-first, like Telegram


class FakeClient:
    def __init__(self, messages):
        self.messages = {m.id: m for m in messages}
        self.order = [m.id for m in messages]
        self.downloads = 0
        self.entity = SimpleNamespace(
            id=CHAT_ID, title="Dead Family Channel", username=None,
            noforwards=True, date=WHEN,
        )

    async def get_me(self):
        return SimpleNamespace(first_name="Test", username="tester", id=1)

    async def disconnect(self):
        pass

    async def get_entity(self, target):
        if isinstance(target, int) and target == CHAT_ID:
            return self.entity
        raise ValueError(f"cannot resolve {target!r}")

    async def get_messages(self, chat_id, ids):
        return self.messages.get(ids)

    def iter_dialogs(self):
        entity = self.entity
        dialog = SimpleNamespace(
            id=CHAT_ID, title="Dead Family Channel", is_channel=True, is_group=False,
            entity=entity, message=SimpleNamespace(date=WHEN),
        )

        async def gen():
            yield dialog

        return gen()

    def iter_messages(self, entity, limit=None, min_id=0, max_id=0, reverse=False, wait_time=0.0):
        ids = list(reversed(self.order)) if reverse else self.order
        if max_id:
            ids = [i for i in ids if i < max_id]
        if min_id:
            ids = [i for i in ids if i > min_id]
        if limit is not None:
            ids = ids[:limit]

        async def gen():
            for i in ids:
                yield self.messages[i]

        return gen()

    async def download_media(self, msg, file, progress_callback=None):
        payload = PAYLOADS[msg.id]
        if progress_callback:
            progress_callback(len(payload) // 2, len(payload))
            progress_callback(len(payload), len(payload))
        Path(file).write_bytes(payload)
        self.downloads += 1
        return file


async def _coro(value):
    return value


def run_with(client, argv, patch_resolve=True):
    app.make_client = lambda args, api_id, api_hash: _coro(client)
    if patch_resolve:
        app.resolve_entity = lambda c, target: _coro(c.entity)
    else:
        app.resolve_entity = ORIG_RESOLVE
    args = app.parse_args([*argv, "--api-id", "1", "--api-hash", "x", "--delay", "0"])
    return asyncio.run(app.run(args))


def test_download(tmp: Path):
    client = FakeClient(build_messages())
    rc = run_with(client, ["@fake", "-o", str(tmp)])
    files = sorted(p.name for p in tmp.iterdir() if p.suffix in {".ogg", ".mp3"})

    assert rc == 0, rc
    assert len(files) == 3, files
    assert any(f.endswith("_11_voice.ogg") for f in files), files
    assert any("Kid - Papa Song.mp3" in f for f in files), files
    assert client.downloads == 3, client.downloads

    manifest = [json.loads(x) for x in (tmp / "manifest.jsonl").read_text().splitlines()]
    assert len(manifest) == 3, manifest
    assert (tmp / "index.csv").exists()

    run_with(client, ["@fake", "-o", str(tmp)])
    assert client.downloads == 3, f"re-downloaded: {client.downloads}"
    return files


def test_list_chats():
    client = FakeClient(build_messages())
    rc = run_with(client, ["--list-chats"])
    assert rc == 0


def test_resolve_numeric_id():
    client = FakeClient(build_messages())
    entity = asyncio.run(ORIG_RESOLVE(client, "-1001234567890"))
    assert entity is client.entity


def test_resolve_private_link():
    client = FakeClient(build_messages())
    entity = asyncio.run(ORIG_RESOLVE(client, "https://t.me/c/1234567890/17"))
    assert entity is client.entity


def main() -> int:
    tmp = Path("tests/_out")
    if tmp.exists():
        for p in tmp.rglob("*"):
            if p.is_file():
                p.unlink()
    tmp.mkdir(parents=True, exist_ok=True)

    files = test_download(tmp)
    test_list_chats()
    test_resolve_numeric_id()
    test_resolve_private_link()
    app.make_client, app.resolve_entity = ORIG_MAKE, ORIG_RESOLVE

    print("offline test ok: download, resume skip, --list-chats, id + t.me/c resolution")
    for f in files:
        print("  ", f)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
