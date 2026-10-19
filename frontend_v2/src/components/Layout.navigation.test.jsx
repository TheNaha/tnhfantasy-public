/**
 * The sidebar's "World" item, and which page that name means.
 *
 * There are two live pages behind two routes — `/worlds` (the worlds list) and
 * `/world-vault` (the cross-entity search hub) — and the roleplay front door's
 * "Shape a world" already pointed at `/worlds`. The one sidebar item actually
 * called "World" pointed at the search hub instead, so the app offered two
 * different destinations under the same word and the nav item was the odd one
 * out.
 */
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('../hooks/useProvidersPageData', () => ({
    default: () => ({ providers: [], lbStats: null }),
}));
vi.mock('../hooks/useBranding', () => ({
    useBranding: () => ({ data: { appName: 'TNH-Comfy', logoUrl: '/logo.png' } }),
}));
vi.mock('../hooks/useKeyboardShortcuts', () => ({ useKeyboardShortcuts: () => ({}) }));
vi.mock('./GlobalCommandPalette', () => ({ default: () => null }));
vi.mock('./KeyboardShortcutsModal', () => ({ default: () => null }));

import Layout from './Layout';

function renderLayout() {
    return render(<MemoryRouter><Layout><div /></Layout></MemoryRouter>);
}

describe('Layout sidebar — where "World" goes', () => {
    it('points at /worlds, the same page the front door calls "Shape a world"', () => {
        renderLayout();
        expect(screen.getByRole('link', { name: 'World' })).toHaveAttribute('href', '/worlds');
    });

    it('does not send the "World" nav item to the vault search hub', () => {
        renderLayout();
        const world = screen.getByRole('link', { name: 'World' });
        expect(world.getAttribute('href')).not.toContain('world-vault');
    });

    it('can collapse and expand the sidebar via toggle button', async () => {
        const { fireEvent } = await import('@testing-library/react');
        renderLayout();
        const collapseBtn = screen.getByRole('button', { name: 'Collapse sidebar' });
        expect(collapseBtn).toBeInTheDocument();

        fireEvent.click(collapseBtn);
        const expandBtn = screen.getByRole('button', { name: 'Expand sidebar' });
        expect(expandBtn).toBeInTheDocument();

        // Accessible link still resolves cleanly when collapsed
        expect(screen.getByRole('link', { name: 'World' })).toHaveAttribute('href', '/worlds');

        fireEvent.click(expandBtn);
        expect(screen.getByRole('button', { name: 'Collapse sidebar' })).toBeInTheDocument();
    });

    it('lists LLM Studio once and links the World Vault hub', async () => {
        const { fireEvent } = await import('@testing-library/react');
        renderLayout();

        expect(screen.getAllByRole('link', { name: 'LLM Studio' })).toHaveLength(1);

        fireEvent.click(screen.getByRole('button', { name: /Expert tools/i }));
        expect(screen.getByRole('link', { name: 'World Vault' })).toHaveAttribute('href', '/world-vault');
    });
});
