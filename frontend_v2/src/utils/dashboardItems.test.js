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

    it('keeps completed output at anchored job timeline position when job card is gone', () => {
        const data = {
            pages: [
                {
                    files: [
                        {
                            name: 'top.png',
                            date: '2024-01-05T00:00:00Z',
                            metadata: {},
                        },
                        {
                            name: 'result.png',
                            date: '2024-01-06T00:00:00Z',
                            metadata: { job_id: 'job-replaced' },
                        },
                        {
                            name: 'bottom.png',
                            date: '2024-01-01T00:00:00Z',
                            metadata: {},
                        },
                    ],
                    jobs: [],
                },
            ],
        };

        const jobTimelineOverrides = new Map([
            ['job-replaced', '2024-01-03T00:00:00Z'],
        ]);

        const { items } = buildDashboardItems(data, [], jobTimelineOverrides);
        const namesInOrder = items.map((item) => item.name || item.id);
        const replacedImage = items.find((item) => item.name === 'result.png');

        expect(namesInOrder).toEqual(['top.png', 'result.png', 'bottom.png']);
        expect(replacedImage.timelineDate).toBe('2024-01-03T00:00:00Z');
    });

    it('uses persisted job timeline anchor without live override map', () => {
        const data = {
            pages: [
                {
                    files: [
                        {
                            name: 'top.png',
                            date: '2024-01-05T00:00:00Z',
                            metadata: {},
                        },
                        {
                            name: 'result.png',
                            date: '2024-01-06T00:00:00Z',
                            metadata: {
                                job_id: 'job-persisted',
                                job_timeline_anchor: '2024-01-03T00:00:00Z',
                            },
                        },
                        {
                            name: 'bottom.png',
                            date: '2024-01-01T00:00:00Z',
                            metadata: {},
                        },
                    ],
                    jobs: [],
                },
            ],
        };

        const { items } = buildDashboardItems(data, []);
        const namesInOrder = items.map((item) => item.name || item.id);
        const replacedImage = items.find((item) => item.name === 'result.png');

        expect(namesInOrder).toEqual(['top.png', 'result.png', 'bottom.png']);
        expect(replacedImage.timelineDate).toBe('2024-01-03T00:00:00Z');
    });
});