import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import CharacterCardSpecBadge from './CharacterCardSpecBadge';

describe('CharacterCardSpecBadge', () => {
    it('renders nothing for a character without card provenance', () => {
        const { container } = render(<CharacterCardSpecBadge character={{ id: 'ch1', name: 'Alice' }} />);
        expect(container).toBeEmptyDOMElement();
    });

    it('shows the source card spec', () => {
        render(
            <CharacterCardSpecBadge
                character={{ id: 'ch1', card_spec: 'chara_card_v3', card_spec_version: '3.0' }}
            />
        );
        const badge = screen.getByTestId('card-spec-badge');
        expect(badge).toHaveTextContent('V3 · 3.0 card');
        expect(screen.getByTitle(/chara_card_v3/)).toBeInTheDocument();
    });

    it('lists the preserved card metadata groups in the tooltip', () => {
        render(
            <CharacterCardSpecBadge
                character={{
                    id: 'ch1',
                    card_spec: 'chara_card_v2',
                    card_metadata: {
                        root: { creator_notes: 'hi' },
                        data: { assets: { a: 1 }, extensions: { tavern_helper: {} } },
                    },
                }}
            />
        );

        expect(screen.getByTestId('card-spec-badge')).toHaveTextContent('V2 card');
        expect(screen.getByText('3 metadata groups')).toBeInTheDocument();
        const tooltip = screen.getByTitle(/Preserved data\.extensions/);
        expect(tooltip).toHaveAttribute('title', expect.stringContaining('Preserved root: creator_notes'));
        expect(tooltip.getAttribute('title')).toContain('Preserved data.extensions: tavern_helper');
    });

    it('flags an embedded character book that was kept as metadata', () => {
        render(
            <CharacterCardSpecBadge
                character={{ id: 'ch1', card_metadata: { data: { character_book: { entries: [] } } } }}
            />
        );
        expect(screen.getByText('1 metadata group')).toBeInTheDocument();
        expect(screen.getByTitle(/embedded lorebook/)).toBeInTheDocument();
    });
});
