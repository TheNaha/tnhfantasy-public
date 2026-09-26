import { renderHook, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createElement } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('../api', () => ({
    jobsApi: {
        validate: vi.fn(),
    },
}));

function renderWithClient(ui) {
    const queryClient = new QueryClient();
    const wrapper = ({ children }) =>
        createElement(QueryClientProvider, { client: queryClient }, children);
    return renderHook(ui, { wrapper });
}

describe('useGenerationPreflight', () => {
    let jobsApi;
    let useGenerationPreflight;

    beforeEach(async () => {
        vi.resetModules();

        const apiMod = await import('../api');
        jobsApi = apiMod.jobsApi;

        const hookMod = await import('./useGenerationPreflight');
        useGenerationPreflight = hookMod.useGenerationPreflight;
    });

    it('opens missing-model dialog and skips submission when validation fails', async () => {
        const validationResult = {
            valid: false,
            global_missing: {
                checkpoints: ['missing-model.safetensors'],
            },
            eligible_providers: [],
        };
        const onValid = vi.fn();
        const onInvalid = vi.fn();

        jobsApi.validate.mockResolvedValue(validationResult);

        const { result } = renderWithClient(() => useGenerationPreflight());

        let submission;
        await act(async () => {
            submission = await result.current.runWithPreflight(
                { workflow: 'test' },
                {
                    preferredProviderId: 'modal-primary',
                    onValid,
                    onInvalid,
                },
            );
        });

        expect(jobsApi.validate).toHaveBeenCalledWith({ workflow: 'test' }, 'modal-primary');
        expect(onValid).not.toHaveBeenCalled();
        expect(onInvalid).toHaveBeenCalledWith(validationResult);
        expect(submission).toEqual({ ok: false, result: validationResult });
        expect(result.current.isMissingModelsOpen).toBe(true);
        expect(result.current.summary).toEqual({
            valid: false,
            eligibleProviderCount: 0,
            missingModelCount: 1,
        });
    });

    it('submits when validation succeeds and closes missing-model dialog', async () => {
        const validationResult = {
            valid: true,
            global_missing: {},
            eligible_providers: [{ id: 'beam-primary' }],
        };
        const onValid = vi.fn().mockResolvedValue({ jobId: 'job-123' });

        jobsApi.validate.mockResolvedValue(validationResult);

        const { result } = renderWithClient(() => useGenerationPreflight());

        await act(async () => {
            result.current.setIsMissingModelsOpen(true);
        });

        let submission;
        await act(async () => {
            submission = await result.current.runWithPreflight(
                { workflow: 'test' },
                { onValid },
            );
        });

        expect(onValid).toHaveBeenCalledWith(validationResult);
        expect(submission).toEqual({
            ok: true,
            result: validationResult,
            submissionResult: { jobId: 'job-123' },
        });
        expect(result.current.isMissingModelsOpen).toBe(false);
        expect(result.current.summary).toEqual({
            valid: true,
            eligibleProviderCount: 1,
            missingModelCount: 0,
        });
    });
    it('shares the missing-models dialog state across separate hook instances', async () => {
        // Regression: isChecking/isMissingModelsOpen used to be local useState,
        // and useGeneratorCore() is called independently in five places. The
        // instance whose runWithPreflight() decided to open the dialog was never
        // the instance whose isMissingModelsOpen the modal rendered from, so the
        // "missing models" dialog could never appear. Two hooks here mirror the
        // real pair: useWorkflowBuilder (sets) and UnifiedGeneratorLayout (reads).
        jobsApi.validate.mockResolvedValue({
            valid: false,
            global_missing: { checkpoints: ['missing-model.safetensors'] },
            eligible_providers: [],
        });

        const setter = renderWithClient(() => useGenerationPreflight());
        const reader = renderWithClient(() => useGenerationPreflight());

        await act(async () => {
            await setter.result.current.runWithPreflight({ workflow: 'test' }, {});
        });

        expect(setter.result.current.isMissingModelsOpen).toBe(true);
        expect(reader.result.current.isMissingModelsOpen).toBe(true);
    });

    it('shares the in-flight checking flag across separate hook instances', async () => {
        let resolveValidate;
        jobsApi.validate.mockReturnValue(new Promise((resolve) => {
            resolveValidate = resolve;
        }));

        const setter = renderWithClient(() => useGenerationPreflight());
        const reader = renderWithClient(() => useGenerationPreflight());

        let pending;
        act(() => {
            pending = setter.result.current.validateWorkflow({ workflow: 'test' });
        });
        await act(async () => { await Promise.resolve(); });

        expect(setter.result.current.isChecking).toBe(true);
        expect(reader.result.current.isChecking).toBe(true);

        await act(async () => {
            resolveValidate({ valid: true, global_missing: {}, eligible_providers: [] });
            await pending;
        });

        expect(setter.result.current.isChecking).toBe(false);
        expect(reader.result.current.isChecking).toBe(false);
    });
});
