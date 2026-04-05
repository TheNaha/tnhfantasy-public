import { AlertTriangle, CheckCircle2, Loader2, Server } from 'lucide-react';

function countOnlineProviders(providers = []) {
    return providers.filter((provider) => {
        const status = provider.runtime_state?.status;
        return provider.enabled && ['running', 'active', 'connected'].includes(status);
    }).length;
}

export default function GeneratorReadinessPanel({
    providers = [],
    providersLoading = false,
    validationSummary = null,
    isChecking = false,
    title = 'Run Readiness',
    hint = 'Provider and model availability before queueing a job.',
}) {
    const onlineProviders = countOnlineProviders(providers);
    const totalProviders = providers.length;
    const providerTone = onlineProviders > 0 ? 'text-emerald-300' : 'text-amber-300';
    const readinessTone = validationSummary?.valid
        ? 'text-emerald-300'
        : validationSummary
            ? 'text-amber-300'
            : 'text-gray-400';

    return (
        <div className="rounded-2xl border border-gray-800 bg-gray-950/70 p-4 shadow-lg shadow-black/20">
            <div className="mb-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-gray-500">
                    {title}
                </p>
                <p className="mt-1 text-xs text-gray-400">{hint}</p>
            </div>

            <div className="space-y-3">
                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-3">
                    <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                            <Server size={16} className={providerTone} />
                            <span className="text-sm font-medium text-white">Providers</span>
                        </div>
                        {providersLoading ? (
                            <Loader2 size={14} className="animate-spin text-blue-400" />
                        ) : (
                            <span className={`text-xs ${providerTone}`}>
                                {onlineProviders}/{totalProviders} online
                            </span>
                        )}
                    </div>
                    <p className="mt-2 text-xs text-gray-400">
                        {providersLoading
                            ? 'Checking provider runtime state...'
                            : onlineProviders > 0
                                ? 'At least one provider looks ready to accept jobs.'
                                : 'No providers are currently online.'}
                    </p>
                </div>

                <div className="rounded-xl border border-gray-800 bg-gray-900/60 p-3">
                    <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2">
                            {isChecking ? (
                                <Loader2 size={16} className="animate-spin text-blue-400" />
                            ) : validationSummary?.valid ? (
                                <CheckCircle2 size={16} className="text-emerald-300" />
                            ) : (
                                <AlertTriangle size={16} className={validationSummary ? 'text-amber-300' : 'text-gray-500'} />
                            )}
                            <span className="text-sm font-medium text-white">Model preflight</span>
                        </div>
                        <span className={`text-xs ${readinessTone}`}>
                            {isChecking
                                ? 'Checking'
                                : validationSummary?.valid
                                    ? 'Ready'
                                    : validationSummary
                                        ? 'Attention needed'
                                        : 'Not checked'}
                        </span>
                    </div>
                    <p className="mt-2 text-xs text-gray-400">
                        {isChecking
                            ? 'Validating workflow requirements against provider availability.'
                            : validationSummary?.valid
                                ? `${validationSummary.eligibleProviderCount} provider${validationSummary.eligibleProviderCount === 1 ? '' : 's'} can run this workflow.`
                                : validationSummary
                                    ? `${validationSummary.missingModelCount} missing model${validationSummary.missingModelCount === 1 ? '' : 's'} need attention before queueing.`
                                    : 'Run generation once to cache a workflow validation result.'}
                    </p>
                </div>
            </div>
        </div>
    );
}
