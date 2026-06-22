import { AlertTriangle, CheckCircle2, Loader2, Server } from 'lucide-react';
import { summarizeProviderStatus } from '../../utils/providerStatus';

function countOnlineProviders(providers = []) {
    return providers.filter((provider) => summarizeProviderStatus(provider).isOnline).length;
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
        <div className="glass-panel rounded-2xl border border-white/5 bg-[#0B0E14]/80 p-5 shadow-xl">
            <div className="mb-5 border-b border-white/5 pb-3">
                <h3 className="text-base lg:text-lg font-bold flex items-center gap-2 text-white tracking-wide">
                    {title}
                </h3>
                <p className="mt-1 text-xs text-gray-400 font-medium">{hint}</p>
            </div>

            <div className="space-y-3">
                <div className="rounded-xl border border-white/10 bg-black/40 p-4 shadow-inner">
                    <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                            <Server size={18} className={`${providerTone} drop-shadow-md`} />
                            <span className="text-sm font-bold text-white tracking-wide">Providers</span>
                        </div>
                        {providersLoading ? (
                            <Loader2 size={16} className="animate-spin text-blue-400 drop-shadow-[0_0_5px_rgba(59,130,246,0.5)]" />
                        ) : (
                            <span className={`text-[11px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border border-current/20 bg-current/10 ${providerTone}`}>
                                {onlineProviders}/{totalProviders} online
                            </span>
                        )}
                    </div>
                    <p className="mt-2.5 text-xs text-gray-400 font-medium">
                        {providersLoading
                            ? 'Checking provider runtime state...'
                            : onlineProviders > 0
                                ? 'At least one provider looks ready to accept jobs.'
                                : 'No providers are currently online.'}
                    </p>
                </div>

                <div className="rounded-xl border border-white/10 bg-black/40 p-4 shadow-inner">
                    <div className="flex items-center justify-between gap-3">
                        <div className="flex items-center gap-2.5">
                            {isChecking ? (
                                <Loader2 size={18} className="animate-spin text-blue-400 drop-shadow-[0_0_5px_rgba(59,130,246,0.5)]" />
                            ) : validationSummary?.valid ? (
                                <CheckCircle2 size={18} className="text-emerald-400 drop-shadow-[0_0_8px_rgba(52,211,153,0.5)]" />
                            ) : (
                                <AlertTriangle size={18} className={`${validationSummary ? 'text-amber-400 drop-shadow-[0_0_8px_rgba(251,191,36,0.5)]' : 'text-gray-500'}`} />
                            )}
                            <span className="text-sm font-bold text-white tracking-wide">Model preflight</span>
                        </div>
                        <span className={`text-[11px] font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border border-current/20 bg-current/10 ${readinessTone}`}>
                            {isChecking
                                ? 'Checking'
                                : validationSummary?.valid
                                    ? 'Ready'
                                    : validationSummary
                                        ? 'Attention needed'
                                        : 'Not checked'}
                        </span>
                    </div>
                    <p className="mt-2.5 text-xs text-gray-400 font-medium">
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
