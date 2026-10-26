import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi } from 'vitest';
import Voices from './Voices';

vi.mock('../hooks/useWorldVault', () => ({
    useVoices: () => ({ data: [], isLoading: false, isError: false }),
    useWorlds: () => ({ data: [] }),
    useVoicePresets: () => ({
        data: [
            { id: 'friendly', name: 'Friendly', description: 'Warm tone' },
            { id: 'calm', name: 'Calm', description: 'Relaxed presence' },
        ],
    }),
    useCreateVoice: () => ({ mutate: vi.fn() }),
    useUpdateVoice: () => ({ mutate: vi.fn() }),
    useDeleteVoice: () => ({ mutate: vi.fn() }),
    useVoicePreview: () => ({ mutateAsync: vi.fn() }),
    useDesignVoice: () => ({ mutateAsync: vi.fn(), isPending: false }),
}));

vi.mock('../hooks/useJobStatus', () => ({
    useJobStatus: () => ({ data: null }),
}));

vi.mock('../store/confirmationStore', () => ({
    useConfirmation: () => ({ confirm: vi.fn() }),
}));

vi.mock('@tanstack/react-query', () => ({
    useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

describe('Voices Page', () => {
    it('renders page shell and create button', () => {
        render(
            <MemoryRouter>
                <Voices />
            </MemoryRouter>
        );
        expect(screen.getByText('Voice Models')).toBeInTheDocument();
        expect(screen.getByText('Design with AI')).toBeInTheDocument();
        expect(screen.getAllByText('Create Voice').length).toBeGreaterThanOrEqual(1);
    });

    it('opens create form with qwen3_tts default and no xtts options', () => {
        render(
            <MemoryRouter>
                <Voices />
            </MemoryRouter>
        );
        const createButtons = screen.getAllByText('Create Voice');
        fireEvent.click(createButtons[0]);

        const select = screen.getByLabelText('Type');
        expect(select.value).toBe('qwen3_tts');

        const options = Array.from(select.querySelectorAll('option')).map((o) => o.value);
        expect(options).toEqual(['qwen3_tts', 'qwen3_preset', 'clone']);
        expect(options).not.toContain('xtts');
        expect(options).not.toContain('other');
    });

    it('shows preset selector when qwen3_preset is chosen', () => {
        render(
            <MemoryRouter>
                <Voices />
            </MemoryRouter>
        );
        const createButtons = screen.getAllByText('Create Voice');
        fireEvent.click(createButtons[0]);

        const select = screen.getByLabelText('Type');
        fireEvent.change(select, { target: { value: 'qwen3_preset' } });

        expect(screen.getByLabelText('Preset Voice')).toBeInTheDocument();
        expect(screen.getByText(/Friendly — Warm tone/)).toBeInTheDocument();
        expect(screen.getByText(/Calm — Relaxed presence/)).toBeInTheDocument();
    });
});
