import { memo, useState } from 'react';
import { Plus, Layers, Loader2 } from 'lucide-react';

const GenerateButtonBar = memo(function GenerateButtonBar({
    generating,
    progress,
    prompt,
    onGenerate,
    onQueue,
    onGenerateVariations,
    blockingReason = null,
}) {
    const [showVariationsMenu, setShowVariationsMenu] = useState(false);

    // A prompt is not enough to run a job. With no checkpoint selected the built
    // workflow carries `ckpt_name: ""`, and the provider rejects it ~40 seconds
    // later with "All providers failed: <provider>" — an error that blames the
    // provider for something the client sent.
    //
    // Verified by submitting a real job from a phone: 15 checkpoints were
    // installed, the form had none selected (`selectedCheckpoint: null` is the
    // store default and nothing selects one for you), the button was enabled,
    // and the job failed after a full round-trip. `InpaintGenerator` already
    // guards this via its own `canGenerate`; this route did not.
    //
    // So the button is disabled while `blockingReason` is set, and the reason is
    // on the button rather than left for the user to discover the hard way.
    const blocked = generating || !prompt || !!blockingReason;
    const reason = blockingReason
        || (generating ? 'Generating…' : (!prompt ? 'Enter a prompt first' : ''));

    return (
        <div className="flex gap-3 relative">
            <button
                onClick={onQueue}
                disabled={!prompt || !!blockingReason}
                title={reason || 'Add to Queue'}
                className={`flex-1 h-14 rounded-xl font-bold text-base shadow-xl transition-all duration-300 transform active:scale-95 border flex items-center justify-center ${!prompt || blockingReason
                    ? 'bg-black/20 text-gray-600 cursor-not-allowed border-white/5'
                    : 'bg-[#0B0E14]/80 hover:bg-[#0B0E14] text-blue-400 hover:text-blue-300 border-white/10 hover:border-blue-500/30 hover:shadow-[0_0_15px_rgba(59,130,246,0.2)]'
                    }`}
            >
                <Plus size={22} strokeWidth={2.5} />
            </button>

            <div className="relative">
                <button
                    onClick={() => setShowVariationsMenu(!showVariationsMenu)}
                    disabled={blocked}
                    title={reason || 'Generate Variations'}
                    className={`h-14 px-5 rounded-xl font-bold text-base shadow-xl transition-all duration-300 transform active:scale-95 border flex items-center justify-center ${blocked
                        ? 'bg-black/20 text-gray-600 cursor-not-allowed border-white/5'
                        : 'bg-purple-900/20 hover:bg-purple-900/40 text-purple-400 hover:text-purple-300 border-purple-500/20 hover:border-purple-500/40 hover:shadow-[0_0_15px_rgba(168,85,247,0.2)]'
                        }`}
                >
                    <Layers size={22} />
                </button>

                {showVariationsMenu && (
                    <div className="absolute bottom-[calc(100%+0.5rem)] right-0 glass-panel border-white/10 rounded-2xl shadow-2xl py-2 min-w-[180px] z-50 backdrop-blur-xl">
                        <div className="px-4 py-2 text-xs font-bold text-gray-400 uppercase tracking-widest border-b border-white/5 mb-1">Seed Variations</div>
                        {[2, 4, 8].map(count => (
                            <button
                                key={count}
                                onClick={() => { setShowVariationsMenu(false); onGenerateVariations(count); }}
                                className="w-full px-4 py-2.5 text-left text-sm font-medium text-gray-300 hover:bg-purple-500/10 hover:text-purple-300 transition-colors"
                            >
                                Generate {count}x
                            </button>
                        ))}
                    </div>
                )}
            </div>

            <button
                onClick={onGenerate}
                disabled={blocked}
                title={reason}
                className={`flex-[3] h-14 rounded-xl font-bold text-lg tracking-wide shadow-xl transition-all duration-300 transform active:scale-[0.98] flex items-center justify-center overflow-hidden relative ${blocked
                    ? 'bg-black/40 text-gray-500 cursor-not-allowed border border-white/5'
                    : 'bg-gradient-to-r from-blue-600 to-violet-600 hover:from-blue-500 hover:to-violet-500 text-white border border-white/10 hover:shadow-[0_0_20px_rgba(139,92,246,0.4)]'
                    }`}
            >
                {/* Glow Effect Overlay */}
                {!blocked && (
                    <div className="absolute inset-0 bg-white/0 hover:bg-white/10 transition-colors duration-300" />
                )}

                <div className="relative z-10 flex items-center justify-center gap-2">
                    {generating ? (
                        <>
                            <Loader2 className="animate-spin drop-shadow-[0_0_5px_rgba(255,255,255,0.5)]" size={22} />
                            <span>Generating...</span>
                        </>
                    ) : blockingReason ? (
                        <span className="drop-shadow-md text-sm px-2 text-center leading-tight">
                            Select a checkpoint
                        </span>
                    ) : (
                        <span className="drop-shadow-md">Generate</span>
                    )}
                </div>

                {generating && progress && (
                    <div className="absolute bottom-0 left-0 h-1 bg-gradient-to-r from-blue-400 to-purple-400 transition-all duration-300 ease-out shadow-[0_0_10px_rgba(168,85,247,0.8)]" style={{ width: `${progress.value}%` }} />
                )}
                {generating && progress?.node && (
                    <div className="absolute top-1 left-0 right-0 text-center text-xs font-medium text-white/50 tracking-wider">
                        {progress.node}
                    </div>
                )}
            </button>
        </div>
    );
});

export default GenerateButtonBar;
