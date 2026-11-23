# telegram-downloader

[![CI](https://github.com/aks1ngh/telegram-downloader/actions/workflows/ci.yml/badge.svg)](https://github.com/aks1ngh/telegram-downloader/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Telethon](https://img.shields.io/badge/built%20on-Telethon-2a9d8f)](https://github.com/LonamiWebs/Telethon)

Download any file from a Telegram chat you can already read — **private or public
channels, and groups** — voice notes, music, photos, images, PDFs, videos and
arbitrary documents. Includes chats with **Restrict saving content** enabled.
Resumable, flood-safe, and usable from a plain terminal on Windows, macOS, or Linux.

```
downloads/
  2021-04-11_203344_37_voice.ogg
  2021-04-11_203402_38_voice.ogg
  2022-01-08_184501_64_Kid - Papa Song.mp3
  2022-03-02_101122_71_photo.jpg
  2020-03-14_090855_52_report final.pdf
  index.csv          # sorted, open in Excel
  manifest.jsonl     # machine-readable, drives resume
```

## Why this exists

Telegram's "Restrict saving content" switch disables saving, forwarding, and
screenshots **inside the official clients**. It is a UI-level flag
(`noforwards`) — the files themselves are still on Telegram's servers and are
served to any authorised MTProto client. This tool logs in with your own account
and pulls them straight from the API.

That makes it the practical option for exporting an archive you have access to
but cannot navigate in the app: a private channel with no username, a dead group
whose invite link expired, or files old enough that the in-app save option never
worked well.

## Features

- **All common payloads** — `voice`, `audio`, `photo`, `image`, `pdf`, `video`, and any other `doc`.
- **Channels and groups** — public, private, invite-only; anything your account can open.
- **Survives protected chats** — no forwarding, no clipboard, no client-side restrictions involved.
- **Resumable** — a `manifest.jsonl` records each saved file; re-running the same command continues where it stopped.
- **Flood-safe** — `FloodWaitError` is caught, slept off, and the scan resumes from the last message seen.
- **Expired file references** — old media is refetched automatically and retried.
- **Resolves anything** — `@username`, invite link, `t.me/c/...` link, numeric `-100...` id, or fuzzy title.
- **Clean output** — date- and id-prefixed filenames, Windows-safe, plus `index.csv` and `failed.jsonl`.
- **No config file required** — credentials come from `config.json`, environment variables, or flags.

## Requirements

- Python 3.9 or newer
- A Telegram account that can already read the chat
- `api_id` / `api_hash` from <https://my.telegram.org> (two minutes, free)
- `pip install telethon`

## Install

```bash
git clone https://github.com/aks1ngh/telegram-downloader.git
cd telegram-downloader
python -m pip install -r requirements.txt
```

Or install it as a command with [pipx](https://pipx.pypa.io):

```bash
pipx install .
telegram-downloader --help
```

## Setup

1. Open <https://my.telegram.org>, log in with your phone number, and choose
   **API development tools**. Create an app — the name and platform do not matter.
2. Copy the credentials into `config.json`:

   ```bash
   cp config.example.json config.json
   ```

   ```json
   {
     "api_id": 1234567,
     "api_hash": "0123456789abcdef0123456789abcdef",
     "phone": "+919876543210"
   }
   ```

   `phone` is optional — leave it out and the tool asks once, then caches the
   login in a session. Environment variables work too: `TG_API_ID`, `TG_API_HASH`,
   `TG_PHONE`.

3. First run asks for the login code Telegram sends you (and your 2FA password if
   set). It is cached in `telegram_downloader.session`, so this happens once.

## Quick start

```bash
# 1. what is in there? downloads nothing
python telegram_downloader.py @channelname --dry-run

# 2. grab everything
python telegram_downloader.py @channelname --types any -o "D:\archive"

# 3. only voice notes, newest 300 messages
python telegram_downloader.py @channelname --types voice --limit 300

# 4. a private group you are a member of
python telegram_downloader.py --find "old group" --types any -o "D:\archive"
```

Windows users can double-click `download.bat` after creating `config.json`.

## What gets downloaded

| `--types` value | Payload | Saved as |
| --- | --- | --- |
| `voice` | voice notes | `<date>_<id>_voice.ogg` |
| `audio` | music / audio files | `<date>_<id>_<Performer - Title>.mp3` |
| `photo` | compressed photos | `<date>_<id>_photo.jpg` |
| `image` | images sent as files | `<date>_<id>_<name>.png` |
| `pdf` | PDF documents | `<date>_<id>_<name>.pdf` |
| `video` | video messages / files | `<date>_<id>_video.mp4` |
| `doc` | anything else | `<date>_<id>_<name>.zip` |

Default is `voice,audio,photo,pdf,image`. Use `--types any` for everything, or
combine freely: `--types voice,pdf`.

## Private or dead chats

A private channel has no `@username`, and its invite link has probably expired if
it has been quiet for years. That is fine — your account is already a member, so
the chat still exists in your dialog list. Find its id once:

```bash
python telegram_downloader.py --list-chats
```

```
              id  type     username               last msg   title
--------------------------------------------------------------------------------
 -1001234567890  channel                         2020-03-14 Family archive
 -1001987654321  channel   @somepublic            2026-11-20 Some public channel
```

Then export by id, or let the tool pick it by title:

```bash
python telegram_downloader.py -1001234567890 -o "D:\archive"
python telegram_downloader.py -1001234567890 --dry-run
python telegram_downloader.py --find "family" -o downloads
```

`https://t.me/c/1234567890/45` style links are accepted as well — the chat id is
extracted and used.

> The id in these examples (`-1001234567890`) is a sample, not a real chat.

## Usage reference

```
python telegram_downloader.py [-o DIR] [--types LIST] [--limit N] [--min-id N] [--max-id N]
                              [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--oldest-first]
                              [--delay SECONDS] [--dry-run] [--recheck]
                              [--list-chats [FILTER]] [--find TITLE]
                              [--phone +CC...] [--api-id N] [--api-hash H]
                              [--session-file PATH] [CHAT ...]
```

| Flag | Effect |
| --- | --- |
| `-o, --output DIR` | Output folder (default `downloads`). Created if missing. |
| `--types LIST` | Comma list of `voice,audio,photo,image,pdf,video,doc`, or `any`. |
| `--limit N` | Scan only the N newest messages. Fast probe before a full run. |
| `--min-id` / `--max-id` | Restrict to a message-id range. |
| `--since` / `--until` | Date window, `YYYY-MM-DD`, inclusive. |
| `--oldest-first` | Walk upward from the first message instead of newest-first. |
| `--delay S` | Pause between files. Raise it if you see flood waits. |
| `--dry-run` | Print matches, download nothing. |
| `--recheck` | Re-download files already on disk. |
| `--list-chats [FILTER]` | Print every chat with id, title, and last message date. |
| `--find TITLE` | Pick the chat whose title contains this text. |
| `--phone` | Phone number for login, e.g. `+919876543210`. |
| `--api-id` / `--api-hash` | Override `config.json` / environment. |
| `--session-file` | Where the login is cached (default `telegram_downloader.session`). |
| `--self-test` | Run offline checks and exit. |

## Output

```
downloads/
  <YYYY-MM-DD_HHMMSS>_<message_id>_<label>.<ext>
  manifest.jsonl   one JSON object per saved file
  index.csv        the same rows, sorted by date, Excel-friendly
  failed.jsonl     only created if something failed; re-run to retry
```

Filenames encode the date, the message id, and a label — `voice`, `photo`, the
document's original name, or `Performer - Title` for music.

Re-running the same command skips anything already recorded in `manifest.jsonl`,
so an interrupted download costs nothing. Delete the manifest to start over, or
pass `--recheck` to force a re-download.

## Troubleshooting

| Symptom | Symptom / fix |
| --- | --- |
| `Missing api_id / api_hash` | Create the app at <https://my.telegram.org> and fill `config.json`. |
| `No phone number or bot token provided` | Fixed in 1.2.1; on older copies pass `--phone +91...` |
| `Could not resolve chat id` | That id is not in your account — copy a real one from `--list-chats`. |
| `Invite link expired / revoked` | You must already be a member; only an admin can re-add you. |
| Login code never arrives | Telegram shows it in the app under **Settings → Devices**, not by SMS. |
| `WinError 10054`, dropped connections | Retried automatically; if it repeats use a VPN or `--delay 2`. |
| `FloodWaitError` repeatedly | Raise `--delay 3`, and run in smaller `--limit` chunks. |
| `file reference expired` | Handled automatically; leftovers land in `failed.jsonl`. |
| Photos missing | They are `photo` type — make sure `--types` includes `photo`. |
| `database is locked` on the session | Close other runs using the same session file. |

## How it works

1. Telethon performs a normal user login (MTProto), cached in a session file.
2. The chat is resolved to an entity, and history is paged with `messages.getHistory`.
3. Each message is classified locally: `DocumentAttributeAudio` (`voice` flag →
   voice note), `DocumentAttributeVideo`, MIME type (`image/*`, `application/pdf`,
   `audio/*`, `video/*`), or a plain photo.
4. `upload.getFile` streams the bytes into `<name>.part`, renamed on success.
5. Every completed file is appended to `manifest.jsonl` before the next download.

Nothing is written, edited, or deleted on the server side.

## Tests

```bash
python telegram_downloader.py --self-test     # offline classification and naming checks
python tests/test_pipeline.py                 # full pipeline against a fake client
```

The pipeline test drives the real download loop with a mock MTProto client: it
verifies voice, music, photo and PDF exports, `--types any`, manifest and CSV
output, resume behaviour, `--list-chats`, id / `t.me/c` / title resolution, the
unknown-id message, and connection retry. No network, no credentials. CI runs it
on Linux and Windows for Python 3.9 and 3.12.

## Project layout

```
telegram_downloader.py    the tool (single file, stdlib + telethon only)
tests/test_pipeline.py    mock-client pipeline test
config.example.json       credential template
download.bat              Windows double-click launcher
.github/workflows/ci.yml  CI: byte-compile, self-test, pipeline test
```

## Scope

Use it on content you have the right to download — your own chats, an archive you
were given access to, or your own media. It logs in as you and only reads chats
your account can already open; it does not bypass access control, join private
chats you were not invited to, or touch anyone else's account.

## License

MIT — see [LICENSE](LICENSE).
