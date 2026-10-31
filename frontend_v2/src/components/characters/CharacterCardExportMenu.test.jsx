import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import CharacterCardExportMenu from './CharacterCardExportMenu';

// The menu reads the export preview, so it needs a query client and a
// network that answers.
vi.mock('../../api', () => ({
    api: {
        get: vi.fn().mockResolvedValue({
            character_id: 'ch1',
            name: 'Lyra Vane',
            formats: ['default', 'v2', 'v3', 'json', 'charx', 'bundle'],
            not_portable: [
                { name: 'Expression images', field: 'expressions', detail: '3 expression(s): angry, happy, sad' },
                { name: 'World membership', field: 'world_id', detail: "belongs to the world 'The Bridge'" },
            ],
            not_portable_summary: 'Expression images and World membership',
            lossless: false,
        }),
    },
}));

const character = { id: 'ch1', name: 'Lyra Vane' };

function renderMenu(props = {}) {
    const onExport = props.onExport || vi.fn();
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
    });
    render(
        <QueryClientProvider client={queryClient}>
            <CharacterCardExportMenu character={character} onExport={onExport} {...props} />
        </QueryClientProvider>
    );
    return { onExport, trigger: screen.getByRole('button', { name: /export card for lyra vane/i }) };
}

describe('CharacterCardExportMenu', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('keeps the menu closed until triggered', () => {
        renderMenu();
        expect(screen.queryByTestId('card-export-menu')).not.toBeInTheDocument();

        fireEvent.click(screen.getByRole('button', { name: /export card for lyra vane/i }));
        expect(screen.getByTestId('card-export-menu')).toBeInTheDocument();
    });

    it('offers every export option, the bundle first among the new ones', () => {
        const { trigger } = renderMenu();
        fireEvent.click(trigger);

        const items = screen.getAllByRole('menuitem');
        expect(items.map((el) => el.textContent)).toEqual([
            expect.stringContaining('Default PNG'),
            expect.stringContaining('V2 PNG'),
            expect.stringContaining('V3 PNG'),
            expect.stringContaining('JSON'),
            expect.stringContaining('CHARX'),
            expect.stringContaining('TNHFantasy bundle'),
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

    it('passes the chosen sections with a bundle export', () => {
        const { onExport, trigger } = renderMenu();

        fireEvent.click(trigger);
        fireEvent.click(screen.getByRole('menuitem', { name: /TNHFantasy bundle/ }));
        expect(onExport).toHaveBeenCalledWith(
            character,
            'bundle',
            expect.arrayContaining(['expressions', 'world'])
        );
    });

    it('says what a card cannot carry', async () => {
        const { trigger } = renderMenu();
        fireEvent.click(trigger);

        const notice = await screen.findByTestId('card-export-not-portable');
        expect(notice).toHaveTextContent('A card cannot carry');
        expect(notice).toHaveTextContent('Expression images');
        expect(notice).toHaveTextContent('World membership');
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
