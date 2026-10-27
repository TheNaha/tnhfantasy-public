import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import ModelImportCard from './ModelImportCard';
import { api } from '../../api';

vi.mock('../../api', () => ({
    api: {
        post: vi.fn(),
    },
}));

vi.mock('../../hooks/useCivitaiSearch', () => ({
    useCheckInstalledVersions: () => ({ data: [1001] }), // 1001 is installed, 1002 & 1003 are not
}));

describe('ModelImportCard multi-version import', () => {
    const mockModel = {
        id: 9999,
        name: 'Lazy Embeddings Pack',
        type: 'TextualInversion',
        modelVersions: [
            {
                id: 1001,
                name: 'lazypos',
                baseModel: 'Illustrious',
                files: [{ primary: true, sizeKB: 200 }],
                images: [],
            },
            {
                id: 1002,
                name: 'lazyneg',
                baseModel: 'Illustrious',
                files: [{ primary: true, sizeKB: 200 }],
                images: [],
            },
            {
                id: 1003,
                name: 'lazyhand',
                baseModel: 'Illustrious',
                files: [{ primary: true, sizeKB: 200 }],
                images: [],
            },
        ],
    };

    beforeEach(() => {
        vi.clearAllMocks();
    });

    it('renders version selector chips and highlights installed status', () => {
        render(<ModelImportCard model={mockModel} onCancel={vi.fn()} />);

        expect(screen.getByText('Lazy Embeddings Pack')).toBeInTheDocument();
        // Check chips
        expect(screen.getByText('lazypos')).toBeInTheDocument();
        expect(screen.getByText('lazyneg')).toBeInTheDocument();
        expect(screen.getByText('lazyhand')).toBeInTheDocument();
        // Since 1001 is installed and selected by default, main button shows installed
        expect(screen.getByText('lazypos Installed')).toBeInTheDocument();
        // Shows Install All button with 2 uninstalled versions
        expect(screen.getByText('Install All (2 new)')).toBeInTheDocument();
    });

    it('installs all uninstalled versions when clicking Install All', async () => {
        api.post.mockResolvedValueOnce({ success: true });
        const onCancel = vi.fn();
        render(<ModelImportCard model={mockModel} onCancel={onCancel} />);

        const installAllBtn = screen.getByText('Install All (2 new)');
        fireEvent.click(installAllBtn);

        expect(api.post).toHaveBeenCalledWith('/api/v2/models/', {
            civitai_data: mockModel,
            selected_versions: [
                { version_id: 1002, is_default: false },
                { version_id: 1003, is_default: false },
            ],
        });
    });
});
