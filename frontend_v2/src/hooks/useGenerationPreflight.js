import { useCallback, useMemo, useState } from 'react';
import { jobsApi } from '../api';
import { useGeneratorStore } from '../store/generatorStore';

function countModelEntries(modelGroups = {}) {
    return Object.values(modelGroups).reduce((total, filenames) => (
        total + (Array.isArray(filenames) ? filenames.length : 0)
    ), 0);
}

export function useGenerationPreflight() {
    const [isChecking, setIsChecking] = useState(false);
    const validationResult = useGeneratorStore(state => state.preflightResult);
    const setValidationResult = useGeneratorStore(state => state.setPreflightResult);
    const [isMissingModelsOpen, setIsMissingModelsOpen] = useState(false);

    const validateWorkflow = useCallback(async (workflow, preferredProviderId = null) => {
        setIsChecking(true);
        try {
            const result = await jobsApi.validate(workflow, preferredProviderId);
            setValidationResult(result);
            if (!result.valid) {
                setIsMissingModelsOpen(true);
            }
            return result;
        } finally {
            setIsChecking(false);
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

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
