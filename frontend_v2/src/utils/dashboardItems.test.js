import { describe, expect, it } from 'vitest';
import { buildDashboardItems } from './dashboardItems';

describe('buildDashboardItems', () => {
    it('keeps active jobs selectable while rendering historical output as images', () => {
        const data = {
            pages: [
                {
                    files: [
                        {
                            name: 'result.png',
                            date: '2024-01-03T00:00:00Z',
                            metadata: { job_id: 'job-complete' },
                        },
                    ],
                    jobs: [
                        {
                            id: 'job-complete',
                            status: 'completed',
                            created_at: '2024-01-02T00:00:00Z',
                            updated_at: '2024-01-03T00:00:00Z',
                            outputs: ['result.png'],
                        },
                    ],
                },
            ],
        };

        const activeJobs = [
            {
                id: 'job-active',
                status: 'running',
                created_at: '2024-01-04T00:00:00Z',
                updated_at: '2024-01-04T00:05:00Z',
                outputs: [],
            },
        ];

        const { items, jobsById } = buildDashboardItems(data, activeJobs);

        expect(jobsById.get('job-complete')?.status).toBe('completed');
        expect(jobsById.get('job-active')?.status).toBe('running');
        expect(items.some((item) => item.type === 'job' && item.id === 'job-active')).toBe(true);
        expect(items.some((item) => item.type === 'image' && item.name === 'result.png')).toBe(true);
        expect(items.some((item) => item.type === 'job' && item.id === 'job-complete')).toBe(false);
    });
});