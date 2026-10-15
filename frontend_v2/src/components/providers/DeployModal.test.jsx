import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import DeployModal from './DeployModal';
import { providersApi } from '../../api';

describe('DeployModal', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('renders dialog with targets and starts deploy when submitted', async () => {
        const deploySpy = vi.spyOn(providersApi, 'deploy').mockResolvedValue({
            target: 'image',
            artifact: 'comfy-modal-stack',
            ok: true,
            exit_code: 0,
            elapsed_seconds: 14.2,
            output: 'Building image...\nSuccess: deployed to Modal.',
        });

        render(
            <DeployModal
                isOpen={true}
                onClose={vi.fn()}
                initialTarget="image"
                providers={[{ id: 'modal-p1', type: 'modal', worker_type: 'image' }]}
            />
        );

        expect(screen.getByRole('dialog', { name: /Deploy Cloud Worker/i })).toBeInTheDocument();
        expect(screen.getByText(/Modal ComfyUI \(Image\)/i)).toBeInTheDocument();

        // Click Start Deploy
        const startBtn = screen.getByRole('button', { name: /Start Deploy/i });
        fireEvent.click(startBtn);

        await waitFor(() => {
            expect(deploySpy).toHaveBeenCalledWith({
                target: 'image',
                dry_run: false,
                timeout: 300,
            });
        });

        // Verifies output and status badge are rendered
        await waitFor(() => {
            expect(screen.getByText(/Deployment Succeeded/i)).toBeInTheDocument();
            expect(screen.getByText(/Building image\.\.\./i)).toBeInTheDocument();
        });
    });

    it('displays error and exit code when deployment fails', async () => {
        vi.spyOn(providersApi, 'deploy').mockResolvedValue({
            target: 'beam',
            artifact: 'All four Beam apps',
            ok: false,
            exit_code: 1,
            elapsed_seconds: 5.1,
            output: 'Error: BEAM_API_KEY is not set.',
        });

        render(
            <DeployModal
                isOpen={true}
                onClose={vi.fn()}
                initialTarget="beam"
            />
        );

        const startBtn = screen.getByRole('button', { name: /Start Deploy/i });
        fireEvent.click(startBtn);

        await waitFor(() => {
            expect(screen.getByText(/Deployment Failed/i)).toBeInTheDocument();
            expect(screen.getByText(/Exit 1/i)).toBeInTheDocument();
            expect(screen.getByText(/Error: BEAM_API_KEY is not set\./i)).toBeInTheDocument();
        });
    });

    it('passes dry_run flag and selected provider_id when configured', async () => {
        const deploySpy = vi.spyOn(providersApi, 'deploy').mockResolvedValue({
            target: 'llm',
            artifact: 'tnh-llm',
            ok: true,
            exit_code: 0,
            elapsed_seconds: 1.0,
            output: 'Dry run check: ok',
        });

        render(
            <DeployModal
                isOpen={true}
                onClose={vi.fn()}
                initialTarget="llm"
                providers={[{ id: 'p-modal-llm', type: 'modal_llm', worker_type: 'llm' }]}
            />
        );

        // Toggle dry run checkbox
        const dryRunCheck = screen.getByRole('checkbox');
        fireEvent.click(dryRunCheck);
        expect(dryRunCheck).toBeChecked();

        // Select provider
        const select = screen.getByRole('combobox');
        fireEvent.change(select, { target: { value: 'p-modal-llm' } });

        const startBtn = screen.getByRole('button', { name: /Start Deploy/i });
        fireEvent.click(startBtn);

        await waitFor(() => {
            expect(deploySpy).toHaveBeenCalledWith({
                target: 'llm',
                provider_id: 'p-modal-llm',
                dry_run: true,
                timeout: 300,
            });
        });
    });
});
