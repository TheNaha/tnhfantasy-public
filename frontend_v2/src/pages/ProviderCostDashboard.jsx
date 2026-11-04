import React, { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
    DollarSign, BarChart3, Activity, Clock, TrendingUp, TrendingDown,
    RefreshCw, Search, Filter,
} from 'lucide-react';
import { api } from '../api/client';
import { buildQueryKey, QUERY_KEYS } from '../constants/queryKeys';
import EmptyState from '../components/EmptyState';
import { QueryErrorState } from '../components/common/QueryState';

const COST_FORMATTER = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
});

/**
 * ProviderCostDashboard — per-provider cost and usage analytics.
 *
 * Reads jobs grouped by provider, showing estimated cost, job counts,
 * success/failure rates, and average duration. Cost estimates come from
 * Job.estimated_cost_cents (set by workers at job completion).
 */
export default function ProviderCostDashboard() {
    const { data: jobsData, isLoading, isError, error, refetch } = useQuery({
        queryKey: buildQueryKey(QUERY_KEYS.JOBS, 'all'),
        queryFn: ({ signal }) => api.get('/api/jobs', { params: { limit: 1000 }, signal }),
        refetchInterval: 60000,
    });
    const jobs = useMemo(() => (Array.isArray(jobsData) ? jobsData : (jobsData?.jobs || [])), [jobsData]);

    // Group by provider
    const byProvider = useMemo(() => {
        const map = new Map();
        for (const job of jobs) {
            const pid = job.provider_id || 'unassigned';
            if (!map.has(pid)) {
                map.set(pid, {
                    id: pid,
                    name: pid,
                    jobs: 0,
                    completed: 0,
                    failed: 0,
                    costCents: 0,
                    totalDurationMs: 0,
                    durations: [],
                });
            }
            const p = map.get(pid);
            p.jobs++;
            if (job.status === 'completed') p.completed++;
            else if (job.status === 'failed') p.failed++;
            if (job.estimated_cost_cents) p.costCents += job.estimated_cost_cents;
            if (job.started_at && job.completed_at) {
                const d = new Date(job.completed_at).getTime() - new Date(job.started_at).getTime();
                p.totalDurationMs += d;
                p.durations.push(d);
            }
        }
        return Array.from(map.values());
    }, [jobs]);

    const totalCost = byProvider.reduce((sum, p) => sum + p.costCents, 0);
    const totalJobs = byProvider.reduce((sum, p) => sum + p.jobs, 0);
    const totalCompleted = byProvider.reduce((sum, p) => sum + p.completed, 0);
    const totalFailed = byProvider.reduce((sum, p) => sum + p.failed, 0);

    if (isLoading) {
        return (
            <div className="flex h-full items-center justify-center text-gray-400">
                Loading cost data…
            </div>
        );
    }

    if (isError) {
        return (
            <div className="flex h-full items-center justify-center p-8">
                <QueryErrorState noun="provider cost data" error={error} onRetry={refetch} />
            </div>
        );
    }
    if (byProvider.length === 0) {
        return (
            <div className="flex h-full flex-col items-center justify-center p-8 text-center">
                <EmptyState
                    title="No cost data yet"
                    description="Run some jobs and cost tracking will appear here once workers report estimated costs."
                />
            </div>
        );
    }

    return (
        <div className="flex h-full flex-col bg-gray-900 text-white">
            <header className="flex items-center justify-between px-4 py-3 border-b border-white/5 bg-gray-800/50 shrink-0">
                <div className="flex items-center gap-2">
                    <DollarSign size={18} className="text-green-400" />
                    <h1 className="text-lg font-semibold">Provider Cost Dashboard</h1>
                </div>
                <div className="flex items-center gap-2">
                    <button
                        onClick={refetch}
                        className="p-2 text-gray-300 hover:text-white hover:bg-white/10 rounded-lg transition-colors"
                        title="Refresh"
                        aria-label="Refresh"
                    >
                        <RefreshCw size={16} />
                    </button>
                </div>
            </header>

            <div className="flex-1 overflow-y-auto p-6 space-y-6">
                {/* Summary cards */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div className="rounded-xl border border-white/10 bg-gray-800/50 p-4">
                        <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Total Cost</div>
                        <div className="text-xl font-bold text-white">{COST_FORMATTER.format(totalCost / 100)}</div>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-gray-800/50 p-4">
                        <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Total Jobs</div>
                        <div className="text-xl font-bold text-white">{totalJobs}</div>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-gray-800/50 p-4">
                        <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Completed</div>
                        <div className="text-xl font-bold text-green-400">{totalCompleted}</div>
                    </div>
                    <div className="rounded-xl border border-white/10 bg-gray-800/50 p-4">
                        <div className="text-xs text-gray-400 uppercase tracking-wider mb-1">Failed</div>
                        <div className="text-xl font-bold text-red-400">{totalFailed}</div>
                    </div>
                </div>

                {/* Provider table */}
                <div className="rounded-xl border border-white/10 bg-gray-800/50 overflow-hidden">
                    <table className="w-full text-left border-collapse">
                        <thead>
                            <tr className="border-b border-white/5 bg-gray-800/30">
                                <th className="px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Provider</th>
                                <th className="px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Jobs</th>
                                <th className="px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Completed</th>
                                <th className="px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Failed</th>
                                <th className="px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Cost</th>
                                <th className="px-4 py-3 text-xs font-semibold text-gray-400 uppercase tracking-wider">Avg Duration</th>
                            </tr>
                        </thead>
                        <tbody className="divide-y divide-white/5">
                            {byProvider.map((p) => {
                                const avgDuration = p.durations.length > 0
                                    ? (p.totalDurationMs / p.durations.length / 1000).toFixed(1) + 's'
                                    : '—';
                                return (
                                    <tr key={p.id} className="hover:bg-white/5 transition-colors">
                                        <td className="px-4 py-3 text-sm text-gray-200 font-medium">{p.name}</td>
                                        <td className="px-4 py-3 text-sm text-gray-300">{p.jobs}</td>
                                        <td className="px-4 py-3 text-sm text-green-400">{p.completed}</td>
                                        <td className="px-4 py-3 text-sm text-red-400">{p.failed}</td>
                                        <td className="px-4 py-3 text-sm font-mono text-gray-200">{COST_FORMATTER.format(p.costCents / 100)}</td>
                                        <td className="px-4 py-3 text-sm text-gray-300">{avgDuration}</td>
                                    </tr>
                                );
                            })}
                        </tbody>
                    </table>
                </div>

                {/* Cost by provider bar */}
                <div className="rounded-xl border border-white/10 bg-gray-800/50 p-6">
                    <div className="flex items-center justify-between mb-4">
                        <h3 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Cost by Provider</h3>
                        <span className="text-xs text-gray-500">Estimated USD</span>
                    </div>
                    <div className="space-y-3">
                        {byProvider
                            .sort((a, b) => b.costCents - a.costCents)
                            .map((p) => {
                                const pct = totalCost > 0 ? (p.costCents / totalCost * 100).toFixed(1) : 0;
                                return (
                                    <div key={p.id} className="space-y-1">
                                        <div className="flex items-center justify-between text-xs">
                                            <span className="text-gray-300">{p.name}</span>
                                            <span className="font-mono text-gray-200">{COST_FORMATTER.format(p.costCents / 100)}</span>
                                        </div>
                                        <div className="w-full bg-gray-700/30 rounded-full h-2">
                                            <div
                                                className="bg-green-500 rounded-full h-2"
                                                style={{ width: `${Math.min(pct, 100)}%` }}
                                            />
                                        </div>
                                        <div className="text-xs text-gray-500">{pct}% of total</div>
                                    </div>
                                );
                            })}
                    </div>
                </div>
            </div>
        </div>
    );
}
