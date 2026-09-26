import { describe, it, expect } from 'vitest';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import {
    JOB_STATUS,
    JOB_STATUSES,
    JOB_PHASE_ORDER,
    UNFINISHED_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    isActiveJobStatus,
    isTerminalJobStatus,
    isJobRunning,
    isJobFailed,
    isJobCancelled,
    isJobComplete,
} from './jobStatus';

/**
 * `class JobStatus(str, Enum)` in `backend_v2/core/entities.py`, transcribed.
 * Hardcoded so this file stays hermetic — the frontend Docker image contains
 * only `frontend_v2`, so the guarded cross-check below is a no-op there while
 * still failing CI on both sides in a full checkout.
 */
const BACKEND_JOB_STATUSES = Object.freeze([
    'pending',
    'retrying',
    'sent-to-provider',
    'connected',
    'pre-generation',
    'generating',
    'completed',
    'post-processing',
    'failed',
    'cancelled',
]);

const ENTITIES_PATH = resolve(
    dirname(fileURLToPath(import.meta.url)),
    '../../../backend_v2/core/entities.py'
);

function readBackendJobStatusValues() {
    if (!existsSync(ENTITIES_PATH)) return null;
    const source = readFileSync(ENTITIES_PATH, 'utf8');
    // The class body ends at the first line that is no longer indented.
    const classMatch = source.match(/^class\s+JobStatus\b[\s\S]*?(?=^\S)/m);
    if (!classMatch) throw new Error(`JobStatus enum not found in ${ENTITIES_PATH}`);
    const values = [...classMatch[0].matchAll(/^\s+[A-Z][A-Z0-9_]*\s*=\s*"([^"]+)"/gm)].map((m) => m[1]);
    if (values.length === 0) throw new Error(`JobStatus enum in ${ENTITIES_PATH} yielded no values`);
    return values;
}

/**
 * Every spelling that previously drifted into a copied list somewhere in the
 * tree and can therefore never match what the API emits.
 */
const DEAD_SPELLINGS = Object.freeze([
    'sent_to_provider',
    'pre_generation',
    'post_processing',
    'generating_blurhash',
    'generating_thumbnails',
    'validating',
    'connecting',
    'processing',
    'executing',
    'progress',
    'running',
    'queued',
]);

describe('jobStatus — the vocabulary is the backend vocabulary', () => {
    it('lists exactly the JobStatus members, with no extras and none missing', () => {
        expect([...JOB_STATUSES].sort()).toEqual([...BACKEND_JOB_STATUSES].sort());
    });

    it('reads back the real backend enum when the backend is present', () => {
        const backendValues = readBackendJobStatusValues();
        if (!backendValues) return; // frontend-only checkout (Docker image)
        expect([...JOB_STATUSES].sort()).toEqual([...backendValues].sort());
    });

    it('exposes a constant for every status and a matching key for each', () => {
        for (const [name, value] of Object.entries(JOB_STATUS)) {
            expect(value).toBe(name.toLowerCase().replace(/_/g, '-'));
        }
        expect(new Set(JOB_STATUSES).size).toBe(JOB_STATUSES.length);
    });

    it('is frozen, so a component cannot mutate the shared list', () => {
        expect(Object.isFrozen(JOB_STATUS)).toBe(true);
        expect(Object.isFrozen(JOB_STATUSES)).toBe(true);
        expect(Object.isFrozen(UNFINISHED_JOB_STATUSES)).toBe(true);
        expect(Object.isFrozen(TERMINAL_JOB_STATUSES)).toBe(true);
        expect(Object.isFrozen(JOB_PHASE_ORDER)).toBe(true);
    });
});

describe('jobStatus — no snake_case or phantom spellings survive', () => {
    it('contains no snake_case status', () => {
        for (const status of JOB_STATUSES) {
            expect(status).not.toMatch(/_/);
        }
    });

    it('would not accept a dead snake_case spelling', () => {
        for (const dead of DEAD_SPELLINGS) {
            expect(JOB_STATUSES).not.toContain(dead);
            expect(isActiveJobStatus(dead)).toBe(false);
            expect(isTerminalJobStatus(dead)).toBe(false);
        }
    });

    it('has no key that could reintroduce a phantom status like connecting', () => {
        // A phantom would be a value in JOB_STATUS that the backend does not
        // emit; the check below is what makes adding one fail.
        expect(JOB_STATUS.CONNECTING).toBeUndefined();
        expect(JOB_STATUS.VALIDATING).toBeUndefined();
        expect(JOB_STATUSES).toHaveLength(10);
        expect(JOB_STATUSES).toEqual(BACKEND_JOB_STATUSES);
    });
});

describe('jobStatus — unfinished vs terminal', () => {
    it('covers every non-terminal status as unfinished', () => {
        const nonTerminal = JOB_STATUSES.filter((s) => !TERMINAL_JOB_STATUSES.includes(s));
        expect([...UNFINISHED_JOB_STATUSES].sort()).toEqual([...nonTerminal].sort());
    });

    it('includes PENDING in unfinished — a queued job still has to be polled', () => {
        expect(UNFINISHED_JOB_STATUSES).toContain(JOB_STATUS.PENDING);
        expect(UNFINISHED_JOB_STATUSES).toHaveLength(7);
    });

    it('partitions the vocabulary with no overlap and nothing unclassified', () => {
        const overlap = UNFINISHED_JOB_STATUSES.filter((s) => TERMINAL_JOB_STATUSES.includes(s));
        expect(overlap).toEqual([]);
        expect(UNFINISHED_JOB_STATUSES.length + TERMINAL_JOB_STATUSES.length).toBe(JOB_STATUSES.length);
    });

    it('mirrors the backend terminal set', () => {
        expect([...TERMINAL_JOB_STATUSES]).toEqual([
            JOB_STATUS.COMPLETED,
            JOB_STATUS.FAILED,
            JOB_STATUS.CANCELLED,
        ]);
    });
});

describe('jobStatus — phase order', () => {
    it('is the unfinished statuses in lifecycle order', () => {
        expect([...JOB_PHASE_ORDER]).toEqual([
            JOB_STATUS.PENDING,
            JOB_STATUS.RETRYING,
            JOB_STATUS.SENT_TO_PROVIDER,
            JOB_STATUS.CONNECTED,
            JOB_STATUS.PRE_GENERATION,
            JOB_STATUS.GENERATING,
            JOB_STATUS.POST_PROCESSING,
        ]);
    });

    it('indexes every unfinished status, so a progress timeline can never be off', () => {
        for (const status of UNFINISHED_JOB_STATUSES) {
            expect(JOB_PHASE_ORDER.indexOf(status)).toBeGreaterThanOrEqual(0);
        }
        for (const status of TERMINAL_JOB_STATUSES) {
            expect(JOB_PHASE_ORDER.indexOf(status)).toBe(-1);
        }
        expect(new Set(JOB_PHASE_ORDER).size).toBe(JOB_PHASE_ORDER.length);
    });
});

describe('jobStatus — predicates agree with the sets', () => {
    it('isActiveJobStatus is exactly membership of UNFINISHED', () => {
        for (const status of JOB_STATUSES) {
            expect(isActiveJobStatus(status)).toBe(UNFINISHED_JOB_STATUSES.includes(status));
            expect(isJobRunning(status)).toBe(isActiveJobStatus(status));
        }
    });

    it('isTerminalJobStatus is exactly membership of TERMINAL', () => {
        for (const status of JOB_STATUSES) {
            expect(isTerminalJobStatus(status)).toBe(TERMINAL_JOB_STATUSES.includes(status));
        }
    });

    it('is never both running and terminal', () => {
        for (const status of JOB_STATUSES) {
            expect(isJobRunning(status) && isTerminalJobStatus(status)).toBe(false);
        }
    });

    it('splits the terminal set three ways', () => {
        for (const status of JOB_STATUSES) {
            const terminalFlags = [isJobComplete(status), isJobFailed(status), isJobCancelled(status)].filter(Boolean);
            expect(terminalFlags).toHaveLength(TERMINAL_JOB_STATUSES.includes(status) ? 1 : 0);
        }
        expect(isJobComplete(JOB_STATUS.COMPLETED)).toBe(true);
        expect(isJobFailed(JOB_STATUS.FAILED)).toBe(true);
        expect(isJobCancelled(JOB_STATUS.CANCELLED)).toBe(true);
    });

    it('still recognises the legacy "error" spelling as failed', () => {
        // `useJobStatus`/older API payloads used it; nothing emits it now, but
        // treating an unknown terminal-ish status as running is worse.
        expect(isJobFailed('error')).toBe(true);
        expect(isJobRunning('error')).toBe(false);
        expect(isJobComplete('error')).toBe(false);
        expect(isJobCancelled('error')).toBe(false);
    });

    it('treats unknown, undefined and null statuses as neither', () => {
        for (const unknown of [undefined, null, '', 'queued', 'CONNECTED']) {
            expect(isActiveJobStatus(unknown)).toBe(false);
            expect(isTerminalJobStatus(unknown)).toBe(false);
            expect(isJobRunning(unknown)).toBe(false);
            expect(isJobComplete(unknown)).toBe(false);
            expect(isJobCancelled(unknown)).toBe(false);
            expect(isJobFailed(unknown)).toBe(false);
        }
    });
});
