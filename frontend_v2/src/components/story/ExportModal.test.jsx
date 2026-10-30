/**
 * `navigator.clipboard` is `undefined` in a non-secure context.
 *
 * Measured on the documented LAN host: `http://100.150.0.4:5174` reports
 * `{"secure":false,"clip":false}` while `http://localhost:5174` reports
 * `{"secure":true,"clip":true}`. Every LAN and VPN user is on the insecure
 * side of that pair.
 *
 * The failure is nastier than a rejected promise: `navigator.clipboard
 * .writeText(...)` throws a **synchronous** `TypeError` dereferencing
 * `undefined`, before any promise exists. So
 *
 *   navigator.clipboard.writeText(x).then(ok).catch(fail)
 *
 * never reaches `.then` or `.catch` — the throw escapes the whole chain. A
 * `try { await … } catch` around it is the only thing that catches it, and only
 * if the `await` is where the call is.
 *
 * `utils/clipboard.js` already guards the property and falls back to a
 * textarea + `execCommand`. Five call sites did not use it.
 *
 * @param {string} text
 * @returns {Promise<boolean>} whether the copy actually happened
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const {
    publishStory,
    unpublishStory,
    exportFormatted,
    exportPublished,
    exportChapterComic,
    toastMock,
} = vi.hoisted(() => {
    const toast = vi.fn();
    toast.success = vi.fn();
    toast.error = vi.fn();
    return {
        publishStory: vi.fn(),
        unpublishStory: vi.fn(),
        exportFormatted: vi.fn(),
        exportPublished: vi.fn(),
        exportChapterComic: vi.fn(),
        toastMock: toast,
    };
});

vi.mock('../../hooks/useWorldVault', () => ({
    useExportStoryFormatted: () => exportFormatted(),
    useExportPublishedStory: () => exportPublished(),
    useExportChapterComic: () => exportChapterComic(),
    usePublishStory: () => publishStory(),
    useUnpublishStory: () => unpublishStory(),
}));

vi.mock('react-hot-toast', () => ({ default: toastMock }));
import ExportModal from './ExportModal';

/**
 * `ExportModal`'s publish handler was the worst of the five.
 *
 * It claimed success first, then copied:
 *
 *     toast.success('Story published — link copied!');
 *     navigator.clipboard.writeText(data.read_url || '');
 *     onClose();
 *
 * On an insecure origin the `writeText` dereference throws synchronously, so
 * `onClose()` is skipped. The modal stays open showing "Story published — link
 * copied!" with the link absent and **Publish to Web** still enabled — so the
 * next click is a **second publish** of a story that was already published.
 */
function renderModal(onClose, chapterId = 'chapter-1') {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>
                <ExportModal story={{ id: 'story-1' }} storyId="story-1" chapterId={chapterId} isOpen onClose={onClose} />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

describe('ExportModal publish on an insecure origin', () => {
    beforeEach(() => {
        vi.clearAllMocks();
        publishStory.mockReturnValue({ mutate: vi.fn(), isPending: false });
        unpublishStory.mockReturnValue({ mutate: vi.fn(), isPending: false });
        exportFormatted.mockReturnValue({ mutate: vi.fn(), isPending: false });
        exportPublished.mockReturnValue({ mutate: vi.fn(), isPending: false });
        exportChapterComic.mockReturnValue({ mutate: vi.fn(), isPending: false });
    });
    afterEach(() => { vi.unstubAllGlobals(); });

    it('closes the modal instead of stranding it on a false success', async () => {
        // Exactly what the LAN host reports: no `clipboard` property at all.
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });

        const onClose = vi.fn();
        const mutate = vi.fn();
        publishStory.mockReturnValue({ mutate, isPending: false });
        // Run the handler the way react-query does: call the supplied onSuccess
        // with the server's payload.
        mutate.mockImplementation((_vars, { onSuccess }) => {
            onSuccess({ read_url: '/read/story/abc123' });
        });

        renderModal(onClose);

        fireEvent.click(screen.getByRole('button', { name: /Publish to Web/i }));

        // The defect: `onClose` never ran, so the modal stayed open with a
        // success toast it had not earned and Publish still clickable.
        // `onSuccess` awaits the copy, so the close is not synchronous.
        await waitFor(() => expect(onClose).toHaveBeenCalledTimes(1), { timeout: 1000 });
    });

    it('reports the copy failure rather than claiming the link was copied', async () => {
        vi.stubGlobal('navigator', { ...navigator, clipboard: undefined });
        const onClose = vi.fn();
        const mutate = vi.fn();
        publishStory.mockReturnValue({ mutate, isPending: false });
        mutate.mockImplementation((_vars, { onSuccess }) => onSuccess({ read_url: '/read/story/abc' }));

        renderModal(onClose);
        fireEvent.click(screen.getByRole('button', { name: /Publish to Web/i }));

        await waitFor(() => expect(toastMock.success).toHaveBeenCalled(), { timeout: 1000 });
        expect(toastMock.success).toHaveBeenCalledWith('Story published');
        // Not "Story published — link copied!": nothing was copied.
        const messages = toastMock.success.mock.calls.map((c) => String(c[0]));
        expect(messages.some((m) => /link copied/i.test(m))).toBe(false);
    });

    it('still claims the link was copied when the clipboard works', async () => {
        const writeText = vi.fn().mockResolvedValue(undefined);
        vi.stubGlobal('navigator', { ...navigator, clipboard: { writeText } });
        const onClose = vi.fn();
        const mutate = vi.fn();
        publishStory.mockReturnValue({ mutate, isPending: false });
        mutate.mockImplementation((_vars, { onSuccess }) => onSuccess({ read_url: '/read/story/abc' }));

        renderModal(onClose);
        fireEvent.click(screen.getByRole('button', { name: /Publish to Web/i }));

        await waitFor(() => expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/read/story/abc`), { timeout: 1000 });
        expect(toastMock.success).toHaveBeenCalledWith('Story published — link copied!');
        expect(onClose).toHaveBeenCalledTimes(1);
    });
});