import { useState } from 'react';
import { Play, Loader2 } from 'lucide-react';
import toast from 'react-hot-toast';
import { api } from '../api';

export default function AdvancedGenerator() {
    const [workflowJson, setWorkflowJson] = useState("");
    const [generating, setGenerating] = useState(false);

    const handleGenerate = async () => {
        try {
            const workflow = JSON.parse(workflowJson);
            setGenerating(true);

            await api.post('/api/generate', { workflow });

            toast.success("Generation complete!");
        } catch (e) {
            console.error(e);
            toast.error("Error: Invalid JSON or generation failed");
        } finally {
            setGenerating(false);
        }
    };

    return (
        <div className="h-[calc(100vh-140px)] flex flex-col">
            <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4 mb-4">
                <h2 className="text-2xl font-bold">Advanced Workflow</h2>
                <button
                    onClick={handleGenerate}
                    disabled={generating || !workflowJson}
                    className="px-6 py-2 bg-green-600 rounded-lg font-medium text-white hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2"
                >
                    {generating ? <Loader2 className="animate-spin" size={18} /> : <Play size={18} />}
                    Run Workflow
                </button>
            </div>

            <div className="flex-1 bg-gray-950 rounded-xl border border-gray-800 overflow-hidden flex flex-col">
                <div className="bg-gray-900 px-4 py-2 border-b border-gray-800 text-xs text-gray-400 font-mono">
                    WORKFLOW JSON
                </div>
                <textarea
                    className="flex-1 w-full bg-gray-950 p-4 font-mono text-sm text-green-400 outline-none resize-none"
                    placeholder="Paste ComfyUI API Format JSON here..."
                    value={workflowJson}
                    onChange={(e) => setWorkflowJson(e.target.value)}
                />
            </div>
        </div>
    );
}
