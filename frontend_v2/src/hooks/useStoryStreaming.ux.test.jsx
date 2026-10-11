/**
 * Two UX defects in the story streaming path, both invisible until used.
 *
 * 1. The chapter editor was `disabled` for the whole stream, so the one moment
 *    you most want to change a sentence is the one moment the box is frozen. It
 *    is editable now, which means the stream has to stop overwriting a human.
 * 2. A TTS job's completion did nothing: this hook matched `image` and
 *    `story_continue` only, so narration wrote its beat and never made it
 *    re-render. The audio appeared when some unrelated query happened to
 *    refetch the chapter — which reads as "narration did nothing".
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { TTS_BEAT_ROLE } from '../test/fixtures/beats';

const HOOK = readFileSync(resolve(__dirname, './useStoryStreaming.js'), 'utf8');
const EDITOR = readFileSync(
    resolve(__dirname, '../components/story/StoryEditor.jsx'),
    'utf8',
);
const PANEL = readFileSync(
    resolve(__dirname, '../components/story/StoryBeatsPanel.jsx'),
    'utf8',
);

describe('the editor is editable during a stream', () => {
    it('the textarea is no longer disabled for the whole stream', () => {
        // Scoped to the textarea: the formatting buttons stay disabled, which is
        // correct — applying a transform to text that is being rewritten mid-
        // token is not something to support.
        const marker = EDITOR.indexOf('aria-label="Chapter content"');
        const start = EDITOR.lastIndexOf('<textarea', marker);
        const textarea = EDITOR.slice(start, EDITOR.indexOf('/>', marker) + 2);
        expect(textarea).toContain('onChange');
        expect(textarea).not.toContain('disabled');
    });

    it('the stream yields once the user has typed', () => {
        // Detected by shape: the editor is the source of truth and this is the
        // only writer, so a mismatch is by definition a user edit.
        expect(HOOK).toContain('userTookOver');
    });

    it('throttles the editor writes, and flushes what the throttle held', () => {
        // Two halves, and the second is the one that breaks silently. Writing
        // every token re-rendered the editor 40x a second; skipping the flush
        // drops the last partial second of a paid generation.
        //
        // Scoped to the progress handler, not the file: the constant and the ref
        // survive a revert of the usage, so a file-level check passes either
        // way — which is how the first version of this test silently verified
        // nothing.
        const handler = HOOK.slice(
            HOOK.indexOf('const unsubProgress'),
            HOOK.indexOf('const unsubCompleted'),
        );
        expect(handler).toContain('STREAM_WRITE_MS');
        expect(handler).toContain('streamPendingRef.current');

        const completion = HOOK.slice(HOOK.indexOf("meta.type === 'story_continue'"));
        expect(completion).toContain('if (streamPendingRef.current && finalStreamedText)');
    });
});

describe('narration completion is visible', () => {
    it('handles tts completions, not just image and story_continue', () => {
        expect(HOOK).toContain("job.task_type === 'tts'");
        expect(HOOK).toContain('Narration ready');
    });

    it('refetches both the chapter and the beats', () => {
        const block = HOOK.slice(HOOK.indexOf("job.task_type === 'tts'"));
        const arm = block.slice(0, block.indexOf('} else if'));
        expect(arm).toContain('invalidateQueries');
        expect(arm.match(/invalidateQueries/g) || []).toHaveLength(2);
    });
});

describe('the beat role matches what the backend writes', () => {
    it('keys on tts, not the stale system_tts', () => {
        expect(PANEL).not.toContain('system_tts');
        expect(PANEL).toContain("beat?.role === 'tts'");
    });

    it('offers tts as a selectable role', () => {
        expect(PANEL).toMatch(/BEAT_ROLE_OPTIONS = \[[^\]]*'tts'[^\]]*\]/);
    });

    it('uses the backend constant', () => {
        expect(TTS_BEAT_ROLE).toBe('tts');
    });
});
