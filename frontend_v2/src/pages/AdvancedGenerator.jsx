import { useState, useCallback, useMemo, useRef } from 'react';
import { Play, Loader2, Settings2 } from 'lucide-react';
import { generateApi, createIdempotencyKey } from '../api';
import ReactFlowEditor from '../components/generator/ReactFlowEditor';
import { compileReactFlowToComfy } from '../utils/WorkflowCompiler';
import UnifiedGeneratorLayout from '../components/generator/UnifiedGeneratorLayout';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import useGenerationPreflight from '../hooks/useGenerationPreflight';
import useProvidersPageData from '../hooks/useProvidersPageData';
import useSettingsStore from '../store/settingsStore';
import { useGeneratorJob } from '../hooks/useGeneratorJob';

export default function AdvancedGenerator() {
    const [editorMode, setEditorMode] = useState('visual'); // 'visual' or 'json'
    const [showRunway, setShowRunway] = useState(false);
    const [workflowJson, setWorkflowJson] = useState("");
    const [reactFlowState, setReactFlowState] = useState({ nodes: [], edges: [] });
    // Seeds live inside the user's own graph nodes here, not in a page-level
    // store, so the global auto-randomise setting cannot be applied — and must
    // not be, since pinning a seed is how two graphs are compared.
    const autoRandomizeSeed = useSettingsStore((s) => s.settings?.generator?.autoRandomizeSeed);
    const workflowRef = useRef(null);
    const { providers: allProviders = [], isLoading: providersLoading } = useProvidersPageData();
    const providers = useMemo(() => allProviders.filter(p => !(p.type === 'llm' || p.worker_type === 'llm' || p.id?.startsWith?.('llm'))), [allProviders]);
    // `object_info` must come from a provider that can actually answer it. The
    // list is not ordered by usability, so `providers[0]` was whichever
    // provider happened to sort first — measured on the live stack as
    // `direct_url`, which is registered `enabled=false`. The proxy then took
    // 30s to return HTTP 200 carrying an error BODY
    // (`{"status":"error","code":502,"provider":"direct_url"}`), which
    // `useObjectInfo` could not tell from a successful payload, so it cached the
    // error object as the node definitions for 24 hours and the palette rendered
    // one category literally named `unknown` with six entries. Prefer an enabled
    // provider; fall back to the first only if none is enabled, so the page is
    // never blank while a provider is being switched on.
    const objectInfoProviderId = useMemo(() => {
        const enabled = providers.filter((p) => p.enabled);
        return (enabled[0] || providers[0])?.id ?? null;
    }, [providers]);
    const {
        isChecking: preflightChecking,
        summary: validationSummary,
        runWithPreflight,
    } = useGenerationPreflight();

    const {
        progress,
        generating,
        handleGenerate,
    } = useGeneratorJob({
        type: 'advanced',
        setGeneratingOnQueue: true,
        // The editor is where the user watches the job progress; redirecting to
        // the gallery on submit would tear the graph out from under them.
        redirectAfterGenerate: false,
        validate: () => {
            if (editorMode === 'json' && !workflowJson.trim()) {
                return 'Workflow is empty';
            }
            let workflow;
            try {
                workflow = editorMode === 'visual'
                    ? compileReactFlowToComfy(reactFlowState.nodes, reactFlowState.edges)
                    : JSON.parse(workflowJson);
            } catch (e) {
                return e instanceof SyntaxError ? 'Error: Invalid JSON' : `Error: ${e.message}`;
            }
            if (editorMode === 'visual') {
                // Keep the JSON view in step with the graph, as the old local
                // handler did on every run.
                setWorkflowJson(JSON.stringify(workflow, null, 2));
            }
            workflowRef.current = workflow;
            return null;
        },
        runSubmission: async () => {
            const workflow = workflowRef.current;
            return runWithPreflight(workflow, {
                onValid: async () => generateApi.workflow(workflow, {}, {
                    idempotencyKey: createIdempotencyKey('generate-advanced')
                }),
            });
        },
    });

    const handleGraphChange = useCallback((nodes, edges) => {
        setReactFlowState({ nodes, edges });
    }, []);

    const onRunWorkflow = () => handleGenerate();

    return (
        <UnifiedGeneratorLayout
            mode="advanced"
            leftColumnTop={
                <div className="h-[calc(var(--vh,1vh)*100-140px)] flex flex-col">
                    <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
                        <div className="flex items-center gap-4">
                            <h2 className="text-2xl font-bold">Advanced Workflow</h2>
                            <div className="flex bg-gray-900 rounded-lg p-1 border border-gray-800">
                                <button
                                    onClick={() => setEditorMode('visual')}
                                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${editorMode === 'visual' ? 'bg-blue-600 text-white shadow' : 'text-gray-400 hover:text-gray-200'}`}
                                >
                                    Visual Graph
                                </button>
                                <button
                                    onClick={() => {
                                        if (editorMode !== 'json') {
                                            const workflow = compileReactFlowToComfy(reactFlowState.nodes, reactFlowState.edges);
                                            setWorkflowJson(JSON.stringify(workflow, null, 2));
                                            setEditorMode('json');
                                        }
                                    }}
                                    className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${editorMode === 'json' ? 'bg-blue-600 text-white shadow' : 'text-gray-400 hover:text-gray-200'}`}
                                >
                                    Raw JSON
                                </button>
                            </div>
                        </div>
                        <div className="flex items-center gap-3">
                            {editorMode === 'visual' && (
                                <button
                                    onClick={() => setShowRunway(!showRunway)}
                                    className={`p-2 rounded-lg transition-colors border ${showRunway ? 'bg-blue-600/20 text-blue-400 border-blue-500/50' : 'bg-gray-900 text-gray-400 border-gray-800 hover:text-gray-200'}`}
                                    title="Toggle Settings & Runway"
                                >
                                    <Settings2 size={20} />
                                </button>
                            )}
                            <button
                                onClick={onRunWorkflow}
                                disabled={generating || (editorMode === 'json' && !workflowJson)}
                                /* green-600, not green-700: white on green-600 measures 3.30:1, below WCAG
                                   AA's 4.5:1 for this 14px label. -700 is 5.02:1. */
                                className="px-6 py-2 bg-green-700 rounded-lg font-medium text-white hover:bg-green-600 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                            >
                                {generating ? <Loader2 className="animate-spin" size={18} /> : <Play size={18} />}
                                Run Workflow
                            </button>
                        </div>
                    </div>

                    {progress && (
                        <div className="mb-4 bg-gray-900 rounded-lg border border-gray-800 p-3">
                            <div className="flex items-center justify-between text-xs text-gray-400 mb-2">
                                <span>{progress.node}</span>
                                <span>{progress.value}%</span>
                            </div>
                            <div className="w-full bg-gray-800 rounded-full h-2 overflow-hidden">
                                <div
                                    className="h-full bg-green-500 rounded-full transition-all duration-300"
                                    style={{ width: `${progress.value}%` }}
                                />
                            </div>
                        </div>
                    )}

                    {autoRandomizeSeed && (
                        <p className="mb-4 text-xs text-gray-500">
                            Auto-randomize seed does not apply in Advanced mode: the seed values inside
                            your workflow's nodes are sent exactly as you set them.
                        </p>
                    )}

                    <div className="flex-1 overflow-hidden flex flex-col">
                        {editorMode === 'visual' ? (
                            <ReactFlowEditor 
                                providerId={objectInfoProviderId}
                                onGraphChange={handleGraphChange} 
                            />
                        ) : (
                            <div className="flex-1 bg-gray-950 rounded-xl border border-gray-800 overflow-hidden flex flex-col">
                                <div className="bg-gray-900 px-4 py-2 border-b border-gray-800 text-xs text-gray-400 font-mono">
                                    WORKFLOW JSON
                                </div>
                                <textarea
                                    className="flex-1 w-full h-full bg-gray-950 p-4 font-mono text-sm text-green-400 outline-none resize-none"
                                    placeholder="Paste ComfyUI API Format JSON here..."
                                    value={workflowJson}
                                    onChange={(e) => setWorkflowJson(e.target.value)}
                                />
                            </div>
                        )}
                    </div>
                </div>
            }
            rightColumnBottom={
                (showRunway || editorMode === 'json') ? (
                    <div className="space-y-4">
                        <GeneratorReadinessPanel
                            providers={providers}
                            providersLoading={providersLoading}
                            validationSummary={validationSummary}
                            isChecking={preflightChecking}
                            title="Advanced Runway"
                            hint="Use the same preflight checks as the guided generators before running raw workflow JSON."
                        />
                        <div className="rounded-2xl border border-gray-800 bg-gray-950/70 p-4 text-sm text-gray-400">
                            Advanced mode preserves the raw ComfyUI workflow path, but validation still checks whether the referenced models exist on any enabled provider before queueing the job.
                        </div>
                    </div>
                ) : null
            }
        />
    );
}
