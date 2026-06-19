import React, { useEffect, useRef, useState } from 'react';
import { Wand2, BookOpen } from 'lucide-react';
import { useGeneratorStore } from '../../store/generatorStore';
import PromptLibrary from './PromptLibrary';

export default function PromptPanel() {
    const prompt = useGeneratorStore((state) => state.prompt);
    const setPrompt = useGeneratorStore((state) => state.setPrompt);
    const negativePrompt = useGeneratorStore((state) => state.negativePrompt);
    const setNegativePrompt = useGeneratorStore((state) => state.setNegativePrompt);
    const [showPromptLibrary, setShowPromptLibrary] = useState(false);

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

    const handleSelectPromptFromLibrary = (selected) => {
        setPrompt(selected.text);
        if (selected.negative) {
            setNegativePrompt(selected.negative);
        }
    };

    return (
        <div className="space-y-3 pb-4 border-b border-gray-800">
            <div className="flex justify-between items-center">
                <h3 className="text-base lg:text-lg font-semibold flex items-center gap-2">
                    <Wand2 size={18} className="text-blue-400" />
                    Prompts
                </h3>
                <button
                    onClick={() => setShowPromptLibrary(true)}
                    className="px-3 py-1.5 bg-blue-600 hover:bg-blue-500 text-white text-xs lg:text-sm rounded-lg flex items-center gap-1.5 transition-colors"
                    aria-label="Open prompt library"
                    type="button"
                >
                    <BookOpen size={14} aria-hidden="true" />
                    <span className="hidden sm:inline">Library</span>
                    <span className="sm:hidden">Library</span>
                </button>
            </div>
            <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Positive Prompt</label>
                <textarea
                    ref={promptRef}
                    className="w-full bg-gray-900/50 border border-gray-700 rounded-lg p-2 lg:p-3 text-sm text-white min-h-[4rem] lg:min-h-[8rem] focus:ring-2 focus:ring-blue-500 outline-none resize-y overflow-hidden transition-all"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Describe what you want to create..."
                />
            </div>
            <div>
                <label className="block text-xs font-medium text-gray-400 mb-1">Negative Prompt</label>
                <textarea
                    ref={negPromptRef}
                    className="w-full bg-gray-900/50 border border-gray-700 rounded-lg p-2 lg:p-3 text-sm text-white min-h-[3rem] lg:min-h-[5rem] focus:ring-2 focus:ring-red-500 outline-none resize-y overflow-hidden transition-all"
                    value={negativePrompt}
                    onChange={(e) => setNegativePrompt(e.target.value)}
                    placeholder="What to avoid..."
                />
            </div>
            
            <PromptLibrary
                isOpen={showPromptLibrary}
                onClose={() => setShowPromptLibrary(false)}
                onSelectPrompt={handleSelectPromptFromLibrary}
            />
        </div>
    );
}
