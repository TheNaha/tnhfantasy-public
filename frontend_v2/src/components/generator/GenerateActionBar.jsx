import { Loader2, Play, Plus } from 'lucide-react';

/**
 * Queue + Generate button bar shared by the Img2Img and Inpaint pages
 * (was copy-pasted verbatim in both). Disabled state is computed by the
 * caller so each page can include its own validation conditions.
 */
export default function GenerateActionBar({
    generating,
    progress,
    disabled,
    onQueue,
    onGenerate,
    label,
    gradientClass,
    progressBarClass,
}) {
    return (
        <div className="flex gap-2">
            <button
                onClick={onQueue}
                disabled={disabled}
                className={`flex-1 h-14 rounded-xl font-bold text-base shadow-lg transition-all border border-gray-700 flex items-center justify-center ${disabled
                    ? 'bg-gray-800 text-gray-500 cursor-not-allowed'
                    : 'bg-gray-800 hover:bg-gray-700 text-gray-300 hover:text-white'
                }`}
                title="Add to queue"
            >
                <Plus size={20} />
            </button>

            <button
                onClick={onGenerate}
                disabled={disabled}
                className={`flex-[4] relative overflow-hidden h-14 rounded-xl font-bold text-lg flex items-center justify-center gap-3 transition-all ${disabled
                    ? 'bg-gray-700 text-gray-500 cursor-not-allowed'
                    : gradientClass
                }`}
            >
                {generating ? (
                    <>
                        <Loader2 className="animate-spin" size={20} />
                        {progress?.node || 'Generating...'}
                    </>
                ) : (
                    <>
                        <Play size={20} />
                        {label}
                    </>
                )}
                {generating && progress && (
                    <div
                        className={`absolute top-0 left-0 h-1 bg-gradient-to-r ${progressBarClass} transition-all duration-300 ease-out`}
                        style={{ width: `${progress.value}%` }}
                    />
                )}
            </button>
        </div>
    );
}
