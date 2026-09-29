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
});
