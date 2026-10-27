import { Loader2 } from "lucide-react";

export default function FeedCardDetails({
  detailsId,
  showDetails,
  detailsLoading,
  metadata
}) {
  if (!showDetails) return null;

  const checkpointName = metadata?.checkpoint
    ? (typeof metadata.checkpoint === 'object'
        ? (metadata.checkpoint.display_name || metadata.checkpoint.name)
        : metadata.checkpoint)
    : null;

  const hasEnhancements = Boolean(
    metadata && (
      metadata.hiresFix ||
      metadata.adetailer ||
      metadata.enableFreeU ||
      metadata.enablePAG
    )
  );

  return (
    <div id={detailsId} className="p-6 space-y-4 md:space-y-6 bg-gray-900/30 border-t border-gray-800">
      {detailsLoading ? (
        <div className="flex gap-2 items-center text-gray-500 text-sm">
          <Loader2 className="animate-spin" size={14} /> Loading details...
        </div>
      ) : metadata ? (
        <>
          {/* Model */}
          {checkpointName && (
            <div className="space-y-1">
              <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                Model
              </h4>
              <p className="text-sm font-medium text-white bg-gray-950/50 p-3 rounded-xl border border-gray-800/50 truncate" title={checkpointName}>
                {checkpointName}
              </p>
            </div>
          )}

          {/* LoRAs */}
          {metadata.loras?.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                LoRAs
              </h4>
              <div className="flex flex-wrap gap-2">
                {metadata.loras.map((lora, i) => (
                  <span
                    key={i}
                    className="px-2.5 py-1 bg-purple-500/20 text-purple-300 rounded-lg text-xs border border-purple-500/30 flex items-center gap-1.5"
                    title={lora.name}
                  >
                    <span className="font-medium truncate max-w-[200px]">
                      {lora.display_name || lora.name}
                    </span>
                    <span className="text-purple-400/80 text-[11px] font-mono">
                      ({lora.strength})
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* ControlNet */}
          {metadata.controlnets?.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                ControlNet
              </h4>
              <div className="flex flex-wrap gap-2">
                {metadata.controlnets.map((cn, i) => (
                  <span
                    key={i}
                    className="px-2.5 py-1 bg-cyan-500/15 text-cyan-300 rounded-lg text-xs border border-cyan-500/30 flex items-center gap-1.5"
                    title={cn.name}
                  >
                    <span className="font-medium truncate max-w-[200px]">
                      {cn.name ? cn.name.split('/').pop() : 'ControlNet'}
                    </span>
                    <span className="text-cyan-400/80 text-[11px] font-mono">
                      ({cn.strength ?? 1.0})
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* IP-Adapter */}
          {metadata.ipAdapters?.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                IP-Adapter
              </h4>
              <div className="flex flex-wrap gap-2">
                {metadata.ipAdapters.map((ip, i) => (
                  <span
                    key={i}
                    className="px-2.5 py-1 bg-violet-500/15 text-violet-300 rounded-lg text-xs border border-violet-500/30 flex items-center gap-1.5"
                    title={ip.model}
                  >
                    <span className="font-medium truncate max-w-[200px]">
                      {ip.model ? ip.model.split('/').pop() : 'IP-Adapter'}
                    </span>
                    <span className="text-violet-400/80 text-[11px] font-mono">
                      ({ip.weight ?? 1.0})
                    </span>
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Enhancements */}
          {hasEnhancements && (
            <div className="space-y-2">
              <h4 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                Enhancements
              </h4>
              <div className="flex flex-wrap gap-2">
                {metadata.hiresFix && (
                  <span className="px-2.5 py-1 bg-amber-500/15 text-amber-300 rounded-lg text-xs border border-amber-500/30 flex items-center gap-1.5 font-medium">
                    <span>✨ Hi-Res Fix:</span>
                    <span className="text-amber-200 font-mono">
                      {metadata.hiresUpscaler || "Active"}
                      {metadata.hiresUpscale ? ` (${metadata.hiresUpscale}x)` : ''}
                      {metadata.hiresDenoise !== undefined && metadata.hiresDenoise !== null ? ` • Denoise ${metadata.hiresDenoise}` : ''}
                      {metadata.hiresSteps ? ` • ${metadata.hiresSteps} steps` : ''}
                    </span>
                  </span>
                )}
                {metadata.adetailer && (
                  <span className="px-2.5 py-1 bg-emerald-500/15 text-emerald-300 rounded-lg text-xs border border-emerald-500/30 flex items-center gap-1.5 font-medium">
                    <span>👤 Face Detailer:</span>
                    <span className="text-emerald-200 font-mono">
                      {metadata.adetailerModel || "Active"}
                      {metadata.adetailerDenoise !== undefined && metadata.adetailerDenoise !== null ? ` • Denoise ${metadata.adetailerDenoise}` : ''}
                    </span>
                  </span>
                )}
                {metadata.enableFreeU && (
                  <span className="px-2.5 py-1 bg-indigo-500/15 text-indigo-300 rounded-lg text-xs border border-indigo-500/30 font-medium">
                    FreeU
                  </span>
                )}
                {metadata.enablePAG && (
                  <span className="px-2.5 py-1 bg-pink-500/15 text-pink-300 rounded-lg text-xs border border-pink-500/30 font-medium">
                    PAG ({metadata.pagScale ?? 3.0})
                  </span>
                )}
              </div>
            </div>
          )}

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
