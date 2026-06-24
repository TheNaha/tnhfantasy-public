import { Loader2 } from "lucide-react";

export default function FeedCardDetails({
  detailsId,
  showDetails,
  detailsLoading,
  metadata
}) {
  if (!showDetails) return null;

  return (
    <div id={detailsId} className="p-6 space-y-4 md:space-y-6 bg-gray-900/30 border-t border-gray-800">
      {detailsLoading ? (
        <div className="flex gap-2 items-center text-gray-500 text-sm">
          <Loader2 className="animate-spin" size={14} /> Loading details...
        </div>
      ) : metadata ? (
        <>
          {/* Prompt */}
          <div className="space-y-2">
            <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
              Prompt
            </h4>
            <p className="text-sm text-gray-300 leading-relaxed bg-gray-950/50 p-4 rounded-xl border border-gray-800/50">
              {metadata.prompt}
            </p>
          </div>

          {/* Negative Prompt */}
          {metadata.negativePrompt && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                Negative Prompt
              </h4>
              <p className="text-sm text-gray-400 leading-relaxed bg-gray-950/50 p-4 rounded-xl border border-gray-800/50">
                {metadata.negativePrompt}
              </p>
            </div>
          )}

          {/* Grid Stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 pt-4 border-t border-gray-800">
            <div>
              <span className="text-xs text-gray-500 block mb-1">
                Steps
              </span>
              <span className="text-sm font-medium text-white bg-gray-800 px-2 py-1 rounded">
                {metadata.steps}
              </span>
            </div>
            <div>
              <span className="text-xs text-gray-500 block mb-1">CFG</span>
              <span className="text-sm font-medium text-white bg-gray-800 px-2 py-1 rounded">
                {metadata.cfg}
              </span>
            </div>
            <div>
              <span className="text-xs text-gray-500 block mb-1">
                Sampler
              </span>
              <span
                className="text-sm font-medium text-white bg-gray-800 px-2 py-1 rounded truncate"
                title={metadata.sampler}
              >
                {metadata.sampler}
              </span>
            </div>
            <div>
              <span className="text-xs text-gray-500 block mb-1">Seed</span>
              <span
                className="text-sm font-medium text-white bg-gray-800 px-2 py-1 rounded truncate"
                title={metadata.seed}
              >
                {metadata.seed}
              </span>
            </div>
          </div>
        </>
      ) : (
        <div className="text-center text-gray-500 text-sm py-4">
          No metadata available
        </div>
      )}
    </div>
  );
}
