import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import DiagnosticsTab from './DiagnosticsTab';

/**
 * The defect this pins: the tab mounted its own `useQuery` but destructured only
 * `{ data, isLoading }`. A failed `GET /api/v2/providers/{id}/diagnostics` left
 * `data` undefined and `isLoading` false, so the tab rendered
 *
 *   Credential Ready: Missing          <- an actionable lie
 *   All diagnostics clear — no issues   <- in a GREEN panel
 *
 * on a provider whose engine was not answering at all. The operator goes to
 * rotate credentials that are fine.
 *
 * `queryErrorInvariants.test.jsx` could not see it either: its `isQueryDerived`
 * resolves `!diagLoading && !metrics` through the local alias
 * `const metrics = diagData`, which its three-hop text walk does not follow.
 */

function renderTab() {
    const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false, gcTime: 0 } },
    });
    return render(
        <QueryClientProvider client={queryClient}>
            <DiagnosticsTab
                providerId="p1"
                diagnostics={{ warnings: [], errors: [], worker: {} }}
                runtime={{ mode: 'in_process', gpu: null, version: null }}
                credentialSummary={{ ready: true, configured_fields: [] }}
                providerFailures={0}
            />
        </QueryClientProvider>
    );
}

const baseProps = {
    providerId: 'p1',
    diagnostics: { warnings: [], errors: [], worker: {} },
    runtime: { mode: 'in_process', gpu: null, version: null },
    credentialSummary: { ready: true, configured_fields: [] },
    providerFailures: 0,
};

describe('DiagnosticsTab states', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    afterEach(() => {
        vi.restoreAllMocks();
    });

    it('renders a failed probe as a failure, never as a healthy provider', async () => {
        const { providersApi } = await import('../../../api');
        vi.spyOn(providersApi, 'getDiagnostics').mockRejectedValue(
            new Error('engine unreachable')
        );

        renderTab();

        await waitFor(() => {
            expect(screen.getByRole('alert')).toBeTruthy();
        });

        // The outage is named as an outage.
        expect(
            screen.getByRole('heading', { name: /could not load your engine telemetry/i })
        ).toBeTruthy();

        // And the green panel is NOT rendered. This is the assertion that would
        // have failed before the fix: with the error branch missing, a rejected
        // query produced exactly the same pixels as a healthy one.
        expect(screen.queryByText(/all diagnostics clear/i)).toBeNull();

        // And the "treat as unverified" warning is present instead.
        expect(screen.getByText(/unverified/i)).toBeTruthy();
    });

    it('still reports a clear provider as clear when the probe answers healthy', async () => {
        const { providersApi } = await import('../../../api');
        vi.spyOn(providersApi, 'getDiagnostics').mockResolvedValue({
            engine_name: 'ModalEngine',
            runtime_mode: 'in_process',
            status: 'healthy',
            latency_ms: 42,
        });

        render(
            <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
                <DiagnosticsTab {...baseProps} />
            </QueryClientProvider>
        );

        await waitFor(() => {
            expect(screen.getByText(/all diagnostics clear/i)).toBeTruthy();
        });
        expect(screen.queryByRole('alert')).toBeNull();
    });
});
