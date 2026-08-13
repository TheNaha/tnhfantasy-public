import { useState, useCallback, useMemo } from 'react';
import { Play, Loader2, Settings2 } from 'lucide-react';
import toast from 'react-hot-toast';
import MissingModelsDialog from '../components/generator/MissingModelsDialog';
import GeneratorReadinessPanel from '../components/generator/GeneratorReadinessPanel';
import useGenerationPreflight from '../hooks/useGenerationPreflight';
import useProvidersPageData from '../hooks/useProvidersPageData';
import { useGeneratorJob } from '../hooks/useGeneratorJob';
import { generateApi, createIdempotencyKey } from '../api';
import ReactFlowEditor from '../components/generator/ReactFlowEditor';
import { compileReactFlowToComfy } from '../utils/WorkflowCompiler';

export default function AdvancedGenerator() {
    const [editorMode, setEditorMode] = useState('visual'); // 'visual' or 'json'
    const [showRunway, setShowRunway] = useState(false);
    const [workflowJson, setWorkflowJson] = useState("");
    const [reactFlowState, setReactFlowState] = useState({ nodes: [], edges: [] });
    const { providers: allProviders = [], isLoading: providersLoading } = useProvidersPageData();
    const providers = useMemo(() => allProviders.filter(p => !(p.type === 'llm' || p.worker_type === 'llm' || p.id.startsWith('llm'))), [allProviders]);
    const {
        isChecking: preflightChecking,
        validationResult,
        summary: validationSummary,
        isMissingModelsOpen,
        setIsMissingModelsOpen,
        runWithPreflight,
    } = useGenerationPreflight();

    const {
        setCurrentJobId,
        progress,
        setProgress,
        generating,
        setGenerating,
    } = useGeneratorJob({ setGeneratingOnQueue: true });

    const handleGraphChange = useCallback((nodes, edges) => {
        setReactFlowState({ nodes, edges });
    }, []);

    const handleGenerate = async () => {
        try {
            let workflow;
            if (editorMode === 'visual') {
                workflow = compileReactFlowToComfy(reactFlowState.nodes, reactFlowState.edges);
                setWorkflowJson(JSON.stringify(workflow, null, 2)); // Update JSON view just in case
            } else {
                workflow = JSON.parse(workflowJson);
            }
            
            setGenerating(true);
            setProgress({ value: 0, max: 100, status: 'starting', node: 'Initializing...' });

            const submission = await runWithPreflight(workflow, {
                onValid: async () => generateApi.workflow(workflow, {}, {
                    idempotencyKey: createIdempotencyKey('generate-advanced')
                }),
            });
            if (!submission.ok) {
                setGenerating(false);
                setProgress(null);
                return;
            }

            const data = submission.submissionResult;
            if (data && data.id) {
                setCurrentJobId(data.id);
                setProgress({ value: 0, max: 100, status: 'queued', node: 'Job queued...' });
                toast.success('Job queued!', { icon: '⏳' });
            } else {
                toast.success("Job queued!");
                setGenerating(false);
                setProgress(null);
            }
        } catch (e) {
            toast.error(e instanceof SyntaxError ? "Error: Invalid JSON" : `Error: ${e.message}`);
            setGenerating(false);
            setProgress(null);
        }
    };

    return (
        <div className={`grid grid-cols-1 gap-6 transition-all ${showRunway || editorMode === 'json' ? 'lg:grid-cols-[minmax(0,1fr)_320px]' : ''}`}>
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
                        onClick={handleGenerate}
                        disabled={generating || (editorMode === 'json' && !workflowJson)}
                        className="px-6 py-2 bg-green-600 rounded-lg font-medium text-white hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
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

            <div className="flex-1 overflow-hidden flex flex-col">
                {editorMode === 'visual' ? (
                    // We just pass the first provider as default for now, users can select it later if needed
                    <ReactFlowEditor 
                        providerId={providers && providers.length > 0 ? providers[0].id : null}
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

            <MissingModelsDialog
                isOpen={isMissingModelsOpen}
                onClose={() => setIsMissingModelsOpen(false)}
                validationResult={validationResult}
            />
            </div>

            {(showRunway || editorMode === 'json') && (
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
            )}
        </div>
    );
}
