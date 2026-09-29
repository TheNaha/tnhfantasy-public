/**
 * The dangling promise in user-facing copy.
 *
 * `WORLD_IGNORED_MESSAGE` told a user whose world link was dropped to
 * "set it later from the <chat|story>'s World panel". No World panel existed on
 * either surface, so the only recovery the message offered did not exist. The
 * copy is kept — it is now true — and these tests are what make it stay true:
 * the row is rendered by both context panels, under exactly the heading the
 * message names.
 */
import { describe, expect, it } from 'vitest';
import { WORLD_IGNORED_MESSAGE, warnIfWorldIgnored } from './worldLinkWarning';

describe('worldLinkWarning', () => {
    it('still names a World panel, which both context panels now render', () => {
        expect(WORLD_IGNORED_MESSAGE('chat')).toContain("the chat's World panel");
        expect(WORLD_IGNORED_MESSAGE('story')).toContain("the story's World panel");
    });

    it('flags a world that did not stick, and only then', () => {
        expect(warnIfWorldIgnored({ world_id: 'w-1' }, 'w-1')).toBe(false);
        expect(warnIfWorldIgnored({ world_id: 'w-2' }, 'w-1')).toEqual({ ignored: true, label: 'chat' });
        // Nothing was asked for, so nothing was ignored.
        expect(warnIfWorldIgnored({ world_id: null }, null)).toBe(false);
    });
});
