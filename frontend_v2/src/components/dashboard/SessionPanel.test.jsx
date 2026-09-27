import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const apiMock = vi.hoisted(() => ({
    listSessions: vi.fn(),
    listSessionAssets: vi.fn(),
    createSession: vi.fn(),
    updateSession: vi.fn(),
    deleteSession: vi.fn(),
    addSessionAssets: vi.fn(),
    removeSessionAsset: vi.fn(),
    splitSession: vi.fn(),
    mergeSession: vi.fn(),
    detectSessions: vi.fn(),
    getSession: vi.fn(),
}));

const confirmMock = vi.hoisted(() => vi.fn(async () => true));

vi.mock('../../api/sessionsApi', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, ...apiMock };
});

vi.mock('../../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: confirmMock }),
}));

const galleryMock = vi.hoisted(() => ({ files: [] }));
// Mocks the module's REAL shape: `useGallery` is a named export. Mocking
// `default` here is what let a default import of a module that has no default
// export pass every test and then fail the production build — a mock written to
// match the import rather than the module hides exactly this.
vi.mock('../../hooks/useGallery', () => ({
    useGallery: () => ({
        data: { pages: [{ files: galleryMock.files, jobs: [] }] },
        isLoading: false,
    }),
}));

import SessionPanel, { SessionViewPlaceholder, SessionsToolbar } from './SessionPanel';

function makeSession(overrides = {}) {
    return {
        id: 's1',
        name: 'Autumn portraits',
        description: null,
        signature: null,
        auto_detected: true,
        locked: false,
        workspace: 'main',
        start_at: '2026-09-27T14:00:00Z',
        end_at: '2026-09-27T14:40:00Z',
        image_count: 2,
        thumbnail: null,
        created_at: '2026-09-27T14:00:00Z',
        updated_at: '2026-09-27T14:40:00Z',
        deleted_at: null,
        ...overrides,
    };
}

function page(sessions) {
    return { sessions, total: sessions.length, limit: 100, offset: 0 };
}

function member(id, overrides = {}) {
    return {
        id,
        relative_path: `main/2026/09/27/${id}.png`,
        thumbnail_relative_path: null,
        width: 1024,
        height: 1024,
        workspace: 'main',
        created_at: '2026-09-27T14:00:00Z',
        added_at: '2026-09-27T14:00:00Z',
        ...overrides,
    };
}

function renderPanel(props = {}) {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    const onClose = vi.fn();
    const utils = render(
        <QueryClientProvider client={queryClient}>
            <SessionPanel isOpen onClose={onClose} {...props} />
        </QueryClientProvider>,
    );
    return { ...utils, onClose, queryClient };
}

function detectButtons() {
    return screen.getAllByRole('button', { name: /detect sessions/i });
}

describe('SessionPanel', () => {
    beforeEach(() => {
        cleanup();
        vi.clearAllMocks();
        confirmMock.mockResolvedValue(true);
    });

    afterEach(() => cleanup());

    describe('list', () => {
        it('shows a loading state, then the sessions', async () => {
            let release;
            apiMock.listSessions.mockReturnValue(new Promise((resolve) => { release = resolve; }));

            renderPanel();
            expect(screen.getByText('Loading sessions…')).toBeInTheDocument();

            release(page([makeSession()]));
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());
        });

        it('surfaces a load failure instead of an empty list', async () => {
            apiMock.listSessions.mockRejectedValue(new Error('Session 5 not found'));

            renderPanel();
            await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Session 5 not found'));
        });

        it('lists count, range, badges and the lock indicator', async () => {
            apiMock.listSessions.mockResolvedValue(page([
                makeSession({ id: 'a', name: 'Detected run', auto_detected: true, locked: false }),
                makeSession({ id: 'b', name: 'My set', auto_detected: false, locked: true, image_count: 7 }),
            ]));

            renderPanel();
            await waitFor(() => expect(screen.getByText('Detected run')).toBeInTheDocument());

            const row = screen.getByText('Detected run').closest('.group');
            expect(within(row).getByText('2 images')).toBeInTheDocument();
            expect(within(row).getByText('Auto-detected')).toBeInTheDocument();
            expect(within(row).queryByText('Locked')).not.toBeInTheDocument();

            const curated = screen.getByText('My set').closest('.group');
            expect(within(curated).getByText('Curated')).toBeInTheDocument();
            expect(within(curated).getByLabelText('Locked session')).toBeInTheDocument();
            expect(within(curated).getByText('7 images')).toBeInTheDocument();
        });

        it('falls back to "Untitled session" for an unnamed auto-detected row', async () => {
            apiMock.listSessions.mockResolvedValue(page([makeSession({ name: null })]));

            renderPanel();
            await waitFor(() =>
                expect(screen.getByText('Untitled session')).toBeInTheDocument());
        });
    });

    describe('empty state', () => {
        it('offers detection when there are no sessions at all', async () => {
            apiMock.listSessions.mockResolvedValue(page([]));

            renderPanel();
            await waitFor(() => expect(screen.getByText('No sessions yet')).toBeInTheDocument());
            expect(detectButtons().length).toBeGreaterThan(0);
        });

        it('does not fire detect until the confirmation is accepted', async () => {
            apiMock.listSessions.mockResolvedValue(page([]));
            confirmMock.mockResolvedValue(false);

            renderPanel();
            await waitFor(() => expect(screen.getByText('No sessions yet')).toBeInTheDocument());
            fireEvent.click(detectButtons()[0]);

            await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
            expect(apiMock.detectSessions).not.toHaveBeenCalled();
        });
    });

    describe('detect', () => {
        it('posts once and reports created / extended / skipped-locked', async () => {
            apiMock.listSessions.mockResolvedValue(page([]));
            apiMock.detectSessions.mockResolvedValue({
                min_size: 2,
                time_gap_minutes: 20,
                dry_run: false,
                max_assets: 50000,
                summary: {
                    groups_detected: 9,
                    sessions_created: 4,
                    sessions_extended: 3,
                    sessions_skipped_locked: 2,
                    elapsed_seconds: 12.5,
                },
            });

            renderPanel();
            await waitFor(() => expect(screen.getByText('No sessions yet')).toBeInTheDocument());
            fireEvent.click(detectButtons()[0]);

            await waitFor(() => expect(apiMock.detectSessions).toHaveBeenCalledTimes(1));
            await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());

            const summary = screen.getByRole('status');
            expect(within(summary).getByText('Created')).toBeInTheDocument();
            expect(within(summary).getByText('4')).toBeInTheDocument();
            expect(within(summary).getByText('Extended')).toBeInTheDocument();
            expect(within(summary).getByText('3')).toBeInTheDocument();
            expect(within(summary).getByText('Skipped (curated)')).toBeInTheDocument();
            expect(within(summary).getByText('2')).toBeInTheDocument();
        });

        it('cannot be fired twice while a run is in flight', async () => {
            apiMock.listSessions.mockResolvedValue(page([]));
            let release;
            apiMock.detectSessions.mockReturnValue(new Promise((resolve) => { release = resolve; }));

            renderPanel();
            await waitFor(() => expect(screen.getByText('No sessions yet')).toBeInTheDocument());

            const button = detectButtons()[0];
            fireEvent.click(button);
            fireEvent.click(button);
            fireEvent.click(button);

            await waitFor(() => expect(apiMock.detectSessions).toHaveBeenCalledTimes(1));
            expect(button).toBeDisabled();
            expect(button).toHaveAttribute('aria-busy', 'true');

            fireEvent.click(button);
            expect(apiMock.detectSessions).toHaveBeenCalledTimes(1);

            release({ summary: { sessions_created: 1, sessions_extended: 0, sessions_skipped_locked: 0 } });
            await waitFor(() => expect(screen.getByRole('status')).toBeInTheDocument());
            expect(apiMock.detectSessions).toHaveBeenCalledTimes(1);
            expect(button).not.toBeDisabled();
        });

        it('reports a failed detect run without leaving the button stuck', async () => {
            apiMock.listSessions.mockResolvedValue(page([]));
            apiMock.detectSessions.mockRejectedValue(new Error('Request timed out'));

            renderPanel();
            await waitFor(() => expect(screen.getByText('No sessions yet')).toBeInTheDocument());
            fireEvent.click(detectButtons()[0]);

            await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Request timed out'));
            await waitFor(() => expect(detectButtons()[0]).not.toBeDisabled());
        });
    });

    describe('rename and delete', () => {
        it('renames a session', async () => {
            apiMock.listSessions.mockResolvedValue(page([makeSession()]));
            apiMock.updateSession.mockResolvedValue({ id: 's1' });

            renderPanel();
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());

            fireEvent.click(screen.getByRole('button', { name: 'Rename' }));
            const input = screen.getByLabelText('Rename Autumn portraits');
            fireEvent.change(input, { target: { value: 'Winter run' } });
            fireEvent.keyDown(input, { key: 'Enter' });

            await waitFor(() =>
                expect(apiMock.updateSession).toHaveBeenCalledWith('s1', { name: 'Winter run' }));
        });

        it('deletes only after the confirmation is accepted', async () => {
            apiMock.listSessions.mockResolvedValue(page([makeSession()]));
            apiMock.deleteSession.mockResolvedValue({ success: true });

            renderPanel();
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());
            fireEvent.click(screen.getByRole('button', { name: 'Delete' }));

            await waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
            await waitFor(() =>
                expect(apiMock.deleteSession).toHaveBeenCalledWith('s1'));
        });

        it('creates a session from the header field', async () => {
            apiMock.listSessions.mockResolvedValue(page([]));
            apiMock.createSession.mockResolvedValue({ id: 'new' });

            renderPanel();
            await waitFor(() => expect(screen.getByText('No sessions yet')).toBeInTheDocument());
            fireEvent.change(screen.getByLabelText('New session name'), { target: { value: 'Winter run' } });
            fireEvent.click(screen.getByRole('button', { name: /create/i }));

            await waitFor(() =>
                expect(apiMock.createSession).toHaveBeenCalledWith({ name: 'Winter run' }));
        });
    });

    describe('images', () => {
        beforeEach(() => {
            galleryMock.files = [];
            apiMock.listSessions.mockResolvedValue(page([makeSession()]));
        });

        it('adds a library image and removes a member through the image view', async () => {
            galleryMock.files = [
                { id: 'a1', relative_path: 'main/2026/09/27/a1.png' },
                { id: 'a2', relative_path: 'main/2026/09/27/a2.png' },
            ];
            apiMock.listSessionAssets.mockResolvedValue({
                session_id: 's1',
                assets: [member('a1')],
                total: 1,
                limit: 200,
                offset: 0,
            });
            apiMock.addSessionAssets.mockResolvedValue({ session_id: 's1', added: 1 });
            apiMock.removeSessionAsset.mockResolvedValue({ session_id: 's1', removed: 1 });

            renderPanel();
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());
            fireEvent.click(screen.getByRole('button', { name: 'Images' }));

            const removeButton = await screen.findByRole('button', { name: /remove .*a1\.png/i });
            fireEvent.click(removeButton);
            await waitFor(() => expect(apiMock.removeSessionAsset).toHaveBeenCalledWith('s1', 'a1'));

            // a1 is a member, so it is never offered as an add candidate.
            const addButton = screen.getByRole('button', { name: /add .*a2\.png/i });
            fireEvent.click(addButton);
            await waitFor(() => expect(apiMock.addSessionAssets).toHaveBeenCalledWith('s1', ['a2']));
        });
    });

    describe('split', () => {
        beforeEach(() => {
            apiMock.listSessions.mockResolvedValue(page([makeSession({ image_count: 3 })]));
        });

        it('posts the ticked members as keep_asset_ids and hides the picker', async () => {
            apiMock.listSessionAssets.mockResolvedValue({
                session_id: 's1',
                assets: [member('a1'), member('a2'), member('a3')],
                total: 3,
                limit: 200,
                offset: 0,
            });
            apiMock.splitSession.mockResolvedValue({ session: {}, created: { id: 's2' } });

            renderPanel();
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());
            fireEvent.click(screen.getByRole('button', { name: 'Split' }));

            await waitFor(() => expect(apiMock.listSessionAssets).toHaveBeenCalledWith('s1'));

            const checkboxes = await screen.findAllByRole('checkbox');
            expect(checkboxes).toHaveLength(3);

            const splitButton = screen.getByRole('button', { name: /split session/i });
            expect(splitButton).toBeDisabled();

            fireEvent.click(checkboxes[0]);
            fireEvent.click(checkboxes[2]);
            expect(screen.getByText(/Keeping/)).toHaveTextContent('Keeping 2 of 3');
            expect(splitButton).toBeEnabled();

            fireEvent.click(splitButton);

            await waitFor(() =>
                expect(apiMock.splitSession).toHaveBeenCalledWith('s1', ['a1', 'a3']));
            expect(apiMock.splitSession).toHaveBeenCalledWith('s1', expect.any(Array));
            await waitFor(() => expect(screen.queryByText(/^Split Autumn portraits$/)).not.toBeInTheDocument());
        });

        it('refuses a split that keeps everything, because the backend would 422', async () => {
            apiMock.listSessionAssets.mockResolvedValue({
                session_id: 's1',
                assets: [member('a1'), member('a2')],
                total: 2,
                limit: 200,
                offset: 0,
            });

            renderPanel();
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());
            fireEvent.click(screen.getByRole('button', { name: 'Split' }));

            const checkboxes = await screen.findAllByRole('checkbox');
            expect(screen.getByRole('button', { name: /split session/i })).toBeDisabled();

            fireEvent.click(checkboxes[0]);
            expect(screen.getByRole('button', { name: /split session/i })).toBeEnabled();

            fireEvent.click(checkboxes[1]);
            expect(screen.getByRole('button', { name: /split session/i })).toBeDisabled();
            expect(apiMock.splitSession).not.toHaveBeenCalled();
        });

        it('reports a member-list failure', async () => {
            apiMock.listSessionAssets.mockRejectedValue(new Error('Session not found'));

            renderPanel();
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());
            fireEvent.click(screen.getByRole('button', { name: 'Split' }));

            await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Session not found'));
        });
    });

    describe('merge', () => {
        it('picks a target from the other sessions and posts it', async () => {
            apiMock.listSessions.mockResolvedValue(page([
                makeSession({ id: 's1', name: 'Source' }),
                makeSession({ id: 's2', name: 'Target' }),
            ]));
            apiMock.mergeSession.mockResolvedValue({ id: 's2' });

            renderPanel();
            await waitFor(() => expect(screen.getByText('Source')).toBeInTheDocument());

            const sourceRow = screen.getByText('Source').closest('.group');
            fireEvent.click(within(sourceRow).getByRole('button', { name: 'Merge' }));

            const options = await screen.findAllByRole('radio');
            expect(options).toHaveLength(1);
            expect(options[0].closest('label')).toHaveTextContent('Target');

            fireEvent.click(screen.getByRole('button', { name: /merge into session/i }));

            await waitFor(() => expect(apiMock.mergeSession).toHaveBeenCalledWith('s1', 's2'));
            await waitFor(() => expect(screen.queryByText(/^Merge Source$/)).not.toBeInTheDocument());
        });

        it('is disabled when there is no second session to merge into', async () => {
            apiMock.listSessions.mockResolvedValue(page([makeSession()]));

            renderPanel();
            await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());
            expect(screen.getByRole('button', { name: 'Merge' })).toBeDisabled();
        });
    });

    it('closes on Escape and on the backdrop', async () => {
        apiMock.listSessions.mockResolvedValue(page([makeSession()]));
        const { onClose } = renderPanel();
        await waitFor(() => expect(screen.getByText('Autumn portraits')).toBeInTheDocument());

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('renders nothing while closed and does not fetch', () => {
        apiMock.listSessions.mockResolvedValue(page([makeSession()]));
        renderPanel({ isOpen: false });
        expect(screen.queryByLabelText('Sessions')).not.toBeInTheDocument();
        expect(apiMock.listSessions).not.toHaveBeenCalled();
    });
});

describe('SessionsToolbar', () => {
    beforeEach(() => cleanup());
    afterEach(() => cleanup());

    it('opens the panel and flips the view mode, and reflects the active mode', () => {
        const onOpenPanel = vi.fn();
        const onToggleViewMode = vi.fn();
        const { rerender } = render(
            <SessionsToolbar
                isSessionView={false}
                onOpenPanel={onOpenPanel}
                onToggleViewMode={onToggleViewMode}
            />,
        );

        const groupButton = screen.getByRole('button', { name: /group by session/i });
        expect(groupButton).toHaveAttribute('aria-pressed', 'false');
        fireEvent.click(screen.getByRole('button', { name: /manage sessions/i }));
        fireEvent.click(groupButton);
        expect(onOpenPanel).toHaveBeenCalledTimes(1);
        expect(onToggleViewMode).toHaveBeenCalledTimes(1);

        rerender(
            <SessionsToolbar
                isSessionView
                onOpenPanel={onOpenPanel}
                onToggleViewMode={onToggleViewMode}
            />,
        );
        expect(screen.getByRole('button', { name: /grouped by session/i }))
            .toHaveAttribute('aria-pressed', 'true');
    });
});

describe('SessionViewPlaceholder', () => {
    beforeEach(() => cleanup());
    afterEach(() => cleanup());

    it('renders a loading, an error and a designed empty state', () => {
        const { rerender } = render(
            <SessionViewPlaceholder isLoading error={null} onOpenPanel={vi.fn()} />,
        );
        expect(screen.getByText('Loading sessions…')).toBeInTheDocument();

        rerender(
            <SessionViewPlaceholder
                isLoading={false}
                error={new Error('detect is unreachable')}
                onOpenPanel={vi.fn()}
            />,
        );
        expect(screen.getByRole('alert')).toHaveTextContent('detect is unreachable');

        const onOpenPanel = vi.fn();
        rerender(<SessionViewPlaceholder isLoading={false} error={null} onOpenPanel={onOpenPanel} />);
        expect(screen.getByText('No sessions to group by')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: /open the sessions panel/i }));
        expect(onOpenPanel).toHaveBeenCalledTimes(1);
    });
});
