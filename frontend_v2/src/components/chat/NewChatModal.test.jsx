import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import NewChatModal from './NewChatModal';

const LOCATIONS = [
    { id: 'loc-1', name: 'The Docks', atmosphere: 'Salt and tar' },
    { id: 'loc-2', name: 'The Rookery' },
];

const PERSONAS = [{ id: 'p-1', name: 'Wanderer' }];

const WORLDS = [{ id: 'w-1', name: 'Emberfall' }];

function renderModal(props = {}) {
    const onCreate = vi.fn().mockResolvedValue({});
    render(<NewChatModal characters={[]} lorebooks={[]} locations={LOCATIONS} personas={[]} onCreate={onCreate} onClose={() => {}} {...props} />);
    return { onCreate };
}

const goToStep = (name) => fireEvent.click(screen.getByRole('button', { name }));

const finish = async (onCreate) => {
    // Advance whatever step the wizard is on, so a test that already stepped
    // forward itself does not click Continue off the end.
    while (screen.queryByRole('button', { name: 'Continue' })) {
        fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
    }
    fireEvent.click(screen.getByRole('button', { name: 'Create chat' }));
    await waitFor(() => expect(onCreate).toHaveBeenCalled());
    return onCreate.mock.calls[0][0];
};

describe('NewChatModal', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('walks the beginner chat flow before creating', async () => {
        const { onCreate } = renderModal();
        expect(screen.getByRole('heading', { name: 'Create New Chat' })).toBeInTheDocument();
        goToStep('Continue');
        expect(screen.getByText('Character (Optional)')).toBeInTheDocument();
        goToStep('Continue');
        expect(screen.getByText('No lorebooks yet. You can add one later from the World page.')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('button', { name: 'Create chat' }));

        await waitFor(() => expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ chatName: 'New Chat' })));
    });
});

describe('NewChatModal — one persona control, not two', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('picking a library persona sends persona_id and no name', async () => {
        const { onCreate } = renderModal({ personas: PERSONAS });
        fireEvent.change(screen.getByTestId('new-chat-persona-select'), { target: { value: 'p-1' } });
        const config = await finish(onCreate);
        expect(config.personaId).toBe('p-1');
        expect(config.personaName).toBeNull();
    });

    it('a custom name clears the library persona, so the server precedence is explicit', async () => {
        const { onCreate } = renderModal({ personas: PERSONAS });
        const select = screen.getByTestId('new-chat-persona-select');
        fireEvent.change(select, { target: { value: 'p-1' } });
        fireEvent.change(select, { target: { value: '__custom__' } });
        fireEvent.change(screen.getByTestId('new-chat-persona-name'), { target: { value: 'Ilse' } });

        const config = await finish(onCreate);
        // `context_builder.py` resolves `persona_name or persona.name`, so a name
        // typed alongside a library persona wins silently. These two are
        // mutually exclusive here, and the escape hatch says so.
        expect(config.personaName).toBe('Ilse');
        expect(config.personaId).toBeNull();
    });

    it('never shows a name field beside a library persona', () => {
        // The two controls used to be siblings on this step: a free-text name
        // AND a library select, with nothing making them exclusive, so
        // `persona_name = persona_name or persona.name` decided the winner
        // silently. There is now exactly one control, and the escape is a
        // choice in it.
        renderModal({ personas: PERSONAS });
        const select = screen.getByTestId('new-chat-persona-select');
        expect(screen.queryByTestId('new-chat-persona-name')).not.toBeInTheDocument();

        fireEvent.change(select, { target: { value: 'p-1' } });
        expect(screen.queryByTestId('new-chat-persona-name')).not.toBeInTheDocument();

        fireEvent.change(select, { target: { value: '__custom__' } });
        expect(screen.getByTestId('new-chat-persona-name')).toBeInTheDocument();
    });

    it('states the precedence in the UI rather than leaving it to be discovered', () => {
        renderModal({ personas: PERSONAS });
        expect(screen.getByText(/your typed name wins/i)).toBeInTheDocument();
        expect(screen.getByText(/clears the library link/i)).toBeInTheDocument();
    });
});

describe('NewChatModal — a real location picker', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('writes location_id AND the matching free text, so both prompt blocks work', async () => {
        const { onCreate } = renderModal();
        goToStep('Continue');
        fireEvent.change(screen.getByTestId('new-chat-location-select'), { target: { value: 'loc-2' } });

        const config = await finish(onCreate);
        expect(config.locationId).toBe('loc-2');
        // `story_location` is what the Activity page's location filter compares
        // against and what becomes the prompt's `Current Location:` line.
        expect(config.storyLocation).toBe('The Rookery');
    });

    it('keeps a free-text escape for a place that does not exist yet', async () => {
        const { onCreate } = renderModal();
        goToStep('Continue');
        fireEvent.change(screen.getByTestId('new-chat-location-select'), { target: { value: '__custom__' } });
        fireEvent.change(screen.getByTestId('new-chat-location-name'), { target: { value: 'The Sunken Stair' } });

        const config = await finish(onCreate);
        expect(config.storyLocation).toBe('The Sunken Stair');
        expect(config.locationId).toBeNull();
    });

    it('lists the library as the primary control, not a text box', () => {
        renderModal();
        goToStep('Continue');
        const select = screen.getByTestId('new-chat-location-select');
        const options = [...select.querySelectorAll('option')].map(o => o.textContent);
        expect(options).toEqual(['No location', 'The Docks', 'The Rookery', 'Custom / free text…']);
        // and the text box only exists once you ask for it
        expect(screen.queryByTestId('new-chat-location-name')).not.toBeInTheDocument();
    });
});

describe('NewChatModal — the world picker is revisitable', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('offers the worlds and promises the world can be changed afterwards', () => {
        renderModal({ worlds: WORLDS });
        goToStep('Continue');
        const select = screen.getByTestId('new-chat-world-select');
        expect([...select.querySelectorAll('option')].map(o => o.textContent)).toEqual(['No World', 'Emberfall']);
        expect(screen.getByText(/change or drop it later/i)).toBeInTheDocument();
    });
});
