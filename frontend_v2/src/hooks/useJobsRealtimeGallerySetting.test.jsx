import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, QueryObserver } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * `gallery.autoRefreshOnJobComplete` must govern the realtime gallery refresh.
 *
 * `useJobsRealtime` is mounted once in App.jsx, so its job.completed handler is
 * the global owner of "a finished image job refreshes the mounted gallery". The
 * Dashboard has its own, setting-aware handler for the same refresh
 * (Dashboard.jsx:116) — so with the setting OFF the user's switch was honoured
 * by one path and ignored by the other, and the gallery still reloaded. Both
 * paths funnel into `refetchNewestGalleryPage`, which coalesces concurrent
 * callers itself, so gating this one costs nothing when the setting is on.
 */

const handlers = new Map();

vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn(), dismiss: vi.fn() },
}));

vi.mock('../api/websocket', () => ({
    connect: vi.fn(() => Promise.resolve()),
    subscribe: vi.fn(() => Promise.resolve()),
    unsubscribe: vi.fn(),
    on: vi.fn((event, cb) => {
        handlers.set(event, cb);
        return () => handlers.delete(event);
    }),
    getConnectionStatus: vi.fn(() => true),
    requestReplay: vi.fn(() => Promise.resolve([])),
    dispatchReplayEvents: vi.fn(),
    EventTypes: {
        JOB_CREATED: 'job.created',
        JOB_PROGRESS: 'job.progress',
        JOB_UPDATED: 'job.updated',
        JOB_POST_PROCESSING: 'job.post_processing',
        JOB_COMPLETED: 'job.completed',
        JOB_FAILED: 'job.failed',
        JOB_CANCELLED: 'job.cancelled',
    },
}));

// Whole-module mock: the hook binds `refetchNewestGalleryPage` at import, so a
// namespace spy would not be the call the hook makes.
const refetchNewestGalleryPage = vi.fn();
vi.mock('./useGallery', () => ({ refetchNewestGalleryPage }));

function makeWrapper() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const wrapper = ({ children }) => (
        <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
    return { queryClient, wrapper };
}

const COMPLETED_IMAGE_JOB = {
    sequence_number: 11,
    data: {
        job: {
            id: 'job-img',
            task_type: 'image',
            status: 'completed',
            outputs: [{ filename: 'a.png' }],
        },
    },
};

describe('useJobsRealtime honours gallery.autoRefreshOnJobComplete', () => {
    let useJobsRealtime;
    let useSettingsStore;

    beforeEach(async () => {
        vi.clearAllMocks();
        handlers.clear();
        // No `vi.resetModules()`: the hook binds `refetchNewestGalleryPage` when
        // it is first imported, and resetting the registry would re-run the
        // mock factory and hand the hook a different vi.fn() than this test
        // asserts on.
        useJobsRealtime = (await import('./useJobsRealtime')).useJobsRealtime;
        useSettingsStore = (await import('../store/settingsStore')).default;
    });

    function setAutoRefresh(value) {
        useSettingsStore.setState((state) => ({
            settings: {
                ...state.settings,
                gallery: { ...state.settings.gallery, autoRefreshOnJobComplete: value },
            },
        }));
    }

    async function mount() {
        const { queryClient, wrapper } = makeWrapper();
        // A mounted gallery, the same shape the Dashboard builds
        // (`['gallery', filters, 25]`). Without an observer the refresh is
        // skipped for a reason that has nothing to do with the setting.
        const observer = new QueryObserver(queryClient, {
            queryKey: ['gallery', { sort: 'date_desc' }, 25],
            queryFn: async () => ({ pages: [], pageParams: [null] }),
        });
        const unsubscribe = observer.subscribe(() => {});
        renderHook(() => useJobsRealtime(), { wrapper });
        await waitFor(() => expect(handlers.has('job.completed')).toBe(true));
        return () => unsubscribe();
    }

    it('refreshes the newest gallery page when the setting is on', async () => {
        setAutoRefresh(true);
        await mount();

        handlers.get('job.completed')(COMPLETED_IMAGE_JOB);

        expect(refetchNewestGalleryPage).toHaveBeenCalled();
    });

    it('does not refresh when the setting is off', async () => {
        setAutoRefresh(false);
        await mount();

        handlers.get('job.completed')(COMPLETED_IMAGE_JOB);

        expect(refetchNewestGalleryPage).not.toHaveBeenCalled();
    });
});
