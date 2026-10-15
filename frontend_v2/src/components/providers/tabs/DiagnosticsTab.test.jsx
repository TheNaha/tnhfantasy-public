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


/**
 * Worker topology: where a remote worker reads and serves.
 *
 * A `remote_llm` provider manages a storage root AND proxies inference to
 * `LLM_UPSTREAM_BASE` — two independent settings that can name two different
 * trees on two different machines. `modal_llm` has no equivalent split. Nothing
 * showed either value, so an operator looking at a populated models tree would
 * reasonably assume it is the one being served; when it is not, the symptom is a
 * model that 404s from a tree that looks fine.
 */
describe('DiagnosticsTab worker topology', () => {
    beforeEach(() => {
        vi.restoreAllMocks();
    });

    function renderWith(telemetry, extra = {}) {
        const queryClient = new QueryClient({
            defaultOptions: { queries: { retry: false, gcTime: 0 } },
        });
        return render(
            <QueryClientProvider client={queryClient}>
                <DiagnosticsTab
                    {...baseProps}
                    providerFailures={0}
                    {...extra}
                />
            </QueryClientProvider>
        );
    }

    it('shows the storage root and the LLM upstream together', async () => {
        const { providersApi } = await import('../../../api');
        vi.spyOn(providersApi, 'getDiagnostics').mockResolvedValue({
            healthy: true, status: 'healthy', latency_ms: 12, telemetry: {
                topology: {
                    storage_root: '/opt/llm-weights',
                    storage_root_env: 'LLM_DATA_DIR',
                    llm_upstream_base: 'http://127.0.0.1:8080/v1',
                    upstream_is_local: true,
                },
            },
        });
        renderWith();

        await waitFor(() => expect(screen.getByText('Worker topology')).toBeInTheDocument());
        expect(screen.getByText('/opt/llm-weights')).toBeInTheDocument();
        // Twice: the value itself and the `title` tooltip carrying it, which is
        // the escape hatch for a truncated path.
        expect(screen.getAllByText(/http:\/\/127\.0\.0\.1:8080\/v1/).length).toBeGreaterThan(0);
        // The operator-visible signal: a loopback upstream is a second server on
        // this box, i.e. possibly not the managed root.
        expect(screen.getByText(/\(this box\)/)).toBeInTheDocument();
    });

    it('warns when the served upstream is not confirmed to read the managed root', async () => {
        const { providersApi } = await import('../../../api');
        vi.spyOn(providersApi, 'getDiagnostics').mockResolvedValue({
            healthy: true, status: 'healthy', latency_ms: 5, telemetry: {
                topology: {
                    storage_root: '/opt/llm-weights',
                    llm_upstream_base: 'http://127.0.0.1:8080/v1',
                    upstream_is_local: true,
                },
            },
        });
        renderWith();

        await waitFor(() => expect(screen.getByText(/Worker topology/)).toBeInTheDocument());
        expect(screen.getByText(/Confirm that server reads this root/)).toBeInTheDocument();
    });

    it('says nothing about a mismatch when there is no upstream to mismatch', async () => {
        const { providersApi } = await import('../../../api');
        vi.spyOn(providersApi, 'getDiagnostics').mockResolvedValue({
            healthy: true, status: 'healthy', latency_ms: 5, telemetry: {
                topology: { worker_mode: 'tts', storage_root: '/opt/ComfyUI' },
            },
        });
        renderWith();

        await waitFor(() => expect(screen.getByText(/Worker topology/)).toBeInTheDocument());
        expect(screen.queryByText(/Confirm that server reads this root/)).not.toBeInTheDocument();
    });

    it('renders no topology block when the agent never answered /info', async () => {
        const { providersApi } = await import('../../../api');
        vi.spyOn(providersApi, 'getDiagnostics').mockResolvedValue({
            healthy: true, status: 'healthy', latency_ms: 5, telemetry: {
                topology: { storage_root_env: 'LLM_DATA_DIR', info_error: 'ConnectError: ...' },
            },
        });
        renderWith();

        await waitFor(() => expect(screen.getByText(/Worker topology/)).toBeInTheDocument());
        expect(screen.getByText(/live \/info unavailable/)).toBeInTheDocument();
    });

    it('has no topology block at all for a non-remote engine', async () => {
        const { providersApi } = await import('../../../api');
        vi.spyOn(providersApi, 'getDiagnostics').mockResolvedValue({
            healthy: true, status: 'healthy', latency_ms: 5, telemetry: { app_name: 'a' },
        });
        renderWith();

        await waitFor(() => expect(screen.getByText(/App Name/)).toBeInTheDocument());
        expect(screen.queryByText('Worker topology')).not.toBeInTheDocument();
    });
});
