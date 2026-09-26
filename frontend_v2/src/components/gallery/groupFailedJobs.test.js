import { describe, expect, it } from 'vitest';
import {
    describeErrorType,
    describeGroupSize,
    formatDuration,
    groupFailedJobs,
} from './groupFailedJobs';

function makeJob(id, { errorType = 'providers_exhausted', providerId = 'llm-local', overrides = {} } = {}) {
    return {
        id,
        status: 'failed',
        error: 'All providers failed: Every provider was tried and failed',
        provider_id: providerId,
        completed_at: '2026-01-01T12:00:00Z',
        metadata: { prompt: `prompt for ${id}` },
        diagnostics: {
            error_type: errorType,
            attempt_count: 1,
            duration_seconds: 7,
            is_retryable: true,
        },
        ...overrides,
    };
}

describe('groupFailedJobs', () => {
    it('returns nothing for an empty or missing list', () => {
        expect(groupFailedJobs([])).toEqual([]);
        expect(groupFailedJobs(null)).toEqual([]);
        expect(groupFailedJobs(undefined)).toEqual([]);
    });

    it('collapses jobs that share a cause and provider into one group with the right count', () => {
        const groups = groupFailedJobs([
            makeJob('a', { overrides: { diagnostics: { ...makeJob('x').diagnostics, duration_seconds: 7 } } }),
            makeJob('b', { overrides: { diagnostics: { ...makeJob('x').diagnostics, duration_seconds: 7 } } }),
            makeJob('c', { overrides: { diagnostics: { ...makeJob('x').diagnostics, duration_seconds: 8 } } }),
        ]);

        expect(groups).toHaveLength(1);
        expect(groups[0].count).toBe(3);
        expect(groups[0].errorType).toBe('providers_exhausted');
        expect(groups[0].label).toBe('Providers exhausted');
        expect(groups[0].providerId).toBe('llm-local');
        expect(groups[0].jobs.map((job) => job.id)).toEqual(['a', 'b', 'c']);
    });

    it('keeps every job reachable inside the group, with its own detail intact', () => {
        const jobs = [
            makeJob('a', { overrides: { metadata: { prompt: 'a red door' } } }),
            makeJob('b', { overrides: { metadata: { prompt: 'a blue door' } } }),
        ];

        const [group] = groupFailedJobs(jobs);

        expect(group.jobs).toHaveLength(2);
        expect(group.jobs.map((job) => job.metadata.prompt)).toEqual(['a red door', 'a blue door']);
    });

    it('splits different causes into one group each', () => {
        const groups = groupFailedJobs([
            makeJob('a', { errorType: 'providers_exhausted' }),
            makeJob('b', { errorType: 'timeout' }),
            makeJob('c', { errorType: 'timeout' }),
        ]);

        expect(groups).toHaveLength(2);
        expect(groups.map((group) => [group.errorType, group.count])).toEqual([
            ['timeout', 2],
            ['providers_exhausted', 1],
        ]);
    });

    it('splits the same cause across different providers', () => {
        const groups = groupFailedJobs([
            makeJob('a', { providerId: 'llm-local' }),
            makeJob('b', { providerId: 'beam-image' }),
        ]);

        expect(groups).toHaveLength(2);
        expect(groups.map((group) => group.providerId).sort()).toEqual(['beam-image', 'llm-local']);
    });

    it('orders groups by size, then by first appearance', () => {
        const groups = groupFailedJobs([
            makeJob('single', { errorType: 'cancelled' }),
            makeJob('a'),
            makeJob('b'),
        ]);

        expect(groups.map((group) => [group.errorType, group.count])).toEqual([
            ['providers_exhausted', 2],
            ['cancelled', 1],
        ]);
    });

    it('groups unassigned jobs under a single sentinel instead of scattering them', () => {
        const groups = groupFailedJobs([
            makeJob('a', { providerId: null }),
            makeJob('b', { providerId: null }),
        ]);

        expect(groups).toHaveLength(1);
        expect(groups[0].count).toBe(2);
        expect(groups[0].providerId).toBeNull();
        expect(groups[0].providerLabel).toBe('unassigned');
    });

    it('falls back to last_provider_id when jobs.provider_id is null', () => {
        const groups = groupFailedJobs([
            makeJob('a', {
                providerId: null,
                overrides: { diagnostics: { ...makeJob('x').diagnostics, last_provider_id: 'llm-local' } },
            }),
            makeJob('b', { providerId: 'llm-local' }),
        ]);

        expect(groups).toHaveLength(1);
        expect(groups[0].count).toBe(2);
    });

    it('treats a job with no error_type as unknown rather than dropping it', () => {
        const groups = groupFailedJobs([
            { id: 'a', status: 'failed', provider_id: 'llm-local' },
        ]);

        expect(groups).toHaveLength(1);
        expect(groups[0].errorType).toBe('unknown');
        expect(groups[0].label).toBe('Failed');
    });

    it('strips the provider container prefixes for display', () => {
        const [group] = groupFailedJobs([makeJob('a', { providerId: 'modal-p1' })]);
        expect(group.providerLabel).toBe('p1');
    });
});

describe('describeGroupSize', () => {
    it('pluralizes the job count', () => {
        expect(describeGroupSize(1)).toBe('1 job failed');
        expect(describeGroupSize(3)).toBe('3 jobs failed');
    });
});

describe('describeErrorType', () => {
    it('maps known backend failure kinds to a label and hint', () => {
        expect(describeErrorType('providers_exhausted').label).toBe('Providers exhausted');
        expect(describeErrorType('stale_recovery').hint).toMatch(/restart or dead worker/i);
    });

    it('falls back to the raw value for an unmapped kind', () => {
        expect(describeErrorType('brand_new_kind').label).toBe('brand_new_kind');
    });
});

describe('formatDuration', () => {
    it('formats seconds, minutes and hours', () => {
        expect(formatDuration(7)).toBe('7s');
        expect(formatDuration(90)).toBe('2m');
        expect(formatDuration(7200)).toBe('2h');
    });

    it('returns null for values that are not a usable duration', () => {
        expect(formatDuration(null)).toBeNull();
        expect(formatDuration(-1)).toBeNull();
        expect(formatDuration('7')).toBeNull();
    });
});
