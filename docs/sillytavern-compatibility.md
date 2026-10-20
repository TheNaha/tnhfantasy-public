# SillyTavern Character Card Compatibility

A character card is a **portable projection** of a character, not the
character. This app's characters are larger than a card's vocabulary — they
have expression image sets, a voice binding, world membership with its
locations, a lorebook library, a gallery and chat history — and a card cannot
express any of that.

So there are two exports, and the difference is stated rather than implied:

- **The card** — what other tools read. Five formats, all SillyTavern-shaped.
- **The bundle** (`*.tnhzip`) — this app's own model of a character, with the
  card alongside so one file is both.

## Supported inputs

- Character Card V1 PNG: flat or `chara` payloads.
- Character Card V2 PNG: `chara` with base64 JSON or base64-compressed JSON.
- Character Card V3 PNG: `ccv3` takes precedence over `chara`.
- Raw JSON cards: V1, V2, or V3 objects.
- CHARX: ZIP-based `card.json` with embedded assets.
- PNG text chunks: `tEXt`, `zTXt`, and `iTXt`.
- TNHComfy bundle: a ZIP with a `manifest.json` of `kind: tnhcomfy-bundle`.

## The three buckets

Every import reports what it did with the card, in three buckets, and the
distinction between them is the point:

| Bucket | Meaning |
|---|---|
| **imported** | Mapped to a column and **in use** here. |
| **preserved** | Kept verbatim in `card_metadata` and written back on export. |
| **preserved but not executed** | Preserved, round-tripped, and **not acted on** here. |

The third bucket used to not exist, which is how a card whose behaviour
differed could still report as "fully compatible".

A card's **embedded lorebook** is imported as a project Lorebook and linked to
the character, so new chats with that character activate it automatically.
Its entry semantics are honoured: `constant: true` becomes an always-on
entry, `enabled: false` does not activate, and a `selective` entry needs a
secondary key as well as a primary one.

## What a card can and cannot carry

**Can carry:** the prose fields, the greetings, `mes_example`, the card's own
tags, the avatar, the generation settings and the scene defaults (through
`data.extensions`), and the card's embedded lorebook.

**Cannot carry:** the expression image set, the voice model binding, world
membership and its locations, the vault's lorebook library, the scene
gallery, the chat history, and the memories. `GET /api/v2/characters/{id}/export/preview`
lists them for a given character, and the export menu shows that list before
the download.

**The bundle** carries all of it, and imports back.

## Expressions

SillyTavern V3 carries expression images in `data.assets` as base64. They are
imported as real expression files (and removed from the residual, so the images
are not carried twice), and written back on export. A CHARX export carries
them as archive members and references them by path.

## Identity, and re-importing

A card exported from this app carries the character's id in
`data.extensions.tnhcomfy`. SillyTavern preserves unknown extensions, so a
card that has been through SillyTavern still knows which character it came
from, and a re-import **updates** that character instead of creating a second
one with the same name. A card from anywhere else has no such identity and is
a new character.

The import is two-phase: `POST /api/v2/characters/import/analyze` returns
what the card would do and **writes nothing**; `POST /api/v2/characters/import/commit`
does the writing, with the scope chosen.

## Export contract

PNG exports contain both:

- `chara`: V2-compatible payload.
- `ccv3`: V3 payload with preserved metadata.

JSON and CHARX exports are derived from the same preserved payload. A CHARX
carries the avatar and the expression images as archive members.

The bundle adds `manifest.json`, `character.json`, `card.json`, `card.png`,
`expressions/`, `lorebooks/`, `world.json` and `chat.jsonl`. Its sections are
opt-in and the manifest records exactly what was included.

## Macros

The prompt pipeline resolves common SillyTavern variables including
`{{char}}`, `{{user}}`, `{{persona}}`, `{{original}}`, `{{time}}`, `{{date}}`,
`{{random::...}}`, `{{pick::...}}`, `{{roll::NdX}}`, and `{{newline}}`. Unknown
variables are left intact rather than silently deleted.

## What is NOT implemented

Stated plainly, because a compatibility document that only lists what works
is not a compatibility document:

- `chara-ext-asset_:{path}` chunks — documented in earlier revisions of this
  file, never implemented.
- SillyTavern's `regex_scripts`, `tavern_helper` and `depth_prompt`
  extensions are **preserved and re-exported, but not executed here**. They
  appear in the import report's "preserved but not executed" bucket.
- A lorebook entry's `position` and `insertion_order` — preserved, but this
  app has no per-entry prompt position. (`insertion_order` is deliberately
  NOT written to the entry's `depth`: ST's is where in the prompt the entry
  lands, and `depth` is a scan depth that activation never reads.)
- Per-entry `priority` and `use_regex`.
- Importing a chat as a chat. The bundle can carry the history; a card
  cannot.
