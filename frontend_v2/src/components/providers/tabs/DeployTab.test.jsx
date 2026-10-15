import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DeployTab from './DeployTab';
import { providersApi } from '../../../api';

function renderDeployTab(provider) {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <DeployTab provider={provider} />
        </QueryClientProvider>
    );
}

describe('DeployTab', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('renders serverless worker summary and persisted output', async () => {
        vi.spyOn(providersApi, 'getLogs').mockResolvedValue({
            provider_id: 'modal-zetsuke',
            deploy: {
                target: 'image',
                artifact: 'comfy-modal-stack',
                transport: 'modal',
                elapsed_seconds: 12.4,
                ok: true,
                exit_code: 0,
                timestamp: '2026-10-15T10:00:00Z',
                output: '==> Modal image worker (comfy-modal-stack)\nok modal credentials present\nok all requested targets deployed',
            },
        });

        renderDeployTab({ id: 'modal-zetsuke', type: 'modal' });

        await waitFor(() => {
            expect(screen.getByText(/Modal ComfyUI \(Image\)/i)).toBeInTheDocument();
            expect(screen.getAllByText(/comfy-modal-stack/i).length).toBeGreaterThan(0);
            expect(screen.getByText(/all requested targets deployed/i)).toBeInTheDocument();
            expect(screen.getByText(/Exit 0/i)).toBeInTheDocument();
        });
    });

    it('triggers deployStream on button click and renders live output chunks', async () => {
        vi.spyOn(providersApi, 'getLogs').mockResolvedValue({
            provider_id: 'modal-zetsuke',
            deploy: null,
        });
        const deploySpy = vi.spyOn(providersApi, 'deployStream').mockImplementation(async (payload, { onChunk, onFinish }) => {
            onChunk('==> Building container...\n');
            onChunk('ok modal credentials present\n');
            onFinish({
                target: 'image',
                artifact: 'comfy-modal-stack',
                ok: true,
                exit_code: 0,
                elapsed_seconds: 5.0,
                output: '==> Building container...\nok modal credentials present\n',
            });
        });

        renderDeployTab({ id: 'modal-zetsuke', type: 'modal' });

        await waitFor(() => {
            expect(screen.getByRole('button', { name: /Deploy Modal Worker/i })).toBeInTheDocument();
        });

        fireEvent.click(screen.getByRole('button', { name: /Deploy Modal Worker/i }));

        await waitFor(() => {
            expect(deploySpy).toHaveBeenCalledWith(
                {
                    target: 'image',
                    dry_run: false,
                    provider_id: 'modal-zetsuke',
                },
                expect.any(Object)
            );
            expect(screen.getByText(/Building container/i)).toBeInTheDocument();
            expect(screen.getByText(/Exit 0/i)).toBeInTheDocument();
        });
    });

    it('supports dry run flag in deployStream call', async () => {
        vi.spyOn(providersApi, 'getLogs').mockResolvedValue({
            provider_id: 'modal-zetsuke',
            deploy: null,
        });
        const deploySpy = vi.spyOn(providersApi, 'deployStream').mockImplementation(async (payload, { onChunk, onFinish }) => {
            onChunk('dry run: not deploying\n');
            onFinish({
                target: 'image',
                dry_run: true,
                artifact: 'comfy-modal-stack',
                ok: true,
                exit_code: 0,
                elapsed_seconds: 1.0,
                output: 'dry run: not deploying\n',
            });
        });

        renderDeployTab({ id: 'modal-zetsuke', type: 'modal' });

        const dryRunCheckbox = screen.getByRole('checkbox');
        fireEvent.click(dryRunCheckbox);

        const deployBtn = screen.getByRole('button', { name: /Pre-flight Check/i });
        fireEvent.click(deployBtn);

        await waitFor(() => {
            expect(deploySpy).toHaveBeenCalledWith(
                {
                    target: 'image',
                    dry_run: true,
                    provider_id: 'modal-zetsuke',
                },
                expect.any(Object)
            );
        });
    });

    it('renders non-serverless message for non-deployable providers', () => {
        renderDeployTab({ id: 'direct-comfy', type: 'direct_url' });

        expect(screen.getByText(/Not a Serverless Provider/i)).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: /Deploy/i })).not.toBeInTheDocument();
    });
});
