# Character Interchange Plan — making card import/export streamlined

**Scope:** the SillyTavern character-card import/export path, in a project whose character model is far larger than a card.

**Status:** implementation-ready

---

## 1. Context

The card codec (`backend_v2/core/character_cards.py`, 731 lines) is good work: PNG chunk decoding across `tEXt`/`zTXt`/`iTXt` keyed by keyword, raw/base64/base64+zlib/CBOR payload decoding, V1/V2/V3 plus legacy spec aliases, CHARX, and a residual-blob design that makes import → export **byte-lossless** even for fields we have no column for. It is backed by ~1,900 lines of backend card tests.

The problem is not the codec. It is that **the project is bigger than the card**, and nothing in the product says so.

A TNHComfy character carries, beyond what a card can express:

| Beyond the card | Where it lives |
|---|---|
| World membership | `Character.world_id` → `World` |
| The vault's own lorebook library | `Character.lorebook_ids` |
| Locations | `Location` rows (`world_id`) — there is no `Character.location_ids` |
| Expression image sets | `Character.expressions` (emotion → avatar path), `expressions_lora` |
| Voice model | `Character.voice_model_id` → `VoiceModel`, `voice_profile` |
| Image-generation settings | `Character.checkpoint`, `lora`, `visual_tags`, `lora_triggers` |
| Scene defaults | `Character.default_time`, `default_location` |
| Gallery | `Collection.character_id` |
| Chat history | `Chat.character_id` → `Message` |
| Memories | `CharacterMemory.character_id` |

A SillyTavern card can express **none** of the first nine. So today:

- **Export** offers five formats (`default`/`v2`/`v3`/`json`/`charx`) and **all five are SillyTavern-shaped**. A character with expressions, a voice, a world and a gallery exports as a card that silently has none of them.
- **Import** has two unrelated entry points: a quick `POST /characters/import` on the Characters page, and the World Architect (`analyze-card` → `commit`) on another page, with different shapes and different guarantees. Neither merges into an existing character; both insert a duplicate on re-import.
- The **import report always says everything is fine.** `lost_fields` is hardcoded `[]` (`api/routes/world_vault/characters.py:196`), so the modal prints *"Fully compatible. All reported card data was imported."* while the report itself is only group-level with counts.

Measured on a realistic ST V2 card (description, personality, scenario, first_mes, mes_example, tags, `extensions.depth_prompt`, a 2-entry `character_book` with `constant: true`):

```
report.lost_fields    : []          <- always
report.warnings       : []          <- always
report.preserved      : [('data.extensions','1 entry'), ('data.character_book','2 entries')]
character.visual_tags : ['fantasy','elf']   <- ST character tags, in the IMAGE tag column
character.world_id    : None
character.lorebook_ids: []
character.expressions : None
lorebook entry 1      : KEY-GATED (needs a keyword)   <- the card said constant:true
export                : expressions exported? False
```

And a card carrying `extensions.voice_model_id` for a voice model this vault does not have **crashes the import with a 500**:

```
IntegrityError: FOREIGN KEY constraint failed
INSERT INTO characters (... 'does-not-exist' ...)
```

---

## 2. The shape of the fix

Three ideas do most of the work.

### 2.1 Two export kinds, and a manifest that says which

- **The card** — the SillyTavern-shaped projection. What other tools read. Unchanged in behaviour; it just stops pretending to be the whole character.
- **The bundle** (`*.tnhzip`) — the native export. Carries the fields, the expressions, the voice binding, the generation settings, the world and its locations, the lorebook library, and optionally the chat history.

Every export carries a manifest, so import always knows what it is reading:

```json
{ "kind": "tnhcomfy-bundle", "version": 1, "exported_at": "...",
  "character_id": "...", "app_version": "...", "includes": ["expressions", "world", "voice"] }
```

An ST card has no manifest, and that is how import tells the two apart.

### 2.2 A stable identity, so re-import merges instead of duplicating

This is the keystone, and it costs one JSON key.

TNHComfy writes `extensions.tnhcomvy = {"character_id": "..."}` into the card it exports. SillyTavern **preserves unknown extensions**, and so does this app's residual blob. So:

- A card exported from TNHComyu, edited in SillyTavern, and re-imported here is **recognised as the same character** — even though the card itself has no id.
- A foreign ST card has no such extension → treated as new, and offered "create new" or "merge into <existing>".

The bundle's manifest carries the same `character_id`, so both paths match the same way.

### 2.3 The report stops lying, and says *why*

Three buckets instead of one:

- **imported** — mapped to a column and **functional** here.
- **preserved** — kept in `card_metadata` and round-tripped, but **not executed** here, with the reason. (Today this bucket is missing entirely, which is why the report can claim "fully compatible".)
- **not portable** — exists in the vault, and a card **cannot** express it. This bucket is for **export**, not import: "this character has 6 expressions, a voice model, a world with 3 locations and 12 chats; a SillyTavern card cannot carry those."

The codec already knows every one of these facts. The report just isn't telling them.

---

## 3. Phases

### Phase 1 — Make the import honest and non-crashing

The bugs. Small, local, and they are what a user importing a real card hits first.

**1.1 — Stop the 500 on a dangling `voice_model_id`.**
`core/character_cards.py:435` writes `extensions.voice_model_id` straight into `Character.voice_model_id`, which is a foreign key (`core/entities.py:1209`). If the voice model is not in this vault, the INSERT fails and the whole import is lost.

- Validate the id against `VoiceModel` before assigning; drop it if it does not exist, and **report it** as "not imported: no such voice model".
- Same class of check for any other card-supplied id that lands in a foreign key (`checkpoint`, `lora` are plain columns, so they are safe; `voice_model_id` is the only FK).
- `backend_v2/api/routes/world_vault/characters.py:327` — `Character(**{...})` then `session.add`. Wrap the write so a constraint failure becomes a `ValidationError` with a readable message rather than a 500.

**1.2 — Honour the SillyTavern lorebook entry semantics that have no equivalent today.**

`core/character_cards.py:707-718` maps 9 of ~18 entry fields. What is lost, and what to do:

| ST field | Today | Plan |
|---|---|---|
| `constant` | **dropped** | Map to a keyless entry. TNHComfy's always-on test is *keyless* (`services/rag_pipeline.py:337`, `services/context_builder.py:568`), so an ST `constant: true` entry **with** keys must become keyless to stay always-on. |
| `enabled` | **dropped** | A disabled entry must not activate. `LorebookEntry` has no such column → **migration 109**: `lorebook_entries.enabled BOOLEAN NOT NULL DEFAULT TRUE`, and the activation query must respect it. |
| `selective` | **dropped** | With `secondary_keys` dropped, selective matching cannot work. Either map both, or report them as "preserved but not executed". Mapping both is better: store `secondary_keys` on the entry and honour `selective` + `selective_logic` in the activation query. |
| `secondary_keys` | **dropped** | Store on the entry; used with `selective`. |
| `position` (`before_char`/`after_char`) | **dropped** | The vault has no equivalent. Report as preserved-but-not-executed, and keep the value in `card_metadata` (it already round-trips). |
| `insertion_order` | mapped to `depth` | **Wrong concept.** `depth` is a scan depth and is **never read at activation** (verified: no read of `.depth` for lorebook entries in `rag_pipeline.py` / `context_builder.py`). Stop writing it to `depth`; keep it in `card_metadata` and report it. |
| `priority`, `use_regex`, `group`, `id` | dropped | Kept in `card_metadata` (they already round-trip). Reported as preserved. |

**1.3 — Stop `data.tags` landing in the image-tag column.**
`core/character_cards.py:398-405` maps ST's character-metadata `tags` (`["fantasy","elf"]`) into `Character.visual_tags`, which is the **image-generation** tag list. The character then pollutes its own image prompts.

- Keep ST `data.tags` in `card_metadata` only (it already round-trips), and stop writing them to `visual_tags`.
- `visual_tags` is a TNHComy concept; it belongs in `extensions.visual_tags` (which the codec already supports). So: **the ST `tags` field and the TNHComy `visual_tags` are different things and must stop sharing a column.**

**1.4 — Stop destroying `extensions.suggested_persona`.**
It is listed in `_MAPPED_EXTENSION_KEYS` (`core/character_cards.py:100`) so it is excluded from the residual blob, but the column read at `:424` only looks at `data.suggested_persona`. The extension value is therefore read from nowhere and preserved nowhere. Read it from `extensions` too, and keep the column write consistent with the export at `:570-571`.

**1.5 — Fix the report.**
`api/routes/world_vault/characters.py:155-200`:
- `lost_fields` must not be hardcoded `[]`. Populate it from the codec: the fields the card carried that the vault could neither map nor preserve.
- Add a **`preserved_but_inert`** bucket: the preserved groups, each with the **specific** keys and the reason they are not executed. Today the report says *"data.extensions — 3 entries"*; it should say *"data.extensions — depth_prompt (preserved, not executed)"*.
- `source_format` (`:365`) says `"json"` for a CHARX import. Use `"charx"`.
- The route's rejection message (`:303`) omits `.charx` while `CARD_FILE_SUFFIXES` (`:47`) accepts it.

**1.6 — The avatar should not carry the card payload.**
`core/character_cards.py:521-522` returns the **whole card PNG** as the avatar, so `avatar.png` (`:339-344`) is a multi-hundred-KB file that still contains the `chara` text chunk. Strip the textual chunks when storing the avatar, and re-add them on export (the export path already writes a fresh `PngInfo`, so the re-export is correct — it is the *stored* file that is wrong).

**1.7 — The frontend's report must consume the new buckets.**
`frontend_v2/src/api/characterCards.js:166-199` computes `lossless: lost.length === 0 && warnings.length === 0` and `CharacterCardImportReport.jsx:112-114` prints *"Fully compatible. All reported card data was imported."* — that sentence must go. It should read from the buckets: *"Imported. 2 features were preserved but are not executed here."*

### Phase 2 — Expressions, in both directions

`grep -c expression core/character_cards.py` → **0**. The feature is the most visible loss for anyone who uses it.

**2.1 — Import.**
ST V3 carries expression images in `data.assets` as entries with `type: "expression"` and a `name` (the emotion). The codec already preserves `data.assets` **verbatim**; it just never turns them into images.

- Parse `data.assets` entries of `type == "expression"` into `Character.expressions` (emotion name → avatar path), writing the image bytes under the character's avatar directory.
- ST expression assets are usually embedded as base64 in the asset entry, or referenced by a filename in a CHARX archive. Handle both: base64 inline, and `charx` archive members.

**2.2 — Export.**
`build_card_payload` (`core/character_cards.py:539-626`) must write the expressions back:
- As `data.assets` entries of `type: "expression"` (V3), each with the emotion name and the image as a data URI, so a SillyTavern client that understands V3 shows them.
- And in the `chara` chunk, the V2 shape has no expression concept — so a V2 export should say so rather than pretend.

**2.3 — CHARX.**
`encode_charx_card` (`:670-678`) writes only `card.json` and the avatar. It should write the expression images as archive members (`assets/expressions/<name>.png`) and reference them from `data.assets` — that is what CHARX is for.

### Phase 3 — A native bundle export

`GET /characters/{id}/export` currently offers five ST formats. Add a sixth.

**3.1 — The bundle format.**

```
character.tnhzip
  manifest.json          {kind, version, exported_at, character_id, app_version, includes[]}
  character.json         every Character column, plus the card_metadata residual
  card.png               the avatar, with the card chunks (so it doubles as an ST card)
  card.json              the SillyTavern card, exactly as the ST export would produce
  expressions/<emotion>.png
  lorebooks/<name>.json  the character's lorebook library
  world.json             {world, locations[]} — only when the user includes the world
  chat.jsonl             optional: the chat history
```

**3.2 — The export menu.** `frontend_v2/src/components/characters/CharacterCardExportMenu.jsx` gains a "TNHComfy bundle" entry with checkboxes for what to include (expressions, voice binding, generation settings, world, lorebooks, chat history). The ST entries stay exactly as they are.

**3.3 — The export must state what it dropped.** Every export response carries the same three buckets as the import report, so *"exported as a SillyTavern card; 6 expressions, 1 voice model, 1 world and 12 chats could not be carried"* is visible in the UI, not inferred from silence.

### Phase 4 — One import entry point, with a preview

Today the two import paths are on two pages and have different shapes. Converge them.

**4.1 — Two-phase import.** The plain import writes immediately. Give it the shape the World Architect already has:

- `POST /characters/import/analyze` → parses, validates, matches, and returns a **preview**: the parsed fields, what would be created, whether it matches an existing character, and what the world scope would add. **Writes nothing.**
- `POST /characters/import/commit` → writes, given the chosen scope and the chosen match.

The World Architect's `analyze-card` / `commit` (`api/routes/world_vault/onboarding.py:174` and `:463`) keep their routes, but the *card* path should reuse the same blueprint machinery (`services/world_onboarding_service.py:_synthesize_card_blueprint`, `:616`) rather than a parallel implementation. One parser, one preview, one commit.

**4.2 — The scope choice.** One button, two outcomes:
- **Just the character** — fast; a character with no world. (Today: "Import Card".)
- **Into a world** — the World Architect's depth: world + locations + lorebook + members, with the optional Vision and enrichment passes. (Today: "World Architect", on another page.)

**4.3 — Merge, not duplicate.** With the identity from §2.2, the preview says *"this card is character 'Ilse of the Bridge' (updated 3 days ago) — update it, or create a new one?"*. The commit applies the update. Today's behaviour is an unconditional INSERT, so re-importing an updated card silently duplicates the character.

**4.4 — Bulk.** The file input has no `multiple` (`frontend_v2/src/pages/Characters.jsx:1021-1028`); `handleImportCard` reads `files?.[0]`. Accept many files (or a directory), show a queue, and report per card. Re-use the same analyze/commit endpoints per file.

### Phase 5 — The "not portable" list, made concrete

A card export should be able to say what it could not carry. This needs one source of truth:

`backend_v2/core/character_cards.py` gains a function that, given a Character and its relations, returns the not-portable set: expressions and expression LoRAs, the voice model binding, the world and its locations, the lorebook library, the generation settings (`checkpoint`/`lora` are in `extensions` today, so they DO round-trip — the others do not), the gallery, the chats, the memories.

`frontend_v2/src/components/characters/CharacterCardExportMenu.jsx` shows it as a checklist before the download: *"6 expressions, 1 voice model, 1 world (3 locations), 12 chats are not carried by a SillyTavern card."* with a pointer to the bundle export.

### Phase 6 — The "bigger than SillyTavern" surface, made coherent

The point of the bundle is that TNHComy characters are not cards. The UI should stop treating "import card" as the only way in and "export card" as the only way out.

- The Characters page gets an **"Export" that offers the bundle first** for a TNHComy-native round trip, with the ST formats as "Export for SillyTavern".
- The World Architect's blueprint is a good model of a "package of things" — world + locations + lorebook + characters. The bundle is the same idea for a single character, and the two should share vocabulary (the blueprint's `characters[]`/`locations[]`/`lorebook` shape is already close).

### Phase 7 — Docs

- `docs/sillytavern-compatibility.md` — two claims are false today: line 13 documents `chara-ext-asset_:{path}` chunks (not implemented anywhere) and line 28 claims expression assets are included (they are not). Rewrite the document around the three buckets, and state plainly that a card is a projection.
- `docs/STATUS.md` — the record for this pass.

---

## 4. Order of work

| Phase | Depends on | Risk |
|---|---|---|
| 1 (honest + non-crashing) | — | low; local fixes plus a migration for `lorebook_entries.enabled` |
| 2 (expressions) | 1 | medium; asset parsing and image writing |
| 5 (not-portable list) | 1 | low; read-only |
| 3 (bundle export) | 2, 5 | medium; new archive format |
| 4 (one import entry) | 1, 3 | medium; converges two flows |
| 6 (UI coherence) | 3, 4 | low |
| 7 (docs) | all | low |

Phases 1 and 5 alone make the product honest, and they are the ones a user hits first.

---

## 5. Risks

| Risk | Mitigation |
|---|---|
| **Changing the report's shape** breaks the frontend, which computes `lossless` from `lost_fields` | Add the new buckets alongside the old fields; the frontend switches to them in the same change. The frontend's card tests use **hand-written** report payloads that do not match the backend's real shape — fix that, and add a test that runs a real backend report through the frontend normaliser. |
| **Making lorebook entries keyless for `constant`** changes activation for existing embedded books | The rule is "an ST `constant: true` entry is always-on". A card that already imported with keys keeps its current behaviour unless it is re-imported. Record the decision in the entry's provenance so it is visible. |
| **`lorebook_entries.enabled` needs a migration** | Migration 109, nullable-free, `DEFAULT TRUE`, so existing rows keep activating. |
| **The bundle is a new format** and could be mistaken for a card | The manifest's `kind` is mandatory, and the import rejects a bundle without one. The file extension is `.tnhzip`, not `.png`/`.json`. |
| **Re-import merge could overwrite work the user did** | The preview shows a **diff** and the commit is explicit. A merge never happens by default. |
| **Phase 4 converges two flows** and the World Architect is large | The convergence is on the *card* side only: the plain import adopts the blueprint machinery instead of reimplementing it. The World Architect's own routes are untouched. |

---

## 6. Validation

```bash
cd backend_v2
.venv/bin/python -m pytest tests/test_character_cards.py tests/test_character_charx.py \
  tests/test_character_card_routes.py tests/test_character_lorebook_ids.py -q
.venv/bin/python -m pytest -q
.venv/bin/ruff check .

cd ../frontend_v2
npx vitest run src/api/characterCards.test.js src/components/characters -q
npx vitest run
npm run lint
```

New tests to write, each of which fails today:

1. A card with `extensions.voice_model_id` naming a voice model that does not exist imports **successfully**, with the value dropped and reported.
2. A card whose `character_book` entry has `constant: true` and keys produces an entry that **activates without a keyword hit**.
3. A card whose entry has `enabled: false` produces an entry that **does not activate**.
4. A card with `data.tags: ["fantasy"]` does **not** put "fantasy" in `visual_tags`.
5. A card with `extensions.suggested_persona` **round-trips** it.
6. A card with ST expression assets imports them as `Character.expressions`, and an export writes them back.
7. A TNHComy character with expressions exports a bundle that contains them, and importing that bundle restores them.
8. Re-importing a card exported by TNHComyu **updates** the existing character instead of creating a second one.
9. A CHARX import reports `format == "charx"`.
10. The import report lists a preserved-but-not-executed feature with its reason, and the frontend shows it.

Manual acceptance:

1. Import a real ST card → the modal names exactly what was not carried and why.
2. Export a TNHComyu character with expressions → the ST card shows no expressions, and the modal says so; the bundle contains them.
3. Export → edit in SillyTavern → re-import → the character is updated, not duplicated.

---

## 7. Out of scope

- **Making a SillyTavern card express the whole vault.** It cannot, and a bespoke `extensions.tnhcomvy.world` would be ignored by every ST client and would be a lie about what a card is. The bundle is the answer.
- **A stable ST extension for world membership.** Same reason.
- **Executing ST `regex_scripts` / `tavern_helper` / `depth_prompt`.** A feature, not a plumbing fix. They are reported as preserved-but-not-executed, which is the honest state.
- **Chat-history import.** The bundle can carry it; a card cannot. Importing a chat as a chat is a separate feature.
