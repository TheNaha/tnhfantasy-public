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

    it('replaces a completed job in place instead of moving output to top', () => {
        const initialData = {
            pages: [
                {
                    files: [
                        { name: 'top.png', date: '2024-01-05T00:00:00Z', metadata: {} },
                        { name: 'bottom.png', date: '2024-01-01T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
            ],
        };

        const completedData = {
            pages: [
                {
                    files: [
                        { name: 'top.png', date: '2024-01-05T00:00:00Z', metadata: {} },
                        {
                            name: 'result.png',
                            date: '2024-01-06T00:00:00Z',
                            metadata: { job_id: 'job-1' },
                        },
                        { name: 'bottom.png', date: '2024-01-01T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
            ],
        };

        const { result, rerender } = renderHook((props) => useDashboardItems(props), {
            initialProps: {
                data: initialData,
                activeJobs: [
                    {
                        id: 'job-1',
                        status: 'running',
                        created_at: '2024-01-03T00:00:00Z',
                        updated_at: '2024-01-03T00:00:10Z',
                        outputs: [],
                    },
                ],
                selectedJobId: null,
                activeCollection: null,
                collections: {},
                showFavorites: false,
                favorites: [],
            },
        });

        rerender({
            data: completedData,
            activeJobs: [],
            selectedJobId: null,
            activeCollection: null,
            collections: {},
            showFavorites: false,
            favorites: [],
        });

        const orderedNames = result.current.allItems.map((item) => item.name || item.id);
        expect(orderedNames).toEqual(['top.png', 'result.png', 'bottom.png']);
    });

    it('keeps anchored replacement stable when infinite scroll appends older pages', () => {
        const initialData = {
            pages: [
                {
                    files: [
                        { name: 'top.png', date: '2024-01-05T00:00:00Z', metadata: {} },
                        { name: 'bottom.png', date: '2024-01-01T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
            ],
        };

        const completedPageOneData = {
            pages: [
                {
                    files: [
                        { name: 'top.png', date: '2024-01-05T00:00:00Z', metadata: {} },
                        {
                            name: 'result.png',
                            date: '2024-01-06T00:00:00Z',
                            metadata: { job_id: 'job-2' },
                        },
                        { name: 'bottom.png', date: '2024-01-01T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
            ],
        };

        const completedWithOlderPageData = {
            pages: [
                {
                    files: [
                        { name: 'top.png', date: '2024-01-05T00:00:00Z', metadata: {} },
                        {
                            name: 'result.png',
                            date: '2024-01-06T00:00:00Z',
                            metadata: { job_id: 'job-2' },
                        },
                        { name: 'bottom.png', date: '2024-01-01T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
                {
                    files: [
                        { name: 'older-1.png', date: '2023-12-31T00:00:00Z', metadata: {} },
                        { name: 'older-2.png', date: '2023-12-30T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
            ],
        };

        const { result, rerender } = renderHook((props) => useDashboardItems(props), {
            initialProps: {
                data: initialData,
                activeJobs: [
                    {
                        id: 'job-2',
                        status: 'running',
                        created_at: '2024-01-03T00:00:00Z',
                        updated_at: '2024-01-03T00:00:10Z',
                        outputs: [],
                    },
                ],
                selectedJobId: null,
                activeCollection: null,
                collections: {},
                showFavorites: false,
                favorites: [],
            },
        });

        rerender({
            data: completedPageOneData,
            activeJobs: [],
            selectedJobId: null,
            activeCollection: null,
            collections: {},
            showFavorites: false,
            favorites: [],
        });

        const orderBeforeAppend = result.current.allItems.map((item) => item.name || item.id);
        expect(orderBeforeAppend).toEqual(['top.png', 'result.png', 'bottom.png']);

        rerender({
            data: completedWithOlderPageData,
            activeJobs: [],
            selectedJobId: null,
            activeCollection: null,
            collections: {},
            showFavorites: false,
            favorites: [],
        });

        const orderAfterAppend = result.current.allItems.map((item) => item.name || item.id);
        expect(orderAfterAppend).toEqual(['top.png', 'result.png', 'bottom.png', 'older-1.png', 'older-2.png']);
    });

    it('keeps replacement order after full reload using persisted job timeline anchor', () => {
        const reloadedData = {
            pages: [
                {
                    files: [
                        { name: 'top.png', date: '2024-01-05T00:00:00Z', metadata: {} },
                        {
                            name: 'result.png',
                            date: '2024-01-06T00:00:00Z',
                            metadata: {
                                job_id: 'job-reload',
                                job_timeline_anchor: '2024-01-03T00:00:00Z',
                            },
                        },
                        { name: 'bottom.png', date: '2024-01-01T00:00:00Z', metadata: {} },
                    ],
                    jobs: [],
                },
            ],
        };

        const { result } = renderHook(() => useDashboardItems({
            data: reloadedData,
            activeJobs: [],
            selectedJobId: null,
            activeCollection: null,
            collections: {},
            showFavorites: false,
            favorites: [],
        }));

        const orderedNames = result.current.allItems.map((item) => item.name || item.id);
        expect(orderedNames).toEqual(['top.png', 'result.png', 'bottom.png']);
    });
});