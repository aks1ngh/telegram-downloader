# tg-audio-export

[![CI](https://github.com/aks1ngh/tg-audio-export/actions/workflows/ci.yml/badge.svg)](https://github.com/aks1ngh/tg-audio-export/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Telethon](https://img.shields.io/badge/built%20on-Telethon-2a9d8f)](https://github.com/LonamiWebs/Telethon)

Download every voice note and audio file from a Telegram channel, including
channels with **Restrict saving content** enabled. Resumable, flood-safe, and
usable from a plain terminal on Windows, macOS, or Linux.

```
tg-audio-export/
  2021-04-11_203344_37_voice.ogg
  2021-04-11_203402_38_voice.ogg
  2022-01-08_184501_64_Kid - Papa Song.mp3
  index.csv          # sorted, open in Excel
  manifest.jsonl     # machine-readable, drives resume
```

## Why this exists

Telegram's "Restrict saving content" switch disables saving, forwarding, and
screenshots **inside the official clients**. It is a UI-level flag
(`noforwards`) — the media itself is still on Telegram's servers and is served
to any authorised MTProto client. This tool logs in with your own account and
pulls the files straight from the API.

That makes it the practical option for exporting an archive you have access to
but cannot navigate in the app: a private channel with no username, an expired
invite link, or media old enough that the in-app save option never worked well.

## Features

- **Audio only** — voice notes, music, and audio documents; everything else is skipped.
- **Survives protected channels** — no forwarding, no clipboard, no client-side restrictions involved.
- **Resumable** — a `manifest.jsonl` records each saved file; re-running the same command continues where it stopped.
- **Flood-safe** — `FloodWaitError` is caught, slept off, and the scan resumes from the last message seen.
- **Expired file references** — old media is refetched automatically and retried.
- **Private channel support** — resolve by `@username`, invite link, `t.me/c/...` link, numeric `-100...` id, or fuzzy title.
- **Clean output** — date- and id-prefixed filenames, Windows-safe, plus `index.csv` and `failed.jsonl`.
- **Zero config files required** — credentials come from `config.json`, environment variables, or flags.

## Requirements

- Python 3.9 or newer
- A Telegram account that can already read the channel
- `api_id` / `api_hash` from <https://my.telegram.org> (two minutes, free)
- `pip install telethon`

## Install

```bash
git clone https://github.com/aks1ngh/tg-audio-export.git
cd tg-audio-export
python -m pip install -r requirements.txt
```

Or install it as a command with [pipx](https://pipx.pypa.io):

```bash
pipx install .
tg-audio-export --help
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
     "api_hash": "0123456789abcdef0123456789abcdef"
   }
   ```

   Environment variables work too: `TG_API_ID`, `TG_API_HASH`.

3. First run asks for the login code Telegram sends you (and your 2FA password if
   set). It is cached in `tg_audio.session`, so this happens once.

## Quick start

```bash
# 1. what is in there? downloads nothing
python tg_audio_export.py @channelname --dry-run

# 2. pull everything
python tg_audio_export.py @channelname -o "D:\family-audio"

# 3. only voice notes, newest 300 messages
python tg_audio_export.py @channelname --types voice --limit 300
```

Windows users can double-click `download-audio.bat` after creating `config.json`.

## Private or dead channels

A private channel has no `@username`, and its invite link has probably expired if
it has been quiet for years. That is fine — your account is already a member, so
the chat still exists in your dialog list. Find its id once:

```bash
python tg_audio_export.py --list-chats
```

```
              id  type     username               last msg   title
--------------------------------------------------------------------------------
 -1001234567890  channel                         2020-03-14 Family archive
 -1001987654321  channel   @somepublic            2026-11-20 Some public channel
```

Then export by id, or let the tool pick it by title:

```bash
python tg_audio_export.py -1001234567890 -o "D:\family-audio"
python tg_audio_export.py -1001234567890 --dry-run
python tg_audio_export.py --find "family" -o out
```

`https://t.me/c/1234567890/45` style links are accepted as well — the channel id is
extracted and used.

## Usage reference

```
python tg_audio_export.py [-o DIR] [--types LIST] [--limit N] [--min-id N] [--max-id N]
                          [--since YYYY-MM-DD] [--until YYYY-MM-DD] [--oldest-first]
                          [--delay SECONDS] [--dry-run] [--recheck]
                          [--list-chats [FILTER]] [--find TITLE]
                          [--phone +CC...] [--api-id N] [--api-hash H]
                          [--session-file PATH] [CHAT ...]
```

| Flag | Effect |
| --- | --- |
| `-o, --output DIR` | Output folder (default `tg_audio`). Created if missing. |
| `--types voice,audio` | Which payloads to keep. `any` also takes non-audio documents. |
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
| `--session-file` | Where the login is cached (default `tg_audio.session`). |
| `--self-test` | Run offline checks and exit. |

## Output

```
out/
  <YYYY-MM-DD_HHMMSS>_<message_id>_<label>.<ext>
  manifest.jsonl   one JSON object per saved file
  index.csv        the same rows, sorted by date, Excel-friendly
  failed.jsonl     only created if something failed; re-run to retry
```

Filenames encode the date, the message id, and — for music — `Performer - Title`.
Voice notes become `<date>_<id>_voice.ogg`.

Re-running the same command skips anything already recorded in `manifest.jsonl`,
so an interrupted export costs nothing. Delete the manifest to start over, or
pass `--recheck` to force a re-download.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| `Missing api_id / api_hash` | Create the app at <https://my.telegram.org> and fill `config.json`. |
| `Could not resolve chat` | Use `--list-chats` and pass the numeric `-100...` id. |
| `Invite link expired / revoked` | You must already be a member; only a channel admin can re-add you. |
| Login code never arrives | Telegram shows it in the app under **Settings → Devices**, not by SMS. |
| `FloodWaitError` repeatedly | Raise `--delay 3`, and run in smaller `--limit` chunks. |
| `file reference expired` | Handled automatically; if a file still fails it is listed in `failed.jsonl`. |
| Nothing found | Channel may hold no audio, or the messages are older than your `--since`. |
| `database is locked` on the session | Close other runs using the same `tg_audio.session`. |

## How it works

1. Telethon performs a normal user login (MTProto), cached in a session file.
2. The channel is resolved to an entity, and history is paged with `messages.getHistory`.
3. Each message is inspected locally: a `DocumentAttributeAudio` or an `audio/*` MIME
   type marks it as a candidate. Voice notes and music are told apart by the
   `voice` flag.
4. `upload.getFile` streams the bytes into `<name>.part`, which is renamed on success.
5. Every completed file is appended to `manifest.jsonl` before the next download starts.

Nothing is written, edited, or deleted on the server side.

## Tests

```bash
python tg_audio_export.py --self-test     # offline naming/filter checks
python tests/test_offline.py              # full pipeline against a fake client
```

The pipeline test drives the real download loop with a mock MTProto client: it
verifies file naming, manifest and CSV output, resume behaviour, `--list-chats`,
and id / `t.me/c` resolution. No network, no credentials. CI runs it on Linux and
Windows for Python 3.9–3.12.

## Project layout

```
tg_audio_export.py        the tool (single file, stdlib + telethon only)
tests/test_offline.py     mock-client pipeline test
config.example.json       credential template
download-audio.bat        Windows double-click launcher
.github/workflows/ci.yml  lint-free CI: self-test + pipeline test
```

## Scope

Use it on content you have the right to export — your own channel, an archive you
were given access to, or your own media. It logs in as you and only reads chats
your account can already open; it does not bypass access control, join private
channels you were not invited to, or touch anyone else's account.

## License

MIT — see [LICENSE](LICENSE).
