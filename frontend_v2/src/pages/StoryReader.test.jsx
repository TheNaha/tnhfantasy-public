import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The reader's share button on a non-secure origin.
 *
 * This one already had `try { await navigator.clipboard.writeText(...) } catch`,
 * so unlike the other four it never threw out of the handler. It was still
 * wrong: on the insecure side the `navigator.clipboard` dereference throws
 * SYNCHRONOUSLY, before the promise exists — so the catch ran only by accident
 * of the await, and the user got the generic "Could not copy link" on a device
 * where copying works perfectly well through the textarea fallback the other
 * four call sites use (measured: `http://100.150.0.4:5174` →
 * `{"secure":false,"clip":false}`).
 */

const toastMock = vi.hoisted(() => {
    const fn = vi.fn();
    fn.success = vi.fn();
    fn.error = vi.fn();
    return fn;
});

vi.mock('react-hot-toast', () => ({ default: toastMock }));
vi.mock('../api', () => ({
    api: { get: vi.fn().mockResolvedValue({ title: 'A Tale', content: 'Once upon a time' }) },
}));
vi.mock('../components/story/ExportModal', () => ({ default: () => null }));

import StoryReader from './StoryReader';

function renderReader() {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter initialEntries={['/read/tok123']}>
                <Routes>
                    <Route path="/read/:token" element={<StoryReader />} />
                </Routes>
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('StoryReader share on an insecure origin', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        // The legacy fallback, working. jsdom does not implement
        // `document.execCommand`, and a real insecure-origin browser does — it
        // is how every copy still worked before the async Clipboard API. This
        // stub is what makes the two implementations observably different; see
        // the note on the second test.
        document.execCommand = vi.fn().mockReturnValue(true);
    });
    afterEach(() => {
        vi.unstubAllGlobals();
        delete document.execCommand;
    });

    const clickShare = () => fireEvent.click(screen.getByTitle('Share link'));

    const renderLoaded = async () => {
        const utils = renderReader();
        // The header only renders once the story resolves; without this the
        // Share button does not exist yet and the query is still pending.
        await screen.findByTitle('Share link', undefined, { timeout: 2000 });
        return utils;
    };

    it('does not throw out of the click handler', async () => {
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });

        await renderLoaded();
        expect(clickShare).not.toThrow();
    });

    /**
     * The behavioural difference between the two implementations.
     *
     * `try { await navigator.clipboard.writeText(...) } catch` cannot succeed on
     * an insecure origin no matter what the browser supports: the dereference
     * throws before any promise exists, so the catch always runs and the user
     * always gets "Could not copy link". The textarea fallback does work there,
     * so routing through `copyToClipboard` is the difference between a button
     * that is dead on the LAN and one that copies.
     *
     * With `execCommand` stubbed to succeed, the old code still reports failure
     * and the fixed code reports success.
     */
    it('succeeds through the legacy fallback instead of reporting a false failure', async () => {
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });

        await renderLoaded();
        clickShare();

        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Link copied!'), { timeout: 2000 });
        expect(toastMock.error).not.toHaveBeenCalled();
        expect(document.execCommand).toHaveBeenCalledWith('copy');
    });

    it('copies the current URL and confirms when the clipboard works', async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });

        await renderLoaded();
        clickShare();

        await waitFor(() => expect(toastMock.success).toHaveBeenCalledWith('Link copied!'), { timeout: 2000 });
        expect(writeText).toHaveBeenCalledWith(window.location.href);
        // The async API is preferred; the fallback is not used when it works.
        expect(document.execCommand).not.toHaveBeenCalled();
    });

    it('reports a genuine failure when neither route works', async () => {
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });
        document.execCommand = vi.fn().mockImplementation(() => { throw new Error('denied'); });

        await renderLoaded();
        clickShare();

        await waitFor(() => expect(toastMock.error).toHaveBeenCalledWith('Could not copy link'), { timeout: 2000 });
    });
});