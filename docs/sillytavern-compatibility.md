# SillyTavern Character Card Compatibility

TNHComfy treats character cards as a portable interchange format, not as a one-time text import.

## Supported inputs

- Character Card V1 PNG: flat or `chara` payloads.
- Character Card V2 PNG: `chara` with base64 JSON or base64-compressed JSON.
- Character Card V3 PNG: `ccv3` takes precedence over `chara`.
- Raw JSON cards: V1, V2, or V3 objects.
- CHARX: ZIP-based `card.json` with embedded assets when present.
- PNG text chunks: `tEXt`, `zTXt`, and `iTXt`.
- Legacy embedded assets: `chara-ext-asset_:{path}` chunks.

## Preservation contract

Known fields map to first-class Character columns. Unknown root fields, data fields, extensions, assets, regex scripts, group greetings, multilingual metadata, and version-specific fields are retained in `card_metadata` and emitted again on export.

Embedded `character_book` objects are imported as project Lorebooks and linked to the character. New chats created with that character activate the embedded lorebook automatically.

## Export contract

PNG exports contain both:

- `chara`: V2-compatible payload.
- `ccv3`: V3 payload with preserved metadata and assets.

JSON and CHARX exports are derived from the same preserved payload. Existing avatar and expression assets are included where the target format supports them.

## Macros

The prompt pipeline resolves common SillyTavern variables including `{{char}}`, `{{user}}`, `{{persona}}`, `{{original}}`, `{{time}}`, `{{date}}`, `{{random::...}}`, `{{pick::...}}`, `{{roll::NdX}}`, and `{{newline}}`. Unknown variables are left intact rather than silently deleted.
