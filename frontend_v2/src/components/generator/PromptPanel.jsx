import { useEffect, useRef, useState } from 'react';
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
        <div className="glass-panel p-5 rounded-2xl border border-white/5 shadow-xl space-y-4 mb-4">
            <div className="flex justify-between items-center">
                <h3 className="text-base lg:text-lg font-bold flex items-center gap-2 text-white">
                    <Wand2 size={20} className="text-blue-400 drop-shadow-[0_0_8px_rgba(59,130,246,0.6)]" />
                    Prompts
                </h3>
                <button
                    onClick={() => setShowPromptLibrary(true)}
                    className="px-4 py-2 bg-blue-600/20 hover:bg-blue-600/40 text-blue-300 hover:text-white border border-blue-500/30 text-xs lg:text-sm rounded-xl flex items-center gap-2 transition-all shadow-[0_0_10px_rgba(59,130,246,0.1)] hover:shadow-[0_0_15px_rgba(59,130,246,0.3)] hover:-translate-y-0.5"
                    aria-label="Open prompt library"
                    type="button"
                >
                    <BookOpen size={16} aria-hidden="true" />
                    <span className="hidden sm:inline font-semibold tracking-wide">Library</span>
                    <span className="sm:hidden font-semibold">Library</span>
                </button>
            </div>
            
            <div className="space-y-1 group">
                <label className="block text-[11px] font-bold text-blue-400 uppercase tracking-widest mb-2 px-1">Positive Prompt</label>
                <textarea
                    ref={promptRef}
                    className="w-full bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 lg:p-4 text-sm text-white min-h-[4rem] lg:min-h-[8rem] focus:ring-2 focus:ring-blue-500/50 focus:border-blue-500/50 outline-none resize-y overflow-hidden transition-all shadow-inner glow-focus placeholder-gray-600"
                    value={prompt}
                    onChange={(e) => setPrompt(e.target.value)}
                    placeholder="Describe what you want to create..."
                />
            </div>
            
            <div className="space-y-1 group">
                <label className="block text-[11px] font-bold text-pink-400 uppercase tracking-widest mb-2 px-1">Negative Prompt</label>
                <textarea
                    ref={negPromptRef}
                    className="w-full bg-[#0B0E14]/80 border border-white/10 rounded-xl p-3 lg:p-4 text-sm text-white min-h-[3rem] lg:min-h-[5rem] focus:ring-2 focus:ring-pink-500/50 focus:border-pink-500/50 outline-none resize-y overflow-hidden transition-all shadow-inner glow-focus placeholder-gray-600"
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
