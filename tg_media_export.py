#!/usr/bin/env python3
"""
Export media from a Telegram channel you can already read: voice notes, music,
photos, images, PDFs, and optionally video or any other document.

Works even when the channel has "Restrict saving content" (protected content)
enabled: that flag is enforced by official clients, not by the server, so a
normal MTProto client can still fetch the files.

Login is a normal user login (api_id / api_hash from https://my.telegram.org).
The session is cached in a file, so you only enter the code once.

Examples
--------
  # 1. see what is in there, download nothing
  python tg_media_export.py @somechannel --dry-run

  # 2. pull voice notes, music, photos and PDFs
  python tg_media_export.py @somechannel -o "D:\\archive"

  # 3. only the kid's voice notes, newest 300 messages
  python tg_media_export.py @somechannel --types voice --limit 300

  # 4. everything, including video and random documents
  python tg_media_export.py @somechannel --types any -o out

  # 5. private channel with no username and a dead invite link:
  #    list what your account can see, then use the numeric id (or --find)
  python tg_media_export.py --list-chats
  python tg_media_export.py -1001234567890 -o out
  python tg_media_export.py --find "family" -o out
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

API_URL = "https://my.telegram.org"

WIN_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *[f"COM{i}" for i in range(1, 10)],
    *[f"LPT{i}" for i in range(1, 10)],
}
INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# extension by MIME type, for documents that carry one
MIME_EXT = {
    "audio/ogg": ".ogg",
    "audio/opus": ".opus",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "audio/x-flac": ".flac",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/webm": ".webm",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "image/heic": ".heic",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
    "image/svg+xml": ".svg",
    "application/pdf": ".pdf",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-matroska": ".mkv",
}

KINDS = ("voice", "audio", "photo", "image", "pdf", "video", "doc")

try:  # telethon is the only dependency; keep the module importable without it
    from telethon import types as T
except ImportError:  # pragma: no cover
    T = None


# --------------------------------------------------------------------------- #
# naming
# --------------------------------------------------------------------------- #

def slug(text: str, limit: int = 70) -> str:
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = INVALID_CHARS.sub("_", text)
    text = re.sub(r"\s+", " ", text).strip(" ._")
    text = text[:limit].strip(" ._")
    if not text:
        return ""
    if text.split(".")[0].upper() in WIN_RESERVED:
        text = "_" + text
    return text


def guess_ext(mime: str | None, name: str | None, fallback: str = ".bin") -> str:
    if mime and mime.lower() in MIME_EXT:
        return MIME_EXT[mime.lower()]
    if name and "." in name:
        ext = "." + name.rsplit(".", 1)[1].lower()
        if 2 <= len(ext) <= 6 and ext[1:].isalnum():
            return ext
    return fallback


def largest_size(sizes) -> int | None:
    best = None
    for s in sizes or []:
        value = getattr(s, "size", None)
        if isinstance(value, int) and (best is None or value > best):
            best = value
    return best


# --------------------------------------------------------------------------- #
# payload inspection (pure, no network)
# --------------------------------------------------------------------------- #

def media_info(msg) -> dict | None:
    """Describe a message's downloadable payload, or None if it has none."""
    if T is None:
        return None
    media = getattr(msg, "media", None)
    if media is None:
        return None

    doc = getattr(media, "document", None)

    # a plain photo (compressed image) is not a document
    photo = getattr(media, "photo", None)
    if doc is None and photo is not None:
        return {
            "kind": "photo",
            "ext": ".jpg",
            "size": largest_size(getattr(photo, "sizes", None)),
            "title": None,
            "performer": None,
            "duration": None,
            "file_name": None,
        }

    if doc is None:
        return None

    mime = (getattr(doc, "mime_type", "") or "").lower()
    attrs = list(getattr(doc, "attributes", []) or [])
    by_type = {type(a): a for a in attrs}

    audio = by_type.get(T.DocumentAttributeAudio)
    video = by_type.get(T.DocumentAttributeVideo)
    fname_attr = by_type.get(T.DocumentAttributeFilename)
    file_name = getattr(fname_attr, "file_name", None) if fname_attr else None
    size = getattr(doc, "size", None)

    base = {
        "size": size,
        "title": None,
        "performer": None,
        "duration": None,
        "file_name": file_name,
    }

    if audio is not None:
        kind = "voice" if getattr(audio, "voice", False) else "audio"
        return {
            **base,
            "kind": kind,
            "title": getattr(audio, "title", None),
            "performer": getattr(audio, "performer", None),
            "duration": getattr(audio, "duration", None),
            "ext": guess_ext(mime, file_name, ".ogg" if kind == "voice" else ".bin"),
        }

    if mime.startswith("audio/"):
        return {**base, "kind": "audio", "ext": guess_ext(mime, file_name, ".bin")}

    if video is not None or mime.startswith("video/"):
        return {
            **base,
            "kind": "video",
            "duration": getattr(video, "duration", None) if video else None,
            "ext": guess_ext(mime, file_name, ".mp4"),
        }

    if mime == "application/pdf" or (file_name or "").lower().endswith(".pdf"):
        return {**base, "kind": "pdf", "ext": ".pdf"}

    if mime.startswith("image/"):
        return {**base, "kind": "image", "ext": guess_ext(mime, file_name, ".jpg")}

    return {**base, "kind": "doc", "ext": guess_ext(mime, file_name, ".bin")}


def audio_info(msg) -> dict | None:
    """Backwards-compatible alias: only audio kinds."""
    info = media_info(msg)
    if info and info["kind"] in ("voice", "audio"):
        return info
    return None


def build_name(msg, info: dict) -> str:
    when = getattr(msg, "date", None) or datetime.now(timezone.utc)
    stamp = when.strftime("%Y-%m-%d_%H%M%S")
    mid = getattr(msg, "id", 0)
    kind = info.get("kind") or "file"

    if kind in ("voice", "photo", "video"):
        label = kind
    elif kind == "audio":
        title = slug(info.get("title") or "", 60)
        performer = slug(info.get("performer") or "", 40)
        if title and performer:
            label = f"{performer} - {title}"
        else:
            label = title or (slug(Path(info.get("file_name") or "").stem, 60) or "audio")
    else:  # pdf, image, doc: prefer the original filename
        original = info.get("file_name") or ""
        label = slug(Path(original).stem, 80) or kind

    return slug(f"{stamp}_{mid}_{label}", limit=150) + info["ext"]


# --------------------------------------------------------------------------- #
# login / entity resolution
# --------------------------------------------------------------------------- #

def env_creds() -> tuple[int | None, str | None]:
    cfg = Path("config.json")
    data: dict = {}
    if cfg.exists():
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except Exception:
            data = {}
    raw_id = os.environ.get("TG_API_ID") or data.get("api_id")
    raw_hash = os.environ.get("TG_API_HASH") or data.get("api_hash")
    try:
        api_id = int(raw_id) if raw_id else None
    except (TypeError, ValueError):
        api_id = None
    return api_id, (raw_hash or None)


async def make_client(args, api_id: int, api_hash: str):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    session = StringSession(args.session_string) if args.session_string else args.session_file
    client = TelegramClient(
        session,
        api_id,
        api_hash,
        device_model="Desktop",
        system_version="Windows 10",
        app_version="1.0",
        connection_retries=8,
        retry_delay=3,
        request_retries=8,
        auto_reconnect=True,
        flood_sleep_threshold=0,  # floods are handled explicitly below
    )
    await client.start(phone=args.phone or None, password=args.password or None)
    return client


INVITE_RE = re.compile(
    r"(?:t(?:elegram)?\.me|telegram\.dog)/(?:joinchat/|\+)([A-Za-z0-9_-]{8,})", re.I
)
PRIVATE_LINK_RE = re.compile(r"(?:t(?:elegram)?\.me|telegram\.dog)/c/(\d+)(?:/\d+)?", re.I)
NUMERIC_RE = re.compile(r"^-?\d{5,}$")


async def find_by_title(client, needle: str, quiet: bool = False):
    """Locate a chat by fuzzy title; used for private channels without a username."""
    needle = needle.strip().lower()
    hits = []
    async for d in client.iter_dialogs():
        if needle and needle not in (d.title or "").lower():
            continue
        hits.append(d)
    if not hits:
        return None
    if len(hits) > 1 and not quiet:
        print(f"   {len(hits)} chats match {needle!r}:")
        for d in hits[:10]:
            print(f"     {d.id:>15}  {d.title}")
        print("   using the first one; pass its id instead to be precise")
    return hits[0].entity


async def resolve_entity(client, target: str):
    """Resolve @name, t.me link, t.me/c/ private link, invite link, or numeric id."""
    from telethon import errors
    from telethon.tl.functions.messages import CheckChatInviteRequest, ImportChatInviteRequest

    target = target.strip()

    m = PRIVATE_LINK_RE.search(target)
    if m:
        target = f"-100{m.group(1)}"

    candidates = [target]
    if NUMERIC_RE.match(target) and not target.startswith("-100"):
        candidates.append(f"-100{target.lstrip('-')}")

    for cand in candidates:
        try:
            return await client.get_entity(int(cand) if NUMERIC_RE.match(cand) else cand)
        except Exception:
            continue

    # a plain name: try it as a dialog title
    if not INVITE_RE.search(target) and not target.startswith(("@", "http", "t.me", "telegram.me")):
        found = await find_by_title(client, target)
        if found is not None:
            return found

    m = INVITE_RE.search(target) or INVITE_RE.search(f"https://t.me/{target}")
    if not m:
        raise SystemExit(
            f"Could not resolve chat: {target!r}\n"
            "Private channel without a usable invite link? Run with --list-chats to see\n"
            "every chat your account is in (id, title, last message date), then pass the id:\n"
            "  python tg_media_export.py -1001234567890 --dry-run"
        )

    invite = m.group(1)
    try:
        await client(ImportChatInviteRequest(invite))
        print("   joined via invite link")
    except errors.InviteHashExpiredError:
        raise SystemExit("Invite link expired / revoked. You must already be a member.")
    except errors.UserAlreadyParticipantError:
        pass
    except errors.InviteRequestSentError:
        raise SystemExit("Join request sent - approve it from your phone, then re-run.")
    except Exception:
        try:
            preview = await client(CheckChatInviteRequest(invite))
            if getattr(preview, "chat", None) is not None:
                return preview.chat
        except Exception:
            pass
        raise SystemExit(f"Could not join or read invite {invite!r}")

    for _ in range(5):
        try:
            return await client.get_entity(invite)
        except Exception:
            await asyncio.sleep(1)
    preview = await client(CheckChatInviteRequest(invite))
    chat = getattr(preview, "chat", None)
    if chat is None:
        raise SystemExit("Joined, but the chat could not be resolved. Re-run.")
    return chat


async def dump_dialogs(client, pattern: str) -> int:
    """Print every chat the account is in, so a private/dead channel can be found by id."""
    pattern = (pattern or "").strip().lower()
    rows = []
    async for d in client.iter_dialogs():
        title = d.title or ""
        if pattern and pattern not in title.lower():
            continue
        ent = d.entity
        uname = getattr(ent, "username", None)
        rows.append((
            d.id,
            "channel" if d.is_channel else ("group" if d.is_group else "user"),
            f"@{uname}" if uname else "",
            d.message.date.strftime("%Y-%m-%d") if d.message and d.message.date else "",
            title,
        ))
    rows.sort(key=lambda r: r[3], reverse=True)
    print(f"{'id':>16}  {'type':<8} {'username':<22} {'last msg':<10} title")
    print("-" * 78)
    for r in rows:
        print(f"{r[0]:>16}  {r[1]:<8} {r[2]:<22} {r[3]:<10} {r[4]}")
    print(f"\n{len(rows)} chats")
    return len(rows)


# --------------------------------------------------------------------------- #
# download loop
# --------------------------------------------------------------------------- #

def progress_printer(name: str, total: int | None):
    state = {"last": 0.0}

    def cb(received: int, tot: int | None):
        tot = tot or total
        now = time.monotonic()
        if now - state["last"] < 0.4 and (tot is None or received < tot):
            return
        state["last"] = now
        if not tot:
            sys.stdout.write(f"\r   {name[:40]} {received/1048576:6.1f} MB   ")
        else:
            sys.stdout.write(
                f"\r   {name[:40]} {received*100/tot:5.1f}%  "
                f"{received/1048576:6.1f}/{tot/1048576:.1f} MB"
            )
        sys.stdout.flush()

    def end():
        sys.stdout.write("\r" + " " * 92 + "\r")
        sys.stdout.flush()

    return cb, end


async def iter_history(client, entity, args):
    """Yield messages newest-first (or oldest-first) and survive flood waits."""
    from telethon import errors

    min_id = args.min_id or 0
    max_id = args.max_id or 0
    seen = 0
    while True:
        remaining = None if args.limit is None else max(args.limit - seen, 0)
        if remaining == 0:
            return
        try:
            async for msg in client.iter_messages(
                entity,
                limit=remaining,
                min_id=min_id,
                max_id=max_id,
                reverse=args.oldest_first,
                wait_time=args.wait_time,
            ):
                seen += 1
                if args.oldest_first:
                    min_id = msg.id
                else:
                    max_id = msg.id
                yield msg
            return
        except errors.FloodWaitError as e:
            wait = int(e.seconds) + 5
            print(f"   history flood wait {wait}s, resuming...")
            await asyncio.sleep(wait)


async def download_one(client, msg, info: dict, out_dir: Path, args) -> tuple[Path, bool]:
    """Download one message; returns (path, skipped)."""
    from telethon import errors

    path = out_dir / build_name(msg, info)
    if path.exists() and path.stat().st_size > 0 and not args.recheck:
        return path, True

    cb, end = progress_printer(path.name, info.get("size"))
    last_err: Exception | None = None
    for attempt in range(1, 4):
        try:
            tmp = path.with_suffix(path.suffix + ".part")
            got = await client.download_media(msg, file=str(tmp), progress_callback=cb)
            end()
            if not got:
                raise RuntimeError("server returned no data")
            Path(got).replace(path)
            return path, False
        except errors.FloodWaitError as e:
            end()
            wait = int(e.seconds) + 3
            print(f"   flood wait {wait}s, sleeping...")
            await asyncio.sleep(wait)
            last_err = e
        except errors.FileReferenceExpiredError as e:
            end()
            print("   file reference expired, refetching message...")
            msg = await client.get_messages(msg.chat_id, ids=msg.id)
            try:
                Path(str(path.with_suffix(path.suffix + ".part"))).unlink()
            except OSError:
                pass
            last_err = e
        except (errors.RPCError, OSError, RuntimeError) as e:
            end()
            last_err = e
            print(f"   attempt {attempt} failed: {e}")
            await asyncio.sleep(2 * attempt)
    raise RuntimeError(f"download failed: {last_err}")


def wants(kind: str, types_arg: str) -> bool:
    if types_arg.strip().lower() in ("any", "all"):
        return True
    return kind in {x.strip().lower() for x in types_arg.split(",") if x.strip()}


async def run(args) -> int:
    api_id, api_hash = env_creds()
    api_id = args.api_id or api_id
    api_hash = args.api_hash or api_hash
    if not api_id or not api_hash:
        print(
            "Missing api_id / api_hash.\n"
            f"  1. open {API_URL} with your phone number\n"
            "  2. API development tools -> create an app (any name)\n"
            "  3. put the two values in config.json as {\"api_id\": 123, \"api_hash\": \"...\"}\n"
            "     or set TG_API_ID / TG_API_HASH, or pass --api-id / --api-hash",
            file=sys.stderr,
        )
        return 2

    out_dir = Path(args.output).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = out_dir / "manifest.jsonl"
    failed_log = out_dir / "failed.jsonl"

    done_ids: set[int] = set()
    if manifest.exists():
        for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                done_ids.add(int(json.loads(line)["id"]))
            except Exception:
                pass

    client = await make_client(args, int(api_id), api_hash)
    stats = {"seen": 0, "found": 0, "saved": 0, "skipped": 0, "failed": 0, "bytes": 0}
    rows: list[dict] = []

    try:
        me = await client.get_me()
        print(f"logged in as {me.first_name or ''} (@{me.username or me.id})")

        if args.list_chats is not None:
            await dump_dialogs(client, args.list_chats)
            return 0

        targets: list = list(args.chats)
        if args.find:
            found = await find_by_title(client, args.find)
            if found is None:
                raise SystemExit(
                    f"No chat title matching {args.find!r}. Run --list-chats to see the real titles."
                )
            targets.append(found)
        if not targets:
            raise SystemExit("Nothing to do: pass a chat, --find TITLE, or --list-chats.")

        for target in targets:
            entity = target if not isinstance(target, str) else await resolve_entity(client, target)
            title = getattr(entity, "title", None) or getattr(entity, "username", None) or str(target)
            print(f"\n== {title} ==")
            if getattr(entity, "noforwards", False):
                print("   note: channel has 'restrict saving content'; download still works here")

            async for msg in iter_history(client, entity, args):
                stats["seen"] += 1
                if stats["seen"] % 500 == 0:
                    print(f"   scanned {stats['seen']} messages, {stats['found']} matches")

                if args.since and msg.date and msg.date < args.since:
                    continue
                if args.until and msg.date and msg.date > args.until:
                    continue

                info = media_info(msg)
                if not info or not wants(info["kind"], args.types):
                    continue
                stats["found"] += 1

                if args.dry_run:
                    dur = info.get("duration") or 0
                    size = (info.get("size") or 0) / 1048576
                    print(
                        f"   {msg.date:%Y-%m-%d %H:%M}  #{msg.id:<7} {info['kind']:<5} "
                        f"{dur:>4}s {size:6.2f} MB  {build_name(msg, info)}"
                    )
                    continue

                if msg.id in done_ids and not args.recheck:
                    stats["skipped"] += 1
                    continue

                try:
                    path, skipped = await download_one(client, msg, info, out_dir, args)
                except Exception as e:
                    stats["failed"] += 1
                    print(f"   FAILED #{msg.id}: {e}")
                    with failed_log.open("a", encoding="utf-8") as fh:
                        fh.write(json.dumps({
                            "id": msg.id,
                            "date": msg.date.isoformat() if msg.date else None,
                            "kind": info["kind"],
                            "error": str(e),
                        }, ensure_ascii=False) + "\n")
                    continue

                if skipped:
                    stats["skipped"] += 1
                    continue

                size = path.stat().st_size
                stats["saved"] += 1
                stats["bytes"] += size
                row = {
                    "id": msg.id,
                    "date": msg.date.isoformat() if msg.date else None,
                    "kind": info["kind"],
                    "duration_s": info.get("duration"),
                    "title": info.get("title"),
                    "performer": info.get("performer"),
                    "bytes": size,
                    "file": path.name,
                }
                rows.append(row)
                with manifest.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                print(f"   saved #{msg.id} [{info['kind']}] -> {path.name}")

                if args.delay:
                    await asyncio.sleep(args.delay)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        await client.disconnect()

    if rows and not args.dry_run:
        write_index(out_dir / "index.csv", manifest)
    print(
        f"\nscanned={stats['seen']} found={stats['found']} saved={stats['saved']} "
        f"skipped={stats['skipped']} failed={stats['failed']} "
        f"total={stats['bytes']/1048576:.1f} MB"
    )
    if args.dry_run:
        print("dry run: nothing downloaded")
    else:
        print(f"output: {out_dir}")
    return 0


def write_index(path: Path, manifest: Path) -> None:
    rows = []
    for line in manifest.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            rows.append(json.loads(line))
        except Exception:
            pass
    rows.sort(key=lambda r: (r.get("date") or "", r.get("id") or 0))
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["id", "date", "kind", "duration_s", "title", "performer", "bytes", "file"],
            extrasaction="ignore",
        )
        w.writeheader()
        w.writerows(rows)
    print(f"index: {path} ({len(rows)} rows)")


# --------------------------------------------------------------------------- #
# cli
# --------------------------------------------------------------------------- #

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Download media (voice, audio, photos, PDFs, files) from a Telegram channel.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("chats", nargs="*", help="@username, t.me link, or invite link")
    p.add_argument("-o", "--output", default="tg_media", help="output folder (default: tg_media)")
    p.add_argument(
        "--types",
        default="voice,audio,photo,pdf,image",
        help=f"comma list of {','.join(KINDS)}, or any (default: voice,audio,photo,pdf,image)",
    )
    p.add_argument("--limit", type=int, default=None, help="scan at most N newest messages")
    p.add_argument("--min-id", type=int, default=0, help="only messages newer than this id")
    p.add_argument("--max-id", type=int, default=0, help="only messages older than this id")
    p.add_argument("--since", type=str, default=None, help="YYYY-MM-DD lower bound")
    p.add_argument("--until", type=str, default=None, help="YYYY-MM-DD upper bound")
    p.add_argument("--oldest-first", action="store_true", help="walk from oldest message")
    p.add_argument("--delay", type=float, default=1.0, help="seconds between downloads")
    p.add_argument("--wait-time", type=float, default=0.0, help="seconds between history requests")
    p.add_argument("--dry-run", action="store_true", help="list matches, download nothing")
    p.add_argument("--recheck", action="store_true", help="re-download files already on disk")
    p.add_argument("--phone", default=None, help="phone number in +countrycode form")
    p.add_argument("--password", default=None, help="2FA password (omit to be prompted)")
    p.add_argument("--api-id", default=None, help="override TG_API_ID / config.json")
    p.add_argument("--api-hash", default=None, help="override TG_API_HASH / config.json")
    p.add_argument("--session-file", default="tg_media.session", help="session cache file")
    p.add_argument("--session-string", default=None, help="reuse a StringSession instead")
    p.add_argument("--list-chats", nargs="?", const="", default=None, metavar="FILTER",
                   help="print every chat (id, title, last message) and exit; optional title filter")
    p.add_argument("--find", default=None, metavar="TITLE",
                   help="pick the chat whose title contains this text (for private channels)")
    p.add_argument("--self-test", action="store_true", help="run offline checks and exit")
    args = p.parse_args(argv)

    if args.types.strip().lower() not in ("any", "all"):
        unknown = [x for x in args.types.split(",") if x.strip() and x.strip().lower() not in KINDS]
        if unknown:
            p.error(f"unknown --types value(s): {', '.join(unknown)}; valid: {', '.join(KINDS)}, any")
    for flag in ("since", "until"):
        raw = getattr(args, flag)
        if raw:
            try:
                setattr(args, flag, parse_date(raw))
            except ValueError:
                p.error(f"--{flag} must be YYYY-MM-DD")
    return args


def parse_date(text: str) -> datetime:
    return datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=timezone.utc)


def self_test() -> int:
    if T is None:
        print("telethon is not installed", file=sys.stderr)
        return 2
    when = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def doc(mime, attrs, size=1234, name=None):
        attributes = list(attrs)
        if name:
            attributes.append(T.DocumentAttributeFilename(file_name=name))
        return T.Document(
            id=1, access_hash=2, file_reference=b"", date=when, mime_type=mime,
            size=size, dc_id=2, attributes=attributes,
        )

    voice = SimpleNamespace(id=42, date=when, media=T.MessageMediaDocument(
        document=doc("audio/ogg", [T.DocumentAttributeAudio(duration=7, voice=True)])))
    vi = media_info(voice)
    assert vi and vi["kind"] == "voice" and vi["ext"] == ".ogg", vi
    assert build_name(voice, vi).endswith("_42_voice.ogg"), build_name(voice, vi)

    song = SimpleNamespace(id=7, date=when, media=T.MessageMediaDocument(
        document=doc("audio/mpeg", [T.DocumentAttributeAudio(
            duration=180, title="Papa Song", performer="Kid")])))
    si = media_info(song)
    assert si and si["kind"] == "audio" and si["ext"] == ".mp3", si
    assert "Kid - Papa Song" in build_name(song, si), build_name(song, si)

    pdf = SimpleNamespace(id=8, date=when, media=T.MessageMediaDocument(
        document=doc("application/pdf", [], size=555, name="report final.pdf")))
    pi = media_info(pdf)
    assert pi and pi["kind"] == "pdf" and pi["ext"] == ".pdf", pi
    assert build_name(pdf, pi).endswith("_8_report final.pdf"), build_name(pdf, pi)

    png = SimpleNamespace(id=9, date=when, media=T.MessageMediaDocument(
        document=doc("image/png", [], size=777, name="scan.png")))
    ii = media_info(png)
    assert ii and ii["kind"] == "image" and ii["ext"] == ".png", ii

    photo = SimpleNamespace(id=10, date=when, media=SimpleNamespace(
        photo=SimpleNamespace(sizes=[SimpleNamespace(size=120), SimpleNamespace(size=4096)])))
    ph = media_info(photo)
    assert ph and ph["kind"] == "photo" and ph["ext"] == ".jpg" and ph["size"] == 4096, ph
    assert build_name(photo, ph).endswith("_10_photo.jpg"), build_name(photo, ph)

    text = SimpleNamespace(id=11, date=when, media=None)
    assert media_info(text) is None

    assert wants("pdf", "voice,pdf") and not wants("video", "voice,pdf")
    assert wants("doc", "any")
    assert slug("  Papa   Mama  ") == "Papa Mama"
    assert slug("a/b:c") == "a_b_c"
    assert slug("CON") == "_CON"
    print("self-test ok")
    for m, i in ((voice, vi), (song, si), (pdf, pi), (png, ii), (photo, ph)):
        print(f"  {i['kind']:<6} -> {build_name(m, i)}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.self_test:
        return self_test()
    if not (args.chats or args.find or args.list_chats is not None):
        parse_args(["--help"])
        return 2
    if T is None:
        print("Telethon is not installed: python -m pip install telethon", file=sys.stderr)
        return 2
    if os.name == "nt":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    try:
        return asyncio.run(run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
