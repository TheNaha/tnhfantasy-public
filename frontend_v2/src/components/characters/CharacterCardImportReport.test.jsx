import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import CharacterCardImportReport from './CharacterCardImportReport';
import { normalizeCardCompatibility } from '../../api/characterCards';

const character = { id: 'ch1', name: 'Lyra Vane' };

function renderReport(overrides = {}) {
    const props = {
        character,
        compatibility: normalizeCardCompatibility({}),
        filename: 'Lyra_Vane.png',
        onClose: vi.fn(),
        ...overrides,
    };
    render(<CharacterCardImportReport {...props} />);
    return props;
}

describe('CharacterCardImportReport', () => {
    it('shows the imported character and detected card spec', () => {
        renderReport({
            compatibility: normalizeCardCompatibility({ format: 'v2', spec: 'chara_card_v2.0', spec_version: '2.0' }),
        });

        expect(screen.getByRole('dialog')).toBeInTheDocument();
        expect(screen.getByText('Lyra Vane')).toBeInTheDocument();
        expect(screen.getByText(/Lyra_Vane\.png/)).toBeInTheDocument();
        expect(screen.getByText(/V2 · chara_card_v2\.0 · v2\.0/)).toBeInTheDocument();
    });

    it('reports a fully compatible import', () => {
        renderReport({
            compatibility: normalizeCardCompatibility({
                format: 'v3',
                lost_fields: [],
                preserved_fields: ['card_metadata'],
            }),
        });

        expect(screen.getByTestId('card-import-status')).toHaveTextContent(/Fully compatible/i);
        expect(screen.getByTestId('card-import-preserved')).toHaveTextContent('card_metadata');
        expect(screen.queryByTestId('card-import-lost')).not.toBeInTheDocument();
    });

    it('separates warnings, lost fields and preserved metadata', () => {
        renderReport({
            compatibility: normalizeCardCompatibility({
                format: 'v2',
                warnings: ['Tags were mapped to visual tags'],
                lost_fields: [{ field: 'extensions.tavern_helper', reason: 'no matching feature' }],
                preserved_fields: ['card_metadata', 'unknown_extensions'],
            }),
        });

        expect(screen.getByTestId('card-import-status')).toHaveTextContent(/Imported with warnings/i);
        expect(screen.getByTestId('card-import-warnings')).toHaveTextContent('Tags were mapped to visual tags');
        expect(screen.getByTestId('card-import-lost')).toHaveTextContent('extensions.tavern_helper');
        expect(screen.getByTestId('card-import-lost')).toHaveTextContent('no matching feature');
        expect(screen.getByTestId('card-import-preserved')).toHaveTextContent('card_metadata');
        expect(screen.getByTestId('card-import-preserved')).toHaveTextContent('unknown_extensions');
    });

    it('surfaces lorebook conversion and dropped extension metadata', () => {
        renderReport({
            compatibility: normalizeCardCompatibility({
                lorebook_converted: true,
                unknown_extensions_preserved: false,
            }),
        });

        expect(screen.getByTestId('card-import-lorebook')).toHaveTextContent(/lorebook entity/i);
        expect(screen.getByTestId('card-import-extensions-lost')).toHaveTextContent(/could not be preserved/i);
    });

    it('degrades gracefully when the backend reports nothing', () => {
        renderReport({ compatibility: normalizeCardCompatibility(null) });

        expect(screen.getByTestId('card-import-status')).toHaveTextContent(/did not report compatibility/i);
    });

    it('wires close, review and chat actions', () => {
        const props = renderReport({ onEdit: vi.fn(), onChat: vi.fn() });

        fireEvent.click(screen.getByRole('button', { name: /Review character/i }));
        expect(props.onEdit).toHaveBeenCalledWith(character);

        fireEvent.click(screen.getByRole('button', { name: /Start chat/i }));
        expect(props.onChat).toHaveBeenCalledWith(character);

        fireEvent.click(screen.getByRole('button', { name: 'Close' }));
        expect(props.onClose).toHaveBeenCalled();

        fireEvent.click(screen.getByRole('button', { name: /Close import report/i }));
        expect(props.onClose).toHaveBeenCalledTimes(2);
    });

    it('renders nothing without a character or report', () => {
        const { container } = render(
            <CharacterCardImportReport character={null} compatibility={normalizeCardCompatibility(null)} onClose={vi.fn()} />
        );
        expect(container).toBeEmptyDOMElement();
    });
});
