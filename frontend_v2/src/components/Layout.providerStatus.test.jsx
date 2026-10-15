import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import useProvidersPageData from '../hooks/useProvidersPageData';
import Layout from './Layout';

vi.mock('../hooks/useProvidersPageData', () => ({
    default: vi.fn(),
}));
vi.mock('../hooks/useBranding', () => ({
    useBranding: () => ({ data: { appName: 'TNH-Comfy', logoUrl: '/logo.png' } }),
}));
vi.mock('../hooks/useKeyboardShortcuts', () => ({ useKeyboardShortcuts: () => ({}) }));
vi.mock('./GlobalCommandPalette', () => ({ default: () => null }));
vi.mock('./KeyboardShortcutsModal', () => ({ default: () => null }));

function renderLayout() {
    return render(
        <MemoryRouter>
            <Layout>
                <div>Content</div>
            </Layout>
        </MemoryRouter>
    );
}

describe('ProviderStatusPanel in Layout', () => {
    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('does not flag "needs attention" when a provider is intentionally disabled', () => {
        useProvidersPageData.mockReturnValue({
            providers: [
                {
                    id: 'modal-nhp196',
                    enabled: true,
                    runtime_state: { status: 'running', connected: true },
                    diagnostics: { warnings: [], errors: [] },
                },
                {
                    id: 'modal-zetsuke',
                    enabled: false,
                    runtime_state: { status: 'stopped', connected: false },
                    diagnostics: { warnings: [], errors: [] },
                },
            ],
            lbStats: null,
        });

        renderLayout();

        // Must NOT show "needs attention"
        expect(screen.queryByText(/needs attention/i)).not.toBeInTheDocument();

        // Must display active ratio and paused count
        expect(screen.getByText(/1\/1 online · 1 paused/i)).toBeInTheDocument();
    });

    it('displays "needs attention" only when an active/enabled provider has errors', () => {
        useProvidersPageData.mockReturnValue({
            providers: [
                {
                    id: 'modal-nhp196',
                    enabled: true,
                    runtime_state: { status: 'running', connected: true },
                    diagnostics: { warnings: [], errors: ['Connection timeout to worker'] },
                },
                {
                    id: 'modal-zetsuke',
                    enabled: false,
                    runtime_state: { status: 'stopped', connected: false },
                    diagnostics: { warnings: [], errors: [] },
                },
            ],
            lbStats: null,
        });

        renderLayout();

        // Enabled provider with error MUST trigger "needs attention"
        expect(screen.getByText(/needs attention/i)).toBeInTheDocument();
    });

    it('displays paused count without error when all providers are disabled', () => {
        useProvidersPageData.mockReturnValue({
            providers: [
                {
                    id: 'modal-nhp196',
                    enabled: false,
                    runtime_state: { status: 'stopped', connected: false },
                    diagnostics: { warnings: [], errors: [] },
                },
                {
                    id: 'modal-zetsuke',
                    enabled: false,
                    runtime_state: { status: 'stopped', connected: false },
                    diagnostics: { warnings: [], errors: [] },
                },
            ],
            lbStats: null,
        });

        renderLayout();

        expect(screen.queryByText(/needs attention/i)).not.toBeInTheDocument();
        expect(screen.getByText(/2 paused/i)).toBeInTheDocument();
    });

    it('shows "paused" tag and active pool count in expanded view', () => {
        useProvidersPageData.mockReturnValue({
            providers: [
                {
                    id: 'modal-nhp196',
                    enabled: true,
                    runtime_state: { status: 'running', connected: true },
                    diagnostics: { warnings: [], errors: [] },
                },
                {
                    id: 'modal-zetsuke',
                    enabled: false,
                    runtime_state: { status: 'stopped', connected: false },
                    diagnostics: { warnings: [], errors: [] },
                },
            ],
            lbStats: null,
        });

        renderLayout();

        // Expand status panel
        const toggleBtn = screen.getByRole('button', { name: /1\/1 online · 1 paused/i });
        fireEvent.click(toggleBtn);

        expect(screen.getByText(/System Status/i)).toBeInTheDocument();
        expect(screen.getByText('modal-nhp196')).toBeInTheDocument();
        expect(screen.getByText('modal-zetsuke')).toBeInTheDocument();
        expect(screen.getAllByText(/paused/i).length).toBeGreaterThanOrEqual(2);
        expect(screen.getAllByText(/1\/1 online/i).length).toBeGreaterThanOrEqual(1);
        expect(screen.getByText(/\(1 paused\)/i)).toBeInTheDocument();
    });
});
