import { renderHook, act } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
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
        expect(mockNavigate).toHaveBeenCalledWith('/');
        expect(randomizeSeed).toHaveBeenCalled();
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
