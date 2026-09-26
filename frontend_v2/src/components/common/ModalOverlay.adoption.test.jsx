import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import ModalOverlay from './ModalOverlay';
import CharacterCardImportReport from '../characters/CharacterCardImportReport';
import CharacterDetailsModal from '../chat/CharacterDetailsModal';
import GreetingPickerModal from '../chat/GreetingPickerModal';
import NewChatModal from '../chat/NewChatModal';
import KeyboardShortcutsModal from '../KeyboardShortcutsModal';
import ImageLightbox from '../dashboard/ImageLightbox';
import JobDetailsModal from '../dashboard/JobDetailsModal';
import ModelDetailsModal from '../model-manager/ModelDetailsModal';
import CivitaiSearchModal from '../model-manager/CivitaiSearchModal';

/**
 * Behavioural contract for the dialogs converted to <ModalOverlay>.
 *
 * Grouped by mounting class rather than one test per dialog: every dialog in a
 * class shares the same lifecycle shape, so the same three properties are
 * asserted once per class (closes on Escape / inert while closed / only the
 * topmost of a stack reacts).
 */

vi.mock('../ProgressiveImage', () => ({ default: () => <img data-testid="mock-image" alt="" /> }));
vi.mock('../../api', () => ({
    api: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn().mockResolvedValue({}) },
    default: { get: vi.fn().mockResolvedValue({ items: [] }), post: vi.fn().mockResolvedValue({}) },
}));

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });

const character = {
    id: 'c1',
    name: 'Elara Moonwhisper',
    description: 'Elven sorceress',
    first_mes: 'Greetings, traveller.',
    alternate_greetings: ['Well met.', 'Ah, a stranger.'],
};

/** Dialogs that are mounted only while they are open (`{isOpen && <Dialog/>}`). */
const mountedOnlyWhileOpen = [
    {
        name: 'CharacterCardImportReport',
        open: (onClose) => (
            <CharacterCardImportReport
                character={character}
                compatibility={{ hasReport: true, warnings: [], lost: [], preserved: [] }}
                filename="Elara.png"
                onClose={onClose}
            />
        ),
    },
    {
        name: 'CharacterDetailsModal',
        open: (onClose) => <CharacterDetailsModal character={character} onClose={onClose} />,
    },
    {
        name: 'GreetingPickerModal',
        open: (onClose) => (
            <GreetingPickerModal character={character} onSelect={vi.fn()} onClose={onClose} />
        ),
    },
    {
        name: 'NewChatModal',
        open: (onClose) => (
            <NewChatModal characters={[character]} lorebooks={[]} onCreate={vi.fn()} onClose={onClose} />
        ),
    },
    {
        name: 'ImageLightbox',
        open: (onClose) => (
            <ImageLightbox image={{ name: 'a.png' }} images={[]} onClose={onClose} />
        ),
    },
    {
        name: 'JobDetailsModal',
        open: (onClose) => <JobDetailsModal job={{ id: 'job-1', status: 'pending' }} onClose={onClose} />,
    },
];

describe('converted dialogs: mounted only while open', () => {
    it.each(mountedOnlyWhileOpen.map((d) => [d.name, d]))('%s closes on Escape', (name, dialog) => {
        const onClose = vi.fn();
        render(dialog.open(onClose));
        expect(screen.getByRole('dialog')).toBeInTheDocument();

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it.each(mountedOnlyWhileOpen.map((d) => [d.name, d]))('%s renders nothing and binds no listener when closed', (name, dialog) => {
        const onClose = vi.fn();
        const { unmount } = render(dialog.open(onClose));
        unmount();

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).not.toHaveBeenCalled();
    });

    it('closes only the topmost dialog when two are stacked', () => {
        const onCloseOuter = vi.fn();
        const onCloseInner = vi.fn();

        render(
            <>
                <CharacterDetailsModal character={character} onClose={onCloseOuter} />
                <NewChatModal characters={[character]} lorebooks={[]} onCreate={vi.fn()} onClose={onCloseInner} />
            </>
        );

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onCloseInner).toHaveBeenCalledTimes(1);
        expect(onCloseOuter).not.toHaveBeenCalled();
    });
});

describe('converted dialogs: mounted unconditionally with an isOpen prop', () => {
    it('closes on Escape while open', () => {
        const onClose = vi.fn();
        render(<KeyboardShortcutsModal isOpen onClose={onClose} />);
        expect(screen.getByRole('dialog')).toBeInTheDocument();

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('renders nothing and does not respond to Escape while closed', () => {
        const onClose = vi.fn();
        const { container } = render(<KeyboardShortcutsModal isOpen={false} onClose={onClose} />);
        expect(container).toBeEmptyDOMElement();

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).not.toHaveBeenCalled();
    });

    it('stays out of the Escape registry until it is open', () => {
        const onHidden = vi.fn();
        const onShown = vi.fn();

        const { rerender } = render(<KeyboardShortcutsModal isOpen={false} onClose={onHidden} />);
        rerender(
            <>
                <KeyboardShortcutsModal isOpen onClose={onShown} />
            </>
        );

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onShown).toHaveBeenCalledTimes(1);
        expect(onHidden).not.toHaveBeenCalled();
    });

    it('only the topmost of a stack reacts', () => {
        const onUnder = vi.fn();
        const onTop = vi.fn();

        render(
            <>
                <KeyboardShortcutsModal isOpen onClose={onTop} />
                <ModalOverlay onClose={onUnder} className="z-50 bg-black/80">
                    <div role="dialog">stacked on top</div>
                </ModalOverlay>
            </>
        );

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onUnder).toHaveBeenCalledTimes(1);
        expect(onTop).not.toHaveBeenCalled();
    });
});

describe('converted dialogs: portal-heavy model dialogs', () => {
    function renderInQuery(ui) {
        return render(<QueryClientProvider client={queryClient}>{ui}</QueryClientProvider>);
    }

    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('ModelDetailsModal closes on Escape', () => {
        const onClose = vi.fn();
        renderInQuery(<ModelDetailsModal file={{ name: 'sdxl.safetensors', type: 'Checkpoint' }} onClose={onClose} />);

        expect(screen.getByRole('dialog')).toBeInTheDocument();
        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).toHaveBeenCalledTimes(1);
    });

    it('ModelDetailsModal renders nothing without a file', () => {
        const onClose = vi.fn();
        const { container } = renderInQuery(<ModelDetailsModal file={null} onClose={onClose} />);
        expect(container).toBeEmptyDOMElement();

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onClose).not.toHaveBeenCalled();
    });

    it('CivitaiSearchModal closes on Escape and the model dialog behind it survives', () => {
        const onCloseSearch = vi.fn();
        const onCloseDetails = vi.fn();
        renderInQuery(
            <>
                <ModelDetailsModal
                    file={{ name: 'sdxl.safetensors', type: 'Checkpoint', model_id: 7 }}
                    onClose={onCloseDetails}
                />
                <CivitaiSearchModal initialQuery="sdxl" onClose={onCloseSearch} onSelect={vi.fn()} />
            </>
        );

        fireEvent.keyDown(window, { key: 'Escape' });
        expect(onCloseSearch).toHaveBeenCalledTimes(1);
        expect(onCloseDetails).not.toHaveBeenCalled();
    });

    it('CivitaiSearchModal keeps its search form and results after a rejected Escape', async () => {
        renderInQuery(<CivitaiSearchModal initialQuery="sdxl" onClose={vi.fn()} onSelect={vi.fn()} />);
        await waitFor(() => expect(screen.getByText('Search CivitAI')).toBeInTheDocument());

        fireEvent.keyDown(window, { key: 'Escape' });

        expect(screen.getByText('Search CivitAI')).toBeInTheDocument();
    });
});
