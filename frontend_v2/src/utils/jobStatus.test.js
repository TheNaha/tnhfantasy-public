import { describe, expect, it } from 'vitest';
import { filterActiveJobs, filterHistoricalJobs, isActiveJobStatus } from './jobStatus';

describe('jobStatus utils', () => {
    it('identifies active job statuses', () => {
        expect(isActiveJobStatus('generating')).toBe(true);
        expect(isActiveJobStatus('post-processing')).toBe(true);
        expect(isActiveJobStatus('completed')).toBe(false);
        expect(isActiveJobStatus('failed')).toBe(false);
    });

    it('splits active and historical jobs into non-overlapping sets', () => {
        const jobs = [
            { id: 'active-1', status: 'generating' },
            { id: 'active-2', status: 'pending' },
            { id: 'historical-1', status: 'completed' },
            { id: 'historical-2', status: 'failed' },
        ];

        expect(filterActiveJobs(jobs).map((job) => job.id)).toEqual(['active-1', 'active-2']);
        expect(filterHistoricalJobs(jobs).map((job) => job.id)).toEqual(['historical-1', 'historical-2']);
    });
});