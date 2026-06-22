
import { Rocket, Loader2 } from 'lucide-react';
import { DataRow, StatusRow, ActionBtn, Notice } from './Shared';
import { STATUS_TONE, humanize } from './utils';

export default function DeployTab({ deploy, deployBadge, capabilities, capabilityReasons, loading, onDeploy, provider }) {
    return (
        <>
            <div className="rounded-xl border border-white/[0.06] bg-gray-900/40 overflow-hidden">
                <StatusRow label="Deploy Status" value={humanize(deploy.status || 'idle')} tone={STATUS_TONE[deploy.status || 'idle']} />
                <DataRow label="Deploy Mode" value={deployBadge} />
                <DataRow label="Message" value={deploy.message || capabilityReasons.deploy || 'No deploy activity'} />
                <DataRow label="Provider Type" value={deploy.mode || provider.type} />
                <DataRow label="Last Deployed" value={deploy.finished_at ? new Date(deploy.finished_at).toLocaleString() : 'Never'} />
                <DataRow
                    label="Completed Steps"
                    value={String(deploy.completed_steps?.length || deploy.steps?.filter((s) => s.success)?.length || 0)}
                />
            </div>

            <div className="flex flex-wrap gap-2 mb-4">
                {capabilities.deploy && (
                    <ActionBtn onClick={onDeploy} disabled={Boolean(loading)} tone="purple" icon={Rocket} label="Deploy" />
                )}
                {!capabilities.deploy && capabilityReasons.deploy && (
                    <Notice tone="yellow" message={capabilityReasons.deploy} />
                )}
            </div>

            {(deploy.logs || deploy.steps?.length || deploy.status !== 'idle') && (
                <div className="space-y-3">
                    {deploy.logs ? (
                        <div className="rounded-xl border border-gray-800 bg-gray-950/70 p-4">
                            <div className="mb-2 flex items-center justify-between gap-3">
                                <span className="font-medium text-sm text-white">Console Logs</span>
                                {deploy.status === 'deploying' && <Loader2 size={14} className="text-blue-400 animate-spin" />}
                            </div>
                            <div className="h-[400px] overflow-y-auto font-mono text-[11px] leading-relaxed text-gray-300 whitespace-pre-wrap break-words rounded bg-black/40 p-3 ring-1 ring-inset ring-white/5 scrollbar-thin flex flex-col-reverse">
                                <div>{deploy.logs}</div>
                            </div>
                        </div>
                    ) : (
                        (deploy.steps?.length ? deploy.steps : [{ name: 'No steps recorded', success: true, output: '' }]).map((step) => (
                            <div key={step.name} className="rounded-xl border border-gray-800 bg-gray-950/70 p-4">
                                <div className="mb-2 flex items-center justify-between gap-3">
                                    <span className="font-medium text-sm text-white">{step.name}</span>
                                    <span className={`rounded-full border px-2 py-0.5 text-[10px] font-medium ${
                                        step.skipped
                                            ? 'border-gray-600 text-gray-400'
                                            : step.success
                                                ? 'border-green-500/25 text-green-300'
                                                : 'border-red-500/25 text-red-300'
                                    }`}>
                                        {step.skipped ? 'Skipped' : step.success ? 'Success' : 'Failed'}
                                    </span>
                                </div>
                                {step.entrypoint && <div className="mb-2 text-xs text-gray-500">{step.entrypoint}</div>}
                                <pre className="whitespace-pre-wrap break-words text-xs text-gray-400">
                                    {step.output || 'No output'}
                                </pre>
                            </div>
                        ))
                    )}
                    {deploy.test_results && deploy.test_results.length > 0 && (
                        <div className="rounded-xl border border-blue-500/20 bg-blue-500/5 p-4 mt-4">
                            <h4 className="text-sm font-medium text-blue-200 mb-3">Deployment Tests</h4>
                            <div className="space-y-2">
                                {deploy.test_results.map((test, idx) => (
                                    <div key={idx} className="flex items-center justify-between bg-black/40 p-2 rounded border border-white/5">
                                        <span className="text-sm text-gray-300">{test.name}</span>
                                        <div className="flex items-center gap-2">
                                            <span className="text-xs text-gray-400">{test.message}</span>
                                            <span className={`text-xs font-bold ${test.success ? 'text-green-400' : 'text-red-400'}`}>
                                                {test.success ? 'PASS' : 'FAIL'}
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </>
    );
}
