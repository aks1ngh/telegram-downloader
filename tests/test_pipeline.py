"""Offline pipeline test: fake MTProto client, real download loop.

Run:  python tests\test_pipeline.py
"""
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import telegram_downloader as app  # noqa: E402
from telethon import types as t  # noqa: E402

WHEN = datetime(2024, 11, 2, 18, 45, 1, tzinfo=timezone.utc)
CHAT_ID = -1001234567890

# message id -> bytes written by the fake downloader
PAYLOADS = {
    11: b"VOICE-ONE" * 100,
    12: b"VOICE-TWO" * 100,
    13: b"SONG" * 100,
    15: b"%PDF-1.4 report" * 50,
    16: b"\xff\xd8\xff\xe0photo" * 60,
    17: b"PK\x03\x04zipped" * 40,
}

ORIG_MAKE = app.make_client
ORIG_RESOLVE = app.resolve_entity


def doc(mid, mime, attrs, size, name=None):
    attributes = list(attrs)
    if name:
        attributes.append(t.DocumentAttributeFilename(file_name=name))
    return t.Document(
        id=mid, access_hash=0, file_reference=b"", date=WHEN,
        mime_type=mime, size=size, dc_id=2, attributes=attributes,
    )


def build_messages():
    def audio_doc(mid, mime, attrs, size, name=None):
        return SimpleNamespace(
            id=mid, date=WHEN, chat_id=CHAT_ID,
            media=t.MessageMediaDocument(document=doc(mid, mime, attrs, size, name)),
        )

    voice = lambda mid: audio_doc(
        mid, "audio/ogg", [t.DocumentAttributeAudio(duration=5, voice=True)], len(PAYLOADS[mid]))
    song = audio_doc(13, "audio/mpeg",
                     [t.DocumentAttributeAudio(duration=200, title="Papa Song", performer="Kid")],
                     len(PAYLOADS[13]))
    pdf = audio_doc(15, "application/pdf", [], len(PAYLOADS[15]), "report final.pdf")
    zip_doc = audio_doc(17, "application/zip", [], len(PAYLOADS[17]), "bundle.zip")
    photo = SimpleNamespace(
        id=16, date=WHEN, chat_id=CHAT_ID,
        media=SimpleNamespace(photo=SimpleNamespace(sizes=[SimpleNamespace(size=len(PAYLOADS[16]))])),
    )
    text = SimpleNamespace(id=14, date=WHEN, chat_id=CHAT_ID, media=None)
    return [text, zip_doc, photo, pdf, song, voice(12), voice(11)]  # newest-first


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
    app.resolve_entity = (lambda c, target: _coro(c.entity)) if patch_resolve else ORIG_RESOLVE
    args = app.parse_args([*argv, "--api-id", "1", "--api-hash", "x", "--delay", "0"])
    return asyncio.run(app.run(args))


def reset(tmp: Path) -> None:
    if tmp.exists():
        for p in tmp.rglob("*"):
            if p.is_file():
                p.unlink()
    tmp.mkdir(parents=True, exist_ok=True)


def test_audio_photo_pdf(tmp: Path):
    reset(tmp)
    client = FakeClient(build_messages())
    rc = run_with(client, ["@fake", "-o", str(tmp)])
    files = sorted(p.name for p in tmp.iterdir() if p.suffix not in {".jsonl", ".csv"})

    assert rc == 0, rc
    assert len(files) == 5, files          # 2 voice + song + pdf + photo, zip skipped by default
    assert any(f.endswith("_11_voice.ogg") for f in files), files
    assert any("Kid - Papa Song.mp3" in f for f in files), files
    assert any(f.endswith("_15_report final.pdf") for f in files), files
    assert any(f.endswith("_16_photo.jpg") for f in files), files
    assert not any(f.endswith(".zip") for f in files), files
    assert client.downloads == 5, client.downloads

    manifest = [json.loads(x) for x in (tmp / "manifest.jsonl").read_text().splitlines()]
    assert len(manifest) == 5, manifest
    assert {row["kind"] for row in manifest} == {"voice", "audio", "pdf", "photo"}, manifest
    assert (tmp / "index.csv").exists()

    run_with(client, ["@fake", "-o", str(tmp)])
    assert client.downloads == 5, f"re-downloaded: {client.downloads}"
    return files


def test_types_any(tmp: Path):
    reset(tmp)
    client = FakeClient(build_messages())
    run_with(client, ["@fake", "-o", str(tmp), "--types", "any"])
    names = [p.name for p in tmp.iterdir() if p.suffix == ".zip"]
    assert names, "zip should be exported with --types any"
    return names


def test_list_chats():
    client = FakeClient(build_messages())
    assert run_with(client, ["--list-chats"]) == 0


def test_resolution():
    client = FakeClient(build_messages())
    assert asyncio.run(ORIG_RESOLVE(client, "-1001234567890")) is client.entity
    assert asyncio.run(ORIG_RESOLVE(client, "https://t.me/c/1234567890/17")) is client.entity
    assert asyncio.run(ORIG_RESOLVE(client, "Dead Family Channel")) is client.entity


def test_unknown_id_message():
    client = FakeClient(build_messages())
    try:
        asyncio.run(ORIG_RESOLVE(client, "-1009999999999"))
    except SystemExit as e:
        assert "--list-chats" in str(e), e
        assert "sample" in str(e), e
    else:
        raise AssertionError("unknown id resolved")


def test_connection_retry():
    class Flaky(FakeClient):
        def __init__(self, messages):
            super().__init__(messages)
            self.calls = 0

        async def get_entity(self, target):
            self.calls += 1
            if self.calls == 1:
                raise ConnectionResetError("WinError 10054: connection forcibly closed")
            return await super().get_entity(target)

    flaky = Flaky(build_messages())
    entity = asyncio.run(ORIG_RESOLVE(flaky, "-1001234567890"))
    assert entity is flaky.entity and flaky.calls >= 2, flaky.calls


def test_bad_types():
    try:
        app.parse_args(["--types", "nonsense", "@x"])
    except SystemExit as e:
        assert e.code == 2
    else:
        raise AssertionError("invalid --types accepted")


def main() -> int:
    tmp = Path("tests/_out")
    files = test_audio_photo_pdf(tmp)
    zips = test_types_any(tmp)
    test_list_chats()
    test_resolution()
    test_unknown_id_message()
    test_connection_retry()
    test_bad_types()
    app.make_client, app.resolve_entity = ORIG_MAKE, ORIG_RESOLVE

    print("pipeline test ok: audio + photo + pdf, --types any, resume, resolution, validation")
    for f in files:
        print("  ", f)
    print("  (types=any)", zips[0])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
