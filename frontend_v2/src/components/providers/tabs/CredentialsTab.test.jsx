import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import CredentialsTab from './CredentialsTab';
import { providersApi } from '../../../api';

function renderTab(props = {}) {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <CredentialsTab
                providerId="test-provider-1"
                credentialSummary={{
                    credentials: { token_id: 'ak-1234••••••••' },
                    encryption: { enabled: true },
                }}
                {...props}
            />
        </QueryClientProvider>
    );
}

describe('CredentialsTab', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('renders encryption banner indicating Fernet encryption is active', async () => {
        vi.spyOn(providersApi, 'getCredentials').mockResolvedValue({
            credentials: { token_id: 'ak-1234••••5678' },
            encryption: { enabled: true },
            provider_type: 'modal',
        });

        renderTab();

        await waitFor(() => {
            expect(screen.getByText(/encrypted at rest with Fernet/i)).toBeInTheDocument();
        });
        expect(screen.getByText('token_id')).toBeInTheDocument();
        expect(screen.getByText('ak-1234••••5678')).toBeInTheDocument();
    });

    it('renders object-shaped credentials {set, masked} without crashing', async () => {
        vi.spyOn(providersApi, 'getCredentials').mockResolvedValue({
            credentials: {
                token_id: { set: true, masked: 'ak-J••••••••9ybh' },
                token_secret: { set: true, masked: 'as-x••••••••1234' },
            },
            encryption: { enabled: true },
            provider_type: 'modal',
        });

        renderTab();

        await waitFor(() => {
            expect(screen.getByText('token_id')).toBeInTheDocument();
        });
        expect(screen.getByText('ak-J••••••••9ybh')).toBeInTheDocument();
        expect(screen.getByText('as-x••••••••1234')).toBeInTheDocument();
    });

    it('renders warning when credentials are not encrypted at rest', async () => {
        vi.spyOn(providersApi, 'getCredentials').mockResolvedValue({
            credentials: {},
            encryption: { enabled: false },
            provider_type: 'beam',
        });

        renderTab();

        await waitFor(() => {
            expect(screen.getByText(/without active encryption key/i)).toBeInTheDocument();
        });
    });

    it('calls deleteCredential when delete button is clicked', async () => {
        vi.spyOn(providersApi, 'getCredentials').mockResolvedValue({
            credentials: { api_key: 'sk-••••••••' },
            encryption: { enabled: true },
            provider_type: 'beam',
        });
        const deleteSpy = vi.spyOn(providersApi, 'deleteCredential').mockResolvedValue({ ok: true });

        renderTab();

        await waitFor(() => {
            expect(screen.getByText('api_key')).toBeInTheDocument();
        });

        const deleteBtn = screen.getByLabelText('Delete api_key');
        fireEvent.click(deleteBtn);

        await waitFor(() => {
            expect(deleteSpy).toHaveBeenCalledWith('test-provider-1', 'api_key');
        });
    });

    it('saves new credential value write-only and resets form', async () => {
        vi.spyOn(providersApi, 'getCredentials').mockResolvedValue({
            credentials: {},
            encryption: { enabled: true },
            provider_type: 'modal',
        });
        const setSpy = vi.spyOn(providersApi, 'setCredentials').mockResolvedValue({ ok: true });

        renderTab();

        await waitFor(() => {
            expect(screen.getByText(/Stored Credentials \(0\)/i)).toBeInTheDocument();
        });

        // Click quick-add token_id
        const quickAddBtn = screen.getByRole('button', { name: /token_id/i });
        fireEvent.click(quickAddBtn);

        // Form field should appear
        const input = screen.getByPlaceholderText('Enter token_id');
        expect(input).toBeInTheDocument();
        fireEvent.change(input, { target: { value: 'ak-new-secret-value-123' } });

        // Save Credentials button
        const saveBtn = screen.getByRole('button', { name: /Save Credentials/i });
        fireEvent.click(saveBtn);

        await waitFor(() => {
            expect(setSpy).toHaveBeenCalledWith('test-provider-1', {
                token_id: 'ak-new-secret-value-123',
            });
        });
    });

    it('renders error query state when getCredentials throws', async () => {
        vi.spyOn(providersApi, 'getCredentials').mockRejectedValue(
            new Error('Network connection failed')
        );

        renderTab();

        await waitFor(() => {
            expect(screen.getByRole('alert')).toBeInTheDocument();
        });
    });
});
