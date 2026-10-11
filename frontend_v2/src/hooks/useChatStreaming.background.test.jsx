/**
 * A background job must not render as a reply.
 *
 * Memory extraction runs after every reply, is built from that same
 * conversation, and therefore carries the chat's own `chat_id`. The chat
 * streaming reducer keys on that id and renders a reply bubble for anything
 * streaming, so an extraction appeared as a second "X is thinking..." under the
 * reply it was derived from — and its completion invalidated the whole
 * transcript a second time per turn.
 *
 * The backend marks such jobs `background: true` in the workflow AND the
 * metadata, so both the progress and terminal paths can see it.
 */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { jobMetadata } from '../utils/jobStatus';

const BACKGROUND_JOB = {
    id: 'job-mem',
    task_type: 'llm',
    metadata: { chat_id: 'chat-1', workspace: 'chat', background: true },
};

const REPLY_JOB = {
    id: 'job-reply',
    task_type: 'llm',
    metadata: { chat_id: 'chat-1', workspace: 'chat' },
};

describe('jobMetadata surfaces the background flag', () => {
    it('passes the flag through from the job metadata', () => {
        expect(jobMetadata(BACKGROUND_JOB).background).toBe(true);
    });

    it('leaves a normal reply falsy, so it is not filtered', () => {
        expect(jobMetadata(REPLY_JOB).background).toBeFalsy();
    });

    it('reads metadata_ as well as metadata, for a serialised job row', () => {
        expect(jobMetadata({ metadata_: { background: true } }).background).toBe(true);
    });
});

describe('useChatStreaming filters background jobs', () => {
    // Structural: rendering the hook needs a ChatWorkspace provider, and the
    // filter sits at applyStreamUpdate's top, so it covers both the streaming
    // path and the terminal path in one place.
    const source = readFileSync(resolve(__dirname, './useChatStreaming.js'), 'utf8');

    it('guards the streaming path', () => {
        expect(source).toContain('if (meta.background) return;');
    });

    it('guards the terminal path too, so no second refetch', () => {
        const matches = source.match(/if \(meta\.background\) return;/g) || [];
        expect(matches.length).toBe(2);
    });
});
