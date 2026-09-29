# Roleplay system — coherence pass

An audit of the World Vault found the user's own read of it to be accurate:
*"most of them either borderline useless, not connected to anything, or have
confusing uses."*

The headline finding is that this was **never a build problem**. Every entity had
a page, most pages had a working editor, and the backend already had every join
that would make the relationships real. What was missing was *ownership of
relationships* — the link between two things was usually owned by the library
page of one of them in a form that did not propagate, or by neither.

The diagnostic that settled it was the **acid test**: for each entity, what
actually reaches the model's prompt? Run both ways — what reaches the prompt,
and what the UI lets you connect — and the two lists barely overlapped.

## What was actually broken

| Entity | Reached the prompt? | Why not |
|---|---|---|
| Character | yes | — |
| Lorebook entries | yes | — |
| Memory | **chat only** | the block needs `character_id`; the story path never passes one |
| Location | **story only** | `Chat.location_id` was read by the UI and **written by nothing** |
| Persona | **partial** | loses to `Chat.persona_name`; impersonation didn't pass a session, so it lost it entirely |
| Scenario | **story only** | on a chat, Apply wrote `system_prompt_override`, which *deletes the character card* |
| **World** | **nothing** | zero references in `context_builder.py` |
| Voice | n/a | TTS-only, correctly |

Three words also meant the wrong things, which is most of why it *felt*
disjointed:

- **"World"** meant three things — the Vault (a search page), the Graph
  (relationships), and the entity. The sidebar and the front door sent you to
  two *different* pages under the same word.
- **"Session"** meant two incompatible things — the front door's "Recent
  sessions" is chats and stories; the Gallery's "Sessions" are curated image
  groups.
- **"Avatar"** is not an entity. It is `Character.avatar_path` (a portrait) and
  `Character.expressions` (emotion → portrait). The Avatar Gallery page was
  already deleted in `82210e50` as a duplicate of Characters. Nothing to
  reconcile.

## What changed

### The World became a real grouping

The keystone. `Chat.world_id` / `Story.world_id` were written, maintained by
`services/world_ownership.py`, and read by nothing — so filing a cast under a
World changed nothing about what the model was told.

- `chat_context_kwargs` resolves the owning World and merges its
  `lorebook_ids`, `location_ids` and first `scenario_ids` entry into the
  prompt, additively. A chat's own picks always come first.
- `World.lorebook_ids` / `scenario_ids` / `voice_ids` are now **writable** via
  `WorldCreate` / `WorldUpdate` and validated — they had **no writer at all**,
  so a World's membership was unconfigurable even once it was read.
- A World contributes its `description` as a `[Setting: …]` section, with
  `{{user}}` / `{{char}}` expanded like every other section.

### The chat path caught up to the story path

`StoryContextPanel` was the good implementation; `ChatContextPanel` was the same
panel missing four things. The chat panel now has the Locations editor with
create-in-place, a lorebook create-in-place, the inspector's edit handlers, and
the cross-links. `NewChatModal`'s free-text location became a real select.

### Content that was authored and silently dropped

- **A scenario applied to a chat no longer deletes the character card.** The
  override *replaces* everything character-related, so one click on the Scenarios
  page removed the character's description, personality, system prompt, extra
  instructions and example dialogue from every later turn, with nothing shown to
  the user. Apply now writes `append_system_prompt`; the override keeps its
  replace-semantics for the explicit Chat Prompt tab, which is what it is for.
- **The story path gets the premise, the earlier chapters, and a real budget.**
  It sent one message — the current chapter — with no chapter history, no
  `Story.description`, no `max_context_tokens` (so it fell through to
  `DEFAULT_MAX_TOKENS` and then truncated the user's own prose), and it injected
  the chat-formatting block into a prose continuation that had just been told to
  output nothing but prose.
- **Macros reach every section.** Substitution ran before twelve of the
  seventeen sections were even built, and only over a five-`source` allowlist —
  so a SillyTavern scenario, which is *written* with `{{user}}`, reached the
  model as literal braces.
- **A character's own lorebooks reach the prompt.** `Character.lorebook_ids` is
  the one new link; see below.
- **A chat's context budget is bounded.** The global setting is range-checked to
  1024–32768; the per-chat override bypassed that check entirely, and it is a
  paid prompt size.

### The prompt stopped paying for the same prose twice

A character was rendered both as a `character_<id>` card and again inside
`story_characters`. A linked location was rendered both as `[Location: X]` and
again inside `[Active Locations]` — `chat_context_kwargs` populated both from
the single `Chat.location_id` column. On every turn, for every message.

### Character ↔ Lorebook — the one missing link

A lorebook could attach to a chat and a story, and a SillyTavern card could
carry an embedded `character_book` — but a lorebook could not attach to a
**Character**, which is what the Lorebooks page's own empty state promised
(*"store world facts, character backgrounds, and setting details"*).
`Character.lorebook_ids` now exists, is writable, is scrubbed on lorebook
delete, and is merged into every prompt for a conversation with that character —
resolved on every build, not snapshotted at chat creation, so existing chats
pick it up.

### Activity

The timeline had no world concept at all — its own docstring said so. It now
takes `world_id`, and three filters were wrong: the Location filter sent a UUID
against a free-text column (always empty), `story_id` did not filter messages,
and `character_id` matched the chat's *primary* character rather than the
speaker, so a group chat returned the wrong lines.

### What was deleted

- The doubled timeline path. It was registered at `/api/v2/timeline/timeline` and
  the frontend worked around it; both now use `/api/v2/timeline`.
- `useVirtualListScrollMargin` — zero importers, and it still contained the bug
  it was written to fix.

### What was renamed

The Gallery's "Sessions" is now "Collections" (curated image groups, which is
what it is), and the two "World" nav entries now agree on `/worlds`. The search
hub is labelled "Search everything" rather than "World Vault", because that is
what it does — and it is the deep-link target for story `@mentions`, so it was
kept rather than deleted.

## A note on the shape of this

Nothing here required a new surface. Every change is a call-site edit to
`EntityContextInspector`, `RoleplayPageShell`, or a copy of a sibling panel that
already existed. The two assets that made it tractable are the shared
`EntityContextInspector` (a props-driven "what does the model actually receive"
panel, including a live "N of M lorebook entries would be injected now" count)
and `StoryContextPanel`, which is the reference implementation the chat panel
was brought up to.

**Three entities remain honestly out of scope**: `VoiceModel` is TTS-only and
correctly scoped; `Session` remains a purely visual concept that lives in
`world_vault/` for historical reasons and is now named honestly; and the
character card's SillyTavern fields (`alternate_greetings`, `group_greetings`,
`suggested_persona`, `creator_notes`, `lora_triggers`) are still write-only.
Those are a SillyTavern-import completeness question, not an integration one,
and are listed in `docs/audit-2026-09-29b.md`.
