import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import CharacterCardExportMenu from './CharacterCardExportMenu';

const character = { id: 'ch1', name: 'Lyra Vane' };

function renderMenu(props = {}) {
    const onExport = props.onExport || vi.fn();
    render(<CharacterCardExportMenu character={character} onExport={onExport} {...props} />);
    return { onExport, trigger: screen.getByRole('button', { name: /export card for lyra vane/i }) };
}

describe('CharacterCardExportMenu', () => {
    it('keeps the menu closed until triggered', () => {
        renderMenu();
        expect(screen.queryByTestId('card-export-menu')).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /export card for lyra vane/i }));
        expect(screen.getByTestId('card-export-menu')).toBeInTheDocument();
    });

    it('offers default, V2, V3, JSON and CHARX export options', () => {
        const { trigger } = renderMenu();
        fireEvent.click(trigger);

        const items = screen.getAllByRole('menuitem');
        expect(items.map((el) => el.textContent)).toEqual([
            expect.stringContaining('Default PNG'),
            expect.stringContaining('V2 PNG'),
            expect.stringContaining('V3 PNG'),
            expect.stringContaining('JSON'),
            expect.stringContaining('CHARX'),
        ]);
        expect(items[0].textContent).toContain('default');
    });

    it('reports the selected format and closes', () => {
        const { onExport, trigger } = renderMenu();

        fireEvent.click(trigger);
        fireEvent.click(screen.getByRole('menuitem', { name: /V3 PNG/ }));
        expect(onExport).toHaveBeenCalledWith(character, 'v3');
        expect(screen.queryByTestId('card-export-menu')).not.toBeInTheDocument();

        fireEvent.click(trigger);
        fireEvent.click(screen.getByRole('menuitem', { name: /JSON/ }));
        expect(onExport).toHaveBeenLastCalledWith(character, 'json');

        fireEvent.click(trigger);
        fireEvent.click(screen.getByRole('menuitem', { name: /V2 PNG/ }));
        expect(onExport).toHaveBeenLastCalledWith(character, 'v2');

        fireEvent.click(trigger);
        fireEvent.click(screen.getByRole('menuitem', { name: /CHARX/ }));
        expect(onExport).toHaveBeenLastCalledWith(character, 'charx');

        fireEvent.click(trigger);
        fireEvent.click(screen.getByRole('menuitem', { name: /Default PNG/ }));
        expect(onExport).toHaveBeenLastCalledWith(character, 'default');
        expect(onExport).toHaveBeenCalledTimes(5);
    });

    it('closes on Escape and on outside clicks', () => {
        const { trigger } = renderMenu();

        fireEvent.click(trigger);
        fireEvent.keyDown(document, { key: 'Escape' });
        expect(screen.queryByTestId('card-export-menu')).not.toBeInTheDocument();

        fireEvent.click(trigger);
        fireEvent.mouseDown(document.body);
        expect(screen.queryByTestId('card-export-menu')).not.toBeInTheDocument();
    });

    it('does not open while disabled', () => {
        renderMenu({ disabled: true });
        const trigger = screen.getByRole('button', { name: /export card for lyra vane/i });
        expect(trigger).toBeDisabled();
        fireEvent.click(trigger);
        expect(screen.queryByTestId('card-export-menu')).not.toBeInTheDocument();
    });
});
