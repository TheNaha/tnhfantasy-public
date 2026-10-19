import { describe, expect, it } from 'vitest';
import { buildContinuationTimeline, joinContinuationText } from './continuationText';

const parentMessage = {
    id: 'm-1',
    content: 'The door creaked open',
    message_metadata: { source_job_id: 'job-parent' },
};

const otherMessage = {
    id: 'm-2',
    content: 'She stepped through.',
    message_metadata: { source_job_id: 'job-other' },
};

describe('joinContinuationText', () => {
    it('separates two prose fragments with a space', () => {
        expect(joinContinuationText('The door creaked', 'open slowly')).toBe('The door creaked open slowly');
    });

    it('does not double an existing whitespace boundary', () => {
        expect(joinContinuationText('The door creaked ', 'open')).toBe('The door creaked open');
        expect(joinContinuationText('The door creaked', ' open')).toBe('The door creaked open');
    });

    it('keeps punctuation attached to the preceding word', () => {
        expect(joinContinuationText('The door creaked', '.')).toBe('The door creaked.');
        expect(joinContinuationText('The door creaked', '…')).toBe('The door creaked…');
    });

    it('returns whichever half exists when the other is empty', () => {
        expect(joinContinuationText('', 'open')).toBe('open');
        expect(joinContinuationText('open', '')).toBe('open');
    });
});

describe('buildContinuationTimeline', () => {
    it('appends continuation text to the bubble it continues', () => {
        const { items, parentJobIds } = buildContinuationTimeline(
            [parentMessage, otherMessage],
            [{ jobId: 'job-cont', jobData: { continuationOfJobId: 'job-parent', text: 'and swung inward' } }]
        );

        expect(items[0].item.content).toBe('The door creaked open and swung inward');
        expect(items[0].item.continuation_streaming).toBe(true);
        expect(items[1].item).toBe(otherMessage);
        expect(parentJobIds.has('job-parent')).toBe(true);
    });

    it('suppresses the placeholder before the first token arrives', () => {
        const { items, parentJobIds } = buildContinuationTimeline(
            [parentMessage],
            [{ jobId: 'job-cont', jobData: { continuationOfJobId: 'job-parent', text: '' } }]
        );

        expect(items).toHaveLength(1);
        expect(items[0].item.content).toBe(parentMessage.content);
        expect(parentJobIds.has('job-parent')).toBe(true);
    });

    it('leaves a continuation without its parent unmatched so callers can show it', () => {
        const { items, parentJobIds } = buildContinuationTimeline(
            [otherMessage],
            [{ jobId: 'job-cont', jobData: { continuationOfJobId: 'job-parent', text: 'orphaned prose' } }]
        );

        expect(items).toHaveLength(1);
        expect(items[0].item).toBe(otherMessage);
        expect(parentJobIds.size).toBe(0);
    });

    it('ignores jobs that are not continuations', () => {
        const { items, parentJobIds } = buildContinuationTimeline(
            [parentMessage],
            [{ jobId: 'job-fresh', jobData: { text: 'a brand new reply' } }]
        );

        expect(items[0].item).toBe(parentMessage);
        expect(parentJobIds.size).toBe(0);
    });
});
