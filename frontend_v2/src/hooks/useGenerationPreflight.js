import { useCallback, useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { jobsApi } from '../api';
import { useGeneratorStore } from '../store/generatorStore';

const PREFLIGHT_KEY = ['jobs', 'validate'];

function countModelEntries(modelGroups = {}) {
    return Object.values(modelGroups).reduce((total, filenames) => (
        total + (Array.isArray(filenames) ? filenames.length : 0)
    ), 0);
}

export function useGenerationPreflight() {
    const queryClient = useQueryClient();
    const [isChecking, setIsChecking] = useState(false);
    const [isMissingModelsOpen, setIsMissingModelsOpen] = useState(false);
    const preflightTick = useGeneratorStore(state => state.preflightTick);

    const { data: validationResult = null } = useQuery({
        queryKey: PREFLIGHT_KEY,
        queryFn: () => null,
        enabled: false,
    });

    // Any generation form change invalidates the previous preflight
    // (mirrors the old `preflightResult: null` resets in generatorStore).
    useEffect(() => {
        queryClient.setQueryData(PREFLIGHT_KEY, null);
    }, [queryClient, preflightTick]);

    const validateWorkflow = useCallback(async (workflow, preferredProviderId = null) => {
        setIsChecking(true);
        try {
            const result = await jobsApi.validate(workflow, preferredProviderId);
            queryClient.setQueryData(PREFLIGHT_KEY, result);
            if (!result.valid) {
                setIsMissingModelsOpen(true);
            }
            return result;
        } finally {
            setIsChecking(false);
        }
    }, [queryClient]);

    const runWithPreflight = useCallback(async (
        workflow,
        {
            preferredProviderId = null,
            onValid = null,
            onInvalid = null,
        } = {},
    ) => {
        const result = await validateWorkflow(workflow, preferredProviderId);
        if (!result.valid) {
            await onInvalid?.(result);
            return { ok: false, result };
        }

        setIsMissingModelsOpen(false);
        const submissionResult = await onValid?.(result);
        return { ok: true, result, submissionResult };
    }, [validateWorkflow]);

    const summary = useMemo(() => {
        if (!validationResult) {
            return null;
        }

        return {
            valid: Boolean(validationResult.valid),
            eligibleProviderCount: validationResult.eligible_providers?.length || 0,
            missingModelCount: countModelEntries(validationResult.global_missing),
        };
    }, [validationResult]);

    return {
        isChecking,
        validationResult,
        summary,
        isMissingModelsOpen,
        setIsMissingModelsOpen,
        validateWorkflow,
        runWithPreflight,
    };
}

export default useGenerationPreflight;
