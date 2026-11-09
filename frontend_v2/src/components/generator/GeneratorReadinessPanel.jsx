import { useState } from 'react';
import { AlertTriangle, CheckCircle2, ChevronDown, ChevronRight, Loader2, Server } from 'lucide-react';
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
    const imageProviders = providers.filter(p => p.worker_type !== 'llm');
    const onlineProviders = countOnlineProviders(imageProviders);
    const totalProviders = imageProviders.length;
    const providerTone = onlineProviders > 0 ? 'text-emerald-300' : 'text-amber-300';
    const readinessTone = validationSummary?.valid
        ? 'text-emerald-300'
        : validationSummary
            ? 'text-amber-300'
            : 'text-gray-400';

    const needsAttention = !providersLoading && (onlineProviders === 0 || (validationSummary && !validationSummary.valid));
    const [userExpanded, setUserExpanded] = useState(null);
    const isExpanded = userExpanded ?? needsAttention;

    return (
        <div className="glass-panel rounded-2xl border border-white/5 bg-[#0B0E14]/80 p-4 lg:p-5 shadow-xl">
            <button
                type="button"
                onClick={() => setUserExpanded(!isExpanded)}
                aria-expanded={isExpanded}
                data-testid="readiness-panel-toggle"
                className="w-full text-left flex items-center justify-between gap-2 transition-colors group"
            >
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                        <h3 className="text-sm lg:text-base font-bold text-white tracking-wide group-hover:text-purple-300 transition-colors">
                            {title}
                        </h3>
                        {isExpanded ? (
                            <ChevronDown size={16} className="text-gray-400 group-hover:text-white transition-colors" />
                        ) : (
                            <ChevronRight size={16} className="text-gray-400 group-hover:text-white transition-colors" />
                        )}
                    </div>
                    <p className="mt-0.5 text-2xs text-gray-400 font-medium truncate">{hint}</p>
                </div>
                {!isExpanded && (
                    <div className="flex items-center gap-1.5 shrink-0">
                        <span className={`text-2xs font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border border-current/20 bg-current/10 ${providerTone}`}>
                            {onlineProviders}/{totalProviders}
                        </span>
                        <span className={`text-2xs font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border border-current/20 bg-current/10 ${readinessTone}`}>
                            {isChecking
                                ? 'Checking'
                                : validationSummary?.valid
                                    ? 'Ready'
                                    : validationSummary
                                        ? 'Attention'
                                        : 'Idle'}
                        </span>
                    </div>
                )}
            </button>

            {isExpanded && (
                <div className="mt-4 pt-4 border-t border-white/5 space-y-3">
                    <div className="rounded-xl border border-white/10 bg-black/40 p-3.5 shadow-inner">
                        <div className="flex items-center justify-between gap-3">
                            <div className="flex items-center gap-2.5">
                                <Server size={18} className={`${providerTone} drop-shadow-md`} />
                                <span className="text-sm font-bold text-white tracking-wide">Providers</span>
                            </div>
                            {providersLoading ? (
                                <Loader2 size={16} className="animate-spin text-blue-400 drop-shadow-[0_0_5px_rgba(59,130,246,0.5)]" />
                            ) : (
                                <span className={`text-2xs font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border border-current/20 bg-current/10 ${providerTone}`}>
                                    {onlineProviders}/{totalProviders} online
                                </span>
                            )}
                        </div>
                        <p className="mt-2 text-xs text-gray-400 font-medium">
                            {providersLoading
                                ? 'Checking provider runtime state...'
                                : onlineProviders > 0
                                    ? 'At least one provider looks ready to accept jobs.'
                                    : 'No providers are currently online.'}
                        </p>
                    </div>

                    <div className="rounded-xl border border-white/10 bg-black/40 p-3.5 shadow-inner">
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
                            <span className={`text-2xs font-bold uppercase tracking-widest px-2 py-0.5 rounded-full border border-current/20 bg-current/10 ${readinessTone}`}>
                                {isChecking
                                    ? 'Checking'
                                    : validationSummary?.valid
                                        ? 'Ready'
                                        : validationSummary
                                            ? 'Attention needed'
                                            : 'Not checked'}
                            </span>
                        </div>
                        <p className="mt-2 text-xs text-gray-400 font-medium">
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
            )}
        </div>
    );
}
