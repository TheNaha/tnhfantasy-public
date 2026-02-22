import React, { useState } from 'react';
import { FolderOpen, Save, ArrowRight, Trash2 } from 'lucide-react';
import { useGeneratorStore } from '../../store/generatorStore';
import toast from 'react-hot-toast';

export default function SavedPromptsPanel() {
    const {
        savedPrompts, setSavedPrompts, setAll,
        prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
        selectedCheckpoint, selectedLoras, controlnets,
        hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
        adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise
    } = useGeneratorStore();

    const [showSavedPrompts, setShowSavedPrompts] = useState(false);
    const [newPromptName, setNewPromptName] = useState("");

    const handleSavePrompt = () => {
        if (!newPromptName.trim()) return toast.error("Enter a name");
        const newPrompt = {
            name: newPromptName,
            date: new Date().toISOString(),
            data: {
                prompt, negativePrompt, seed, steps, cfg, sampler, scheduler, width, height, batchSize,
                selectedCheckpoint, selectedLoras, controlnets,
                hiresFix, hiresUpscaler, hiresDenoise, hiresUpscale, hiresSteps,
                adetailer, adetailerModel, adetailerPrompt, adetailerSteps, adetailerDenoise
            }
        };
        const newPrompts = [...savedPrompts, newPrompt];
        setSavedPrompts(newPrompts);
        setNewPromptName("");
        toast.success("Prompt saved!");
    };

    const handleLoadPrompt = (p) => {
        const d = p.data;
        setAll({
            prompt: d.prompt,
            negativePrompt: d.negativePrompt,
            seed: d.seed,
            steps: d.steps,
            cfg: d.cfg,
            sampler: d.sampler,
            scheduler: d.scheduler,
            width: d.width,
            height: d.height,
            batchSize: d.batchSize || 1,
            selectedCheckpoint: d.selectedCheckpoint || null,
            selectedLoras: d.loras || [],
            controlnets: d.controlnets || [],
            hiresFix: d.hiresFix || false,
            hiresUpscaler: d.hiresUpscaler || "Latent",
            hiresDenoise: d.hiresDenoise || 0.5,
            hiresUpscale: d.hiresUpscale || 1.5,
            hiresSteps: d.hiresSteps || 10,
            adetailer: d.adetailer || false,
            adetailerModel: d.adetailerModel || "face_yolov8n.pt",
            adetailerPrompt: d.adetailerPrompt || "",
            adetailerSteps: d.adetailerSteps || 20,
            adetailerDenoise: d.adetailerDenoise || 0.4
        });
        toast.success("Prompt loaded!");
        setShowSavedPrompts(false);
    };

    const handleDeletePrompt = (idx) => {
        const newPrompts = [...savedPrompts];
        newPrompts.splice(idx, 1);
        setSavedPrompts(newPrompts);
    };

    return (
        <div className="bg-gray-800/50 backdrop-blur-sm p-6 rounded-xl border border-gray-700/50 shadow-lg">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold flex items-center gap-2 text-white">
                    <FolderOpen size={20} className="text-yellow-400" />
                    Saved Prompts
                </h3>
                <button
                    onClick={() => setShowSavedPrompts(!showSavedPrompts)}
                    className="text-sm text-blue-400 hover:text-blue-300 transition-colors"
                >
                    {showSavedPrompts ? "Hide" : "Show Saved"}
                </button>
            </div>

            {showSavedPrompts && (
                <div className="mb-6 space-y-4 animate-in slide-in-from-top-2 fade-in duration-200">
                    <div className="flex gap-2">
                        <input
                            type="text"
                            placeholder="New prompt name..."
                            className="flex-1 bg-gray-900 border border-gray-700 rounded-lg p-2 text-white text-sm focus:ring-1 focus:ring-green-500 outline-none"
                            value={newPromptName}
                            onChange={(e) => setNewPromptName(e.target.value)}
                        />
                        <button
                            onClick={handleSavePrompt}
                            className="px-4 py-2 bg-green-600 hover:bg-green-500 rounded-lg text-white text-sm flex items-center gap-2 transition-colors shadow-lg shadow-green-900/20"
                        >
                            <Save size={16} /> Save
                        </button>
                    </div>

                    <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-60 overflow-y-auto pr-1 custom-scrollbar">
                        {savedPrompts.length === 0 ? (
                            <p className="text-gray-500 text-sm col-span-2 text-center py-4">No saved prompts yet.</p>
                        ) : (
                            savedPrompts.map((p, idx) => (
                                <div key={idx} className="bg-gray-900/50 p-3 rounded-lg border border-gray-700/50 flex justify-between items-center group hover:border-gray-600 transition-all">
                                    <div>
                                        <p className="font-medium text-sm text-gray-200">{p.name}</p>
                                        <p className="text-xs text-gray-500">{new Date(p.date).toLocaleDateString()}</p>
                                    </div>
                                    <div className="flex gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                                        <button
                                            onClick={() => handleLoadPrompt(p)}
                                            className="p-1.5 bg-blue-600/20 text-blue-400 rounded hover:bg-blue-600/40 transition-colors"
                                            title="Load"
                                        >
                                            <ArrowRight size={14} />
                                        </button>
                                        <button
                                            onClick={() => handleDeletePrompt(idx)}
                                            className="p-1.5 bg-red-600/20 text-red-400 rounded hover:bg-red-600/40 transition-colors"
                                            title="Delete"
                                        >
                                            <Trash2 size={14} />
                                        </button>
                                    </div>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
