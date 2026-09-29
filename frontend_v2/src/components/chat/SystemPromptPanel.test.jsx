/**
 * What `system_prompt_override` actually is, and who writes it.
 *
 * `Chat.system_prompt_override` used to be written by two things — this tab and
 * `Scenarios → Apply` — and the only place it was visible was a textarea behind
 * a 1.5px badge dot, so a user who applied a scenario and came back had no way
 * to see it had changed anything.
 *
 * The backend half is fixed too: `Scenarios → Apply` now writes
 * `append_system_prompt`, because the override *replaces* the character card
 * and one click on that page was silently deleting a character's description,
 * personality, system prompt, extra instructions and example dialogue from every
 * later turn. The override keeps its replace-semantics for this tab, which is
 * what the field is for.
 *
 * It also matters *what* it does: `context_builder.py` documents the override as
 * replacing the character card entirely, while this panel's own help text said it
 * was "appended after the character's core instructions". The tests below pin the
 * real behaviour, because "it only appends" is the belief that makes a user
 * comfortable leaving an override in place.
 */
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import SystemPromptPanel from './SystemPromptPanel';

function renderPanel(chat = {}, extra = {}) {
    const onChatUpdate = vi.fn();
    render(
        <SystemPromptPanel
            activeChat={{ id: 'chat-1', ...chat }}
            linkedCharacter={null}
            systemPromptData={{ sections: [] }}
            onChatUpdate={onChatUpdate}
            onCharacterPatch={vi.fn()}
            {...extra}
        />
    );
    return { onChatUpdate };
}

describe('SystemPromptPanel — override provenance', () => {
    it('says who writes the override and what it does, whenever one is set', () => {
        renderPanel({ system_prompt_override: 'You are a barkeep.' });
        const note = screen.getByTestId('override-provenance');
        expect(note).toHaveTextContent(/replaces the character card entirely/i);
        expect(note).toHaveTextContent(/Scenarios/);
    });

    it('shows no provenance note when there is no override at all', () => {
        renderPanel({});
        expect(screen.queryByTestId('override-provenance')).not.toBeInTheDocument();
    });

    it('corrects the help text: the override is not appended to the character card', () => {
        renderPanel({ system_prompt_override: 'You are a barkeep.' });
        fireEvent.click(screen.getByRole('button', { name: /chat prompt/i }));
        const help = screen.getByText(/Chat System Prompt/i).closest('p');
        expect(help.textContent).toMatch(/not additive/i);
        expect(help.textContent).toMatch(/character card and the character’s extra instructions are left out/i);
        // The old, wrong sentence must be gone.
        expect(screen.queryByText(/appended after the character's core instructions/i)).not.toBeInTheDocument();
    });

    it('can still be cleared from the header', () => {
        const { onChatUpdate } = renderPanel({ system_prompt_override: 'You are a barkeep.' });
        fireEvent.click(screen.getByRole('button', { name: /clear override/i }));
        expect(onChatUpdate).toHaveBeenCalledWith({ system_prompt_override: null });
    });
});
