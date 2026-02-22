import React, { useEffect, useRef } from 'react';
import { Wand2 } from 'lucide-react';
import { useGeneratorStore } from '../../store/generatorStore';

export default function PromptPanel() {
    const { prompt, setPrompt, negativePrompt, setNegativePrompt } = useGeneratorStore();
    const promptRef = useRef(null);
    const negPromptRef = useRef(null);

    // Auto-resize textareas
    useEffect(() => {
        if (promptRef.current) {
            promptRef.current.style.height = 'auto';
            promptRef.current.style.height = promptRef.current.scrollHeight + 'px';
        }
    }, [prompt]);

    useEffect(() => {
        if (negPromptRef.current) {
            negPromptRef.current.style.height = 'auto';
            negPromptRef.current.style.height = negPromptRef.current.scrollHeight + 'px';
        }
    }, [negativePrompt]);

    return (
        <div className="bg-gray-800/50 backdrop-blur-sm p-6 rounded-xl border border-gray-700/50 space-y-4 shadow-lg">
            <h3 className="text-lg font-semibold flex items-center gap-2 text-white">
                <Wand2 size={20} className="text-blue-400" />
                Prompts
            </h3>
            <div className="space-y-4">
                <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">Positive Prompt</label>
                    <textarea
                        ref={promptRef}
                        className="w-full bg-gray-900/50 border border-gray-700 rounded-lg p-3 text-white min-h-[8rem] focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500 outline-none resize-y overflow-hidden transition-all"
                        value={prompt}
                        onChange={(e) => setPrompt(e.target.value)}
                        placeholder="Describe what you want to see..."
                    />
                </div>
                <div>
                    <label className="block text-sm font-medium text-gray-400 mb-1">Negative Prompt</label>
                    <textarea
                        ref={negPromptRef}
                        className="w-full bg-gray-900/50 border border-gray-700 rounded-lg p-3 text-white min-h-[5rem] focus:ring-2 focus:ring-red-500/50 focus:border-red-500 outline-none resize-y overflow-hidden transition-all"
                        value={negativePrompt}
                        onChange={(e) => setNegativePrompt(e.target.value)}
                        placeholder="Describe what you want to avoid..."
                    />
                </div>
            </div>
        </div>
    );
}
