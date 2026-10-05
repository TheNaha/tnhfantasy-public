import { renderHook, act, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useGeneratorJob } from './useGeneratorJob';

vi.mock('./useJobStatus', () => ({
    useJobStatus: () => ({ data: null }), // no job subscription -> effect never fires
}));

const mockNavigate = vi.fn();
vi.mock('react-router-dom', () => ({
    useNavigate: () => mockNavigate,
}));

vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn() },
}));

const mockUseSettingsStore = vi.fn();
vi.mock('../store/settingsStore', () => ({
    default: (sel) => mockUseSettingsStore(sel),
}));

import toast from 'react-hot-toast';

describe('useGeneratorJob', () => {
    let mockRunSubmission;

    beforeEach(() => {
        vi.clearAllMocks();
        mockNavigate.mockClear();
        mockUseSettingsStore.mockImplementation((sel) =>
            sel({ settings: { generator: { redirectAfterGenerate: false, redirectDelay: 0 } } })
        );
        mockRunSubmission = vi.fn().mockResolvedValue({
            ok: true,
            submissionResult: { id: 'job-1' },
        });
    });

    it('submits the workflow and tracks the job on success', async () => {
        const randomizeSeed = vi.fn();
        const { result } = renderHook(() =>
            useGeneratorJob({
                runSubmission: mockRunSubmission,
                type: 'simple',
                setGeneratingOnQueue: false,
                autoRandomizeSeed: true,
                randomizeSeed,
            })
        );

        await act(async () => {
            await result.current.handleGenerate();
        });

        expect(mockRunSubmission).toHaveBeenCalledTimes(1);
        expect(result.current.currentJobId).toBe('job-1');
        expect(toast.success).toHaveBeenCalledWith('Job queued!', { icon: '⏳' });
        expect(mockNavigate).not.toHaveBeenCalled();
        expect(randomizeSeed).toHaveBeenCalled();
    });

    it('redirects after generation when the setting is enabled', async () => {
        mockUseSettingsStore.mockImplementation((sel) =>
            sel({ settings: { generator: { redirectAfterGenerate: true, redirectDelay: 0 } } })
        );
        const { result } = renderHook(() =>
            useGeneratorJob({
                runSubmission: mockRunSubmission,
                type: 'simple',
                setGeneratingOnQueue: false,
            })
        );

        await act(async () => {
            await result.current.handleGenerate();
        });

        await waitFor(() => expect(mockNavigate).toHaveBeenCalledWith('/gallery'));
    });

    it('silently queues (no progress, no job tracking) when setGeneratingOnQueue=false', async () => {
        const { result } = renderHook(() =>
            useGeneratorJob({
                runSubmission: mockRunSubmission,
                type: 'simple',
                setGeneratingOnQueue: false,
            })
        );

        await act(async () => {
            await result.current.handleGenerate({ shouldRedirect: false, trackQueuedJob: false });
        });

        // Queue mode still submits, but does NOT track the job / navigate.
        expect(mockRunSubmission).toHaveBeenCalledTimes(1);
        expect(result.current.currentJobId).toBe(null);
        expect(toast.success).toHaveBeenCalledWith('Added to queue!', { icon: '➕' });
        expect(mockNavigate).not.toHaveBeenCalled();
        expect(result.current.generating).toBe(false);
    });

    it('flashes then resets generating state when setGeneratingOnQueue=true (Img2Img/Inpaint)', async () => {
        const { result } = renderHook(() =>
            useGeneratorJob({
                runSubmission: mockRunSubmission,
                type: 'img2img',
                setGeneratingOnQueue: true,
            })
        );

        await act(async () => {
            await result.current.handleGenerate({ shouldRedirect: false, trackQueuedJob: false });
        });

        expect(mockRunSubmission).toHaveBeenCalledTimes(1);
        // finally reset path -> generating ends false, job not tracked.
        expect(result.current.currentJobId).toBe(null);
        expect(result.current.generating).toBe(false);
        expect(toast.success).toHaveBeenCalledWith('Added to queue!', { icon: '➕' });
    });

    it('resets state and surfaces an error on submission failure', async () => {
        mockRunSubmission.mockRejectedValueOnce(new Error('provider down'));
        const { result } = renderHook(() =>
            useGeneratorJob({
                runSubmission: mockRunSubmission,
                type: 'simple',
                setGeneratingOnQueue: false,
            })
        );

        await act(async () => {
            await result.current.handleGenerate();
        });

        expect(mockRunSubmission).toHaveBeenCalledTimes(1);
        expect(toast.error).toHaveBeenCalledWith('Error: provider down');
        expect(result.current.generating).toBe(false);
        expect(result.current.progress).toBe(null);
        expect(result.current.currentJobId).toBe(null);
    });

    it('honours the validate() short-circuit', async () => {
        const { result } = renderHook(() =>
            useGeneratorJob({
                runSubmission: mockRunSubmission,
                type: 'img2img',
                validate: () => 'Please upload a source image first',
            })
        );

        await act(async () => {
            await result.current.handleGenerate();
        });

        expect(mockRunSubmission).not.toHaveBeenCalled();
        expect(toast.error).toHaveBeenCalledWith('Please upload a source image first');
    });
});

/*
 * `settings.generator.redirectDelay` was unreachable.
 *
 * The completion effect armed a timer behind a `redirectAfterGenerate` gate, and
 * `handleGenerate` navigated SYNCHRONOUSLY on submit. So the navigation that
 * actually ran had no delay, it unmounted the generator page, and the unmount
 * cleanup cleared the pending timer together with the job subscription that
 * would have fired it. No route reached the effect's gate, and the Settings
 * slider — a live, persisted, persisted-to-the-server setting — changed nothing.
 */
describe('redirectDelay', () => {
    let mockRunSubmission;

    const settings = (delay) => {
        mockUseSettingsStore.mockImplementation((sel) =>
            sel({ settings: { generator: { redirectAfterGenerate: true, redirectDelay: delay } } })
        );
    };

    beforeEach(() => {
        vi.clearAllMocks();
        mockRunSubmission = vi.fn().mockResolvedValue({
            ok: true,
            submissionResult: { id: 'job-1' },
        });
    });

    afterEach(() => {
        vi.useRealTimers();
    });

    const mount = () => renderHook(() =>
        useGeneratorJob({
            runSubmission: mockRunSubmission,
            type: 'simple',
            setGeneratingOnQueue: false,
        })
    );

    it('does NOT navigate synchronously on submit', async () => {
        vi.useFakeTimers();
        settings(1500);
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        // The pre-fix line was `if (shouldRedirect) navigate('/gallery')` right
        // here: no delay, so the setting was decorative.
        expect(mockRunSubmission).toHaveBeenCalledTimes(1);
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('navigates once, exactly one delay later', async () => {
        vi.useFakeTimers();
        settings(1500);
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        act(() => { vi.advanceTimersByTime(1499); });
        expect(mockNavigate).not.toHaveBeenCalled();

        act(() => { vi.advanceTimersByTime(1); });
        expect(mockNavigate).toHaveBeenCalledTimes(1);
        expect(mockNavigate).toHaveBeenCalledWith('/gallery');

        // Once. The completion effect used to be a second redirect site.
        act(() => { vi.advanceTimersByTime(60_000); });
        expect(mockNavigate).toHaveBeenCalledTimes(1);
    });

    it('waits the full slider value, not a hardcoded delay', async () => {
        vi.useFakeTimers();
        settings(4000);
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        act(() => { vi.advanceTimersByTime(1000); });
        expect(mockNavigate).not.toHaveBeenCalled();

        act(() => { vi.advanceTimersByTime(3000); });
        expect(mockNavigate).toHaveBeenCalledWith('/gallery');
    });

    it('redirects on a zero delay too, rather than treating it as off', async () => {
        vi.useFakeTimers();
        settings(0);
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        expect(mockNavigate).not.toHaveBeenCalled();
        act(() => { vi.advanceTimersByTime(0); });
        expect(mockNavigate).toHaveBeenCalledWith('/gallery');
    });

    it('falls back to no delay when the stored value is not a number', async () => {
        vi.useFakeTimers();
        settings('soon');
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        act(() => { vi.advanceTimersByTime(0); });
        expect(mockNavigate).toHaveBeenCalledWith('/gallery');
    });

    it('clamps a negative delay rather than arming an already-expired timer', async () => {
        vi.useFakeTimers();
        settings(-2500);
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        act(() => { vi.advanceTimersByTime(0); });
        expect(mockNavigate).toHaveBeenCalledWith('/gallery');
    });

    it('never redirects when the setting is off', async () => {
        vi.useFakeTimers();
        mockUseSettingsStore.mockImplementation((sel) =>
            sel({ settings: { generator: { redirectAfterGenerate: false, redirectDelay: 0 } } })
        );
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        act(() => { vi.advanceTimersByTime(60_000); });
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('drops the pending redirect if the page unmounts during the delay', async () => {
        // The cleanup that made the old timer unreachable is load-bearing: a user
        // who navigates away inside the delay window must not be yanked to the
        // gallery afterwards.
        vi.useFakeTimers();
        settings(3000);
        const { result, unmount } = mount();

        await act(async () => {
            await result.current.handleGenerate();
        });

        act(() => { vi.advanceTimersByTime(500); });
        unmount();

        act(() => { vi.advanceTimersByTime(60_000); });
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('is skipped when the caller passes shouldRedirect: false', async () => {
        vi.useFakeTimers();
        settings(0);
        const { result } = mount();

        await act(async () => {
            await result.current.handleGenerate({ shouldRedirect: false });
        });

        act(() => { vi.advanceTimersByTime(60_000); });
        expect(mockNavigate).not.toHaveBeenCalled();
    });

    it('leaves the hook override authoritative over the setting', async () => {
        // AdvancedGenerator passes `redirectAfterGenerate: false` so a run does
        // not tear the graph out from under the user.
        vi.useFakeTimers();
        settings(0);
        const { result } = renderHook(() =>
            useGeneratorJob({
                runSubmission: mockRunSubmission,
                type: 'advanced',
                setGeneratingOnQueue: true,
                redirectAfterGenerate: false,
            })
        );

        await act(async () => {
            await result.current.handleGenerate();
        });

        act(() => { vi.advanceTimersByTime(60_000); });
        expect(mockNavigate).not.toHaveBeenCalled();
    });
});
