import { describe, expect, it } from 'vitest';
import { renderHook } from '@testing-library/react';

import { useDashboardItems } from './useDashboardItems';

describe('useDashboardItems', () => {
    it('resolves selected historical jobs from merged dashboard data', () => {
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

        const { result } = renderHook(() => useDashboardItems({
            data,
            activeJobs: [],
            selectedJobId: 'job-complete',
            activeCollection: null,
            collections: {},
            showFavorites: false,
            favorites: [],
        }));

        expect(result.current.selectedJob?.id).toBe('job-complete');
        expect(result.current.allItems.some((item) => item.type === 'image' && item.name === 'result.png')).toBe(true);
    });

    it('filters displayed items by active collection and favorites', () => {
        const data = {
            pages: [
                {
                    files: [
                        { name: 'favorite.png', date: '2024-01-03T00:00:00Z', metadata: {} },
                        { name: 'other.png', date: '2024-01-02T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
            ],
        };

        const { result } = renderHook(() => useDashboardItems({
            data,
            activeJobs: [],
            selectedJobId: null,
            activeCollection: 'collection-1',
            collections: {
                'collection-1': {
                    images: ['favorite.png'],
                },
            },
            showFavorites: true,
            favorites: ['favorite.png'],
        }));

        expect(result.current.displayedItems).toHaveLength(1);
        expect(result.current.displayedItems[0].name).toBe('favorite.png');
    });
});