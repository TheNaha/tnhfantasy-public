import { memo, useState } from 'react';
import { Plus, Layers, Loader2 } from 'lucide-react';

const GenerateButtonBar = memo(function GenerateButtonBar({
    generating,
    progress,
    prompt,
    onGenerate,
    onQueue,
    onGenerateVariations,
}) {
    const [showVariationsMenu, setShowVariationsMenu] = useState(false);

    return (
        <div className="flex gap-2 relative">
            <button
                onClick={onQueue}
                disabled={!prompt}
                className={`flex-1 h-12 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 border border-gray-700 flex items-center justify-center ${!prompt
                    ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                    : 'bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white'
                    }`}
            >
                <Plus size={18} />
            </button>

            <div className="relative">
                <button
                    onClick={() => setShowVariationsMenu(!showVariationsMenu)}
                    disabled={generating || !prompt}
                    className={`h-12 px-4 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 border flex items-center justify-center ${generating || !prompt
                        ? 'bg-gray-800 text-gray-500 cursor-not-allowed border-gray-700'
                        : 'bg-purple-900/50 hover:bg-purple-800/50 text-purple-300 hover:text-purple-200 border-purple-700'
                        }`}
                    title="Generate Variations"
                >
                    <Layers size={18} />
                </button>

                {showVariationsMenu && (
                    <div className="absolute bottom-full mb-2 right-0 bg-gray-800 border border-gray-700 rounded-xl shadow-xl py-2 min-w-[160px] z-50">
                        <div className="px-3 py-1 text-xs text-gray-500 uppercase tracking-wider">Seed Variations</div>
                        {[2, 4, 8].map(count => (
                            <button
                                key={count}
                                onClick={() => { setShowVariationsMenu(false); onGenerateVariations(count); }}
                                className="w-full px-4 py-2 text-left text-sm text-gray-300 hover:bg-purple-900/30 hover:text-purple-300 transition-colors"
                            >
                                Generate {count}x
                            </button>
                        ))}
                    </div>
                )}
            </div>

            <button
                onClick={onGenerate}
                disabled={generating || !prompt}
                className={`flex-[3] h-12 rounded-xl font-bold text-base shadow-lg transition-all transform active:scale-95 flex items-center justify-center ${generating
                    ? 'bg-gray-700 text-gray-400 cursor-not-allowed'
                    : 'bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white shadow-blue-900/20'
                    }`}
            >
                {generating ? (
                    <span className="flex items-center justify-center gap-2">
                        <Loader2 className="animate-spin" size={20} />
                        Generating...
                    </span>
                ) : (
                    "Generate"
                )}
            </button>

            {generating && progress && (
                <div className="absolute top-0 left-0 h-1 bg-gradient-to-r from-blue-500 to-purple-500 transition-all duration-300 ease-out" style={{ width: `${progress.value}%` }} />
            )}
            {generating && progress?.node && (
                <div className="absolute top-1 left-0 right-0 text-center text-[10px] text-gray-400">
                    {progress.node}
                </div>
            )}
        </div>
    );
});

export default GenerateButtonBar;
