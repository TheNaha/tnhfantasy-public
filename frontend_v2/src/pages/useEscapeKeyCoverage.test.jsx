/**
 * "Esc → Close modals", as `KeyboardShortcutsModal.jsx:16` advertises it.
 *
 * Sixteen overlays were hand-rolled with `fixed inset-0` and no Escape
 * handling, no portal and no `role="dialog"`, while `ModalOverlay` has all
 * three and 22 consumers. This file covers every dialog that has been converted
 * to the shared contract, plus the three converted here in the pages/components
 * workstream: `SessionPanel`'s drawer, `PromptForm` and the command palette.
 * Dialogs still to convert are reported as not-done rather than half-applied.
 *
 * Every case renders the REAL component with the REAL `useEscapeKey` and fires
 * a real `keydown` on `window`, the event the hook listens for. Mocking the
 * hook would have made the suite pass whether or not the component called it —
 * which is the failure mode the 2026-09-29 and 2026-09-29b audits both found
 * elsewhere in this repo.
 */
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ModalOverlay from '../components/common/ModalOverlay';

const apiMock = vi.hoisted(() => ({
    get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn(),
}));

vi.mock('../api', async (importOriginal) => {
    const actual = await importOriginal();
    return { ...actual, api: apiMock };
});

const escape = () => fireEvent.keyDown(window, { key: 'Escape' });

function wrap(node) {
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 }, mutations: { retry: false } } });
    return render(<QueryClientProvider client={queryClient}><MemoryRouter>{node}</MemoryRouter></QueryClientProvider>);
}

beforeEach(() => {
    vi.clearAllMocks();
    apiMock.get.mockResolvedValue([]);
    localStorage.setItem('tnhfantasy_setup_complete', 'true');
});

describe('Escape closes the overlays that were converted', () => {
    it('CollectionsPanel', async () => {
        const CollectionsPanel = (await import('../components/collections/CollectionsPanel')).default;
        const onClose = vi.fn();
        wrap(<CollectionsPanel isOpen onClose={onClose} />);
        await waitFor(() => expect(screen.getByText('Collections')).toBeInTheDocument());
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('CollectionsPanel ignores Escape while it is closed', async () => {
        const CollectionsPanel = (await import('../components/collections/CollectionsPanel')).default;
        const onClose = vi.fn();
        wrap(<CollectionsPanel isOpen={false} onClose={onClose} />);
        escape();
        expect(onClose).not.toHaveBeenCalled();
    });

    it('ImageComparison', async () => {
        const { ImageComparison } = await import('../components/dashboard/ImageComparison');
        const onClose = vi.fn();
        wrap(<ImageComparison images={[]} onClose={onClose} />);
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('ProviderModal', async () => {
        const ProviderModal = (await import('../components/providers/ProviderModal')).default;
        const onClose = vi.fn();
        wrap(<ProviderModal provider={null} onClose={onClose} onSave={vi.fn()} saveProvider={vi.fn()} />);
        await waitFor(() => expect(document.body.textContent).toMatch(/provider/i));
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('AddModelToProviderModal', async () => {
        const AddModelToProviderModal = (await import('../components/providers/AddModelToProviderModal')).default;
        const onClose = vi.fn();
        wrap(<AddModelToProviderModal providers={[]} onClose={onClose} />);
        await waitFor(() => expect(document.body.textContent).toMatch(/model/i));
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('ModelImportCard', async () => {
        const ModelImportCard = (await import('../components/model-manager/ModelImportCard')).default;
        const onCancel = vi.fn();
        wrap(<ModelImportCard model={{ id: 1, name: 'x' }} onCancel={onCancel} />);
        escape();
        expect(onCancel).toHaveBeenCalled();
    });

    it('LorebookFormModal', async () => {
        const Lorebooks = (await import('./Lorebooks')).default;
        wrap(<Lorebooks />);
        await waitFor(() => expect(screen.getByText('Lorebooks')).toBeInTheDocument());
        // "New Lorebook" is both the toolbar button and the modal heading, so
        // the heading is scoped by the form's own placeholder instead.
        fireEvent.click(screen.getByRole('button', { name: /new lorebook/i }));
        await screen.findByPlaceholderText(/lorebook name/i);
        escape();
        await waitFor(() => expect(screen.queryByPlaceholderText(/lorebook name/i)).not.toBeInTheDocument());
    });

    it('Locations form', async () => {
        const Locations = (await import('./Locations')).default;
        wrap(<Locations />);
        await waitFor(() => expect(screen.getByText('Locations')).toBeInTheDocument());
        fireEvent.click(screen.getByRole('button', { name: /new location/i }));
        await waitFor(() => expect(screen.getByPlaceholderText(/location name/i)).toBeInTheDocument());
        escape();
        await waitFor(() => expect(screen.queryByPlaceholderText(/location name/i)).not.toBeInTheDocument());
    });

    it('SessionPanel drawer', async () => {
        // It declared `role="dialog"` but called `useEscapeKey` nowhere, so the
        // only way out was the backdrop. It also announced itself to assistive
        // tech as "Collections" — copy-paste residue from CollectionsPanel.
        const SessionPanel = (await import('../components/dashboard/SessionPanel')).default;
        const onClose = vi.fn();
        wrap(<SessionPanel isOpen onClose={onClose} />);
        expect(screen.getByRole('dialog', { name: 'Sessions' })).toBeInTheDocument();
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('SessionPanel drawer does not close while it is closed', async () => {
        const SessionPanel = (await import('../components/dashboard/SessionPanel')).default;
        const onClose = vi.fn();
        wrap(<SessionPanel isOpen={false} onClose={onClose} />);
        escape();
        expect(onClose).not.toHaveBeenCalled();
    });

    it('PromptForm', async () => {
        // A hand-rolled `fixed inset-0` with no backdrop click, no Escape and no
        // portal: dismissable only by its own Cancel button.
        const { PromptForm } = await import('../components/generator/PromptForm');
        const onClose = vi.fn();
        wrap(<PromptForm onClose={onClose} />);
        await waitFor(() => expect(screen.getByRole('dialog', { name: /add new prompt/i })).toBeInTheDocument());
        escape();
        expect(onClose).toHaveBeenCalled();
    });

    it('GlobalCommandPalette closes on Escape, and only closes itself over a stacked dialog', async () => {
        // The palette used to install its own `window` keydown listener and call
        // `preventDefault()` without `stopPropagation()`. `useEscapeKey` does
        // check `defaultPrevented`, so the palette's handler kept running and the
        // dialog underneath it closed too — one Escape, two dismissals.
        const GlobalCommandPalette = (await import('../components/GlobalCommandPalette')).default;
        const onClosePalette = vi.fn();
        const onCloseDialog = vi.fn();
        wrap(
            <>
                <ModalOverlay onClose={onCloseDialog} className="z-50 bg-black/80">
                    <div role="dialog" aria-label="Underneath">the dialog</div>
                </ModalOverlay>
                <GlobalCommandPalette onClose={onClosePalette} />
            </>
        );
        await waitFor(() => expect(screen.getByPlaceholderText(/jump to a page or action/i)).toBeInTheDocument());

        escape();

        expect(onClosePalette).toHaveBeenCalledTimes(1);
        expect(onCloseDialog).not.toHaveBeenCalled();
    });
});
