import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * The chat surface's two hand-rolled full-screen overlays.
 *
 * `ChatWorkspace.jsx` rendered the avatar viewer as a bare
 * `fixed inset-0 z-[100]` div with a backdrop click and *no* Escape handling —
 * so the one dismissal `KeyboardShortcutsModal.jsx:16` advertises ("Esc → Close
 * modals") did nothing on it, and the viewer could only be closed with a mouse.
 * The Scenes gallery was the mirror image: it answered Escape (a hand-rolled
 * `useEscapeKey`) but its backdrop had no click-to-close, unlike every other
 * dialog in the app.
 *
 * Both now go through `ModalOverlay`, which brings the portal, the
 * `role="dialog"`, the backdrop click and the Escape registry together. The
 * `z-[100]` / `z-[60]` stacking intent is preserved as a class override, because
 * the avatar viewer has to sit above the Scenes dialog.
 *
 * Every case fires a real `keydown` on `window` with the real `useEscapeKey`;
 * mocking the hook would have made this suite pass whether or not the component
 * ever called it.
 */

const apiMock = vi.hoisted(() => ({
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, api: apiMock };
});

const mockActiveChatId = vi.hoisted(() => vi.fn(() => 'chat-1'));
vi.mock('../store/worldVaultStore', () => ({
    useWorldVaultStore: (sel) => sel({ activeChatId: mockActiveChatId(), setActiveChat: vi.fn() }),
}));

vi.mock('../hooks/useStreamingJobs', () => ({
    useActiveChatStreams: vi.fn(() => []),
    setStreamingJob: vi.fn(),
    clearStreamingJob: vi.fn(),
    getStreamingJob: vi.fn(() => undefined),
}));

vi.mock('../hooks/useCollections', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useCollections: () => ({ data: {} }), useAddImagesToCollection: () => ({ mutateAsync: vi.fn() }) };
});

vi.mock('../api/collectionsApi', () => ({ addImagesToCollection: vi.fn() }));
vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: vi.fn().mockResolvedValue(true) }),
    useConfirmationStore: { getState: vi.fn(), setState: vi.fn() },
}));
vi.mock('react-hot-toast', () => ({
    default: { success: vi.fn(), error: vi.fn(), promise: vi.fn() },
}));
vi.mock('react-router-dom', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, useNavigate: () => vi.fn() };
});

vi.mock('../hooks/useWorldVault', async (importOriginal) => {
    const actual = await importOriginal();
    return {
        ...actual,
        useChats: () => ({ data: [{ id: 'chat-1', name: 'Test Chat', character_id: 'char-1' }], isLoading: false }),
        useMessages: () => ({ data: [], isLoading: false }),
        useCharacters: () => ({ data: [{ id: 'char-1', name: 'Ada', avatar_path: 'ada.png' }], isLoading: false }),
        useChat: () => ({ data: { id: 'chat-1', name: 'Test Chat', character_id: 'char-1' } }),
        useChatImages: () => ({ data: [], isError: false, error: null, refetch: vi.fn() }),
        useCharacterCollection: () => ({ data: { images: [], image_count: 0 }, isError: false, error: null, refetch: vi.fn() }),
        useBranches: () => ({ data: [], isLoading: false }),
        useWorlds: () => ({ data: [] }),
        usePersonas: () => ({ data: [] }),
        useLorebooks: () => ({ data: [], isLoading: false }),
    };
});

import ChatWorkspace from './ChatWorkspace';

// jsdom has no layout engine; the message list scrolls itself into view on mount.
Element.prototype.scrollIntoView = vi.fn();

const escape = () => fireEvent.keyDown(window, { key: 'Escape' });

function renderWorkspace() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <MemoryRouter>
                <ChatWorkspace />
            </MemoryRouter>
        </QueryClientProvider>
    );
}

beforeEach(() => {
    vi.clearAllMocks();
    mockActiveChatId.mockReturnValue('chat-1');
});

describe('ChatWorkspace avatar viewer', () => {
    async function openAvatarViewer() {
        const user = renderWorkspace();
        fireEvent.click(await screen.findByRole('button', { name: /view ada's avatar/i }));
        return user;
    }

    it('is a labelled dialog once open', async () => {
        await openAvatarViewer();
        const dialogs = screen.getAllByRole('dialog');
        expect(dialogs.some((d) => /ada avatar/i.test(d.getAttribute('aria-label') || ''))).toBe(true);
    });

    it('closes on Escape, which it previously ignored', async () => {
        await openAvatarViewer();
        expect(screen.getAllByRole('dialog').length).toBeGreaterThan(0);

        escape();

        await waitFor(() => {
            const labels = screen.queryAllByRole('dialog').map((d) => d.getAttribute('aria-label') || '');
            expect(labels.some((l) => /ada avatar/i.test(l))).toBe(false);
        });
    });

    it('keeps the z-[100] stacking intent above the Scenes dialog', async () => {
        await openAvatarViewer();
        // The overlay shell, not the portal root: ModalOverlay renders its own
        // `z-50` and the caller overrides it, and that override is the stacking
        // intent the avatar viewer needs over the Scenes dialog at `z-[60]`.
        const shells = [...document.querySelectorAll('[data-modal-overlay]')];
        expect(shells.some((el) => el.className.includes('z-[100]'))).toBe(true);
    });

    it('still closes on a backdrop click', async () => {
        await openAvatarViewer();

        fireEvent.click(document.querySelector('[data-modal-overlay]'));

        await waitFor(() => {
            const labels = screen.queryAllByRole('dialog').map((d) => d.getAttribute('aria-label') || '');
            expect(labels.some((l) => /ada avatar/i.test(l))).toBe(false);
        });
    });
});

describe('ChatWorkspace Scenes gallery', () => {
    async function openScenesGallery() {
        const user = renderWorkspace();
        const button = await screen.findByRole('button', { name: /scenes/i });
        fireEvent.click(button);
        return user;
    }

    it('closes on a backdrop click, which it previously lacked', async () => {
        await openScenesGallery();
        await screen.findByRole('button', { name: /close scenes gallery/i });

        fireEvent.click(document.querySelector('[data-modal-overlay]'));

        await waitFor(() => {
            expect(screen.queryByRole('button', { name: /close scenes gallery/i })).toBeNull();
        });
    });

    it('closes on Escape', async () => {
        await openScenesGallery();
        await screen.findByRole('button', { name: /close scenes gallery/i });

        escape();

        await waitFor(() => {
            expect(screen.queryByRole('button', { name: /close scenes gallery/i })).toBeNull();
        });
    });
});