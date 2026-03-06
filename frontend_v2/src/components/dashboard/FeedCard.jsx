import { useState, memo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronUp,
  Check,
  RefreshCw,
  Download,
  Trash2,
  Loader2,
  Sparkles,
  Copy,
  Image as ImageIcon,
  Paintbrush,
  MoreHorizontal,
} from "lucide-react";
import toast from "react-hot-toast";

import { useGeneratorStore } from "../../store/generatorStore";
import useSettingsStore from "../../store/settingsStore";
import ProgressiveImage from "../ProgressiveImage";
import ContextMenu, { createImageActions } from "../ContextMenu";

const FeedCard = memo(function FeedCard({
  item,
  selected,
  onSelect,
  onClick,
  selectionMode,
  onDelete,
}) {
  const [showDetails, setShowDetails] = useState(false);
  const navigate = useNavigate();
  const settings = useSettingsStore((state) => state.settings);

  // Use React Query for metadata fetching with caching
  const { data: metadata, isLoading: loading } = useQuery({
    queryKey: ["metadata", item.name],
    queryFn: async () => {
      const res = await fetch(`/api/view/output/${item.name}.json`);
      if (res.ok) return res.json();
      return null;
    },
    enabled: true, // Always fetch for header display - fixes "invalid model" issue
    staleTime: Infinity, // Metadata doesn't change
  });

  const handleReuse = async () => {
    // Fetch metadata if not loaded yet
    let meta = metadata;
    if (!meta) {
      try {
        const res = await fetch(`/api/view/output/${item.name}.json`);
        if (res.ok) {
          meta = await res.json();
        } else {
          console.error("Failed to load metadata");
          return;
        }
      } catch (error) {
        console.error("Error loading metadata:", error);
        return;
      }
    }

    // Update global store directly
    useGeneratorStore.getState().setAll({
      prompt: meta.prompt,
      negativePrompt: meta.negativePrompt,
      seed: meta.seed,
      steps: meta.steps,
      cfg: meta.cfg,
      sampler: meta.sampler,
      scheduler: meta.scheduler,
      width: meta.width,
      height: meta.height,
      selectedCheckpoint: meta.checkpoint,
      selectedLoras: meta.loras || [],
      hiresFix: meta.hiresFix,
      hiresUpscaler: meta.hiresUpscaler,
      adetailer: meta.adetailer,
      adetailerModel: meta.adetailerModel,
    });

    // Disable auto-randomize seed to allow reproduction of the same image
    useSettingsStore
      .getState()
      .updateSetting("generator", "autoRandomizeSeed", false);

    toast.success(
      "Parameters loaded! Auto-randomize seed disabled for reproduction.",
      {
        icon: "🎯",
        duration: settings.ui.toastSuccessDuration,
      },
    );

    navigate("/generate");
  };

  // Quick Remix: Load params, randomize seed, and generate immediately
  const [remixing, setRemixing] = useState(false);

  const handleRemix = async () => {
    if (remixing) return;
    setRemixing(true);

    try {
      // Fetch metadata
      let meta = metadata;
      if (!meta) {
        const res = await fetch(`/api/view/output/${item.name}.json`);
        if (res.ok) {
          meta = await res.json();
        } else {
          toast.error("Failed to load image metadata");
          return;
        }
      }

      // Generate new random seed
      const newSeed = Math.floor(Math.random() * Number.MAX_SAFE_INTEGER);

      // Build workflow using WorkflowBuilder (import dynamically to avoid circular deps)
      const { WorkflowBuilder } = await import("../../utils/workflowBuilder");
      const builder = new WorkflowBuilder();
      const workflow = builder.build({
        prompt: meta.prompt,
        negativePrompt: meta.negativePrompt,
        seed: newSeed,
        steps: meta.steps,
        cfg: meta.cfg,
        sampler: meta.sampler,
        scheduler: meta.scheduler,
        width: meta.width,
        height: meta.height,
        checkpoint:
          typeof meta.checkpoint === "object"
            ? meta.checkpoint.name
            : meta.checkpoint,
        loras: meta.loras || [],
        hiresFix: meta.hiresFix,
        hiresUpscaler: meta.hiresUpscaler,
        adetailer: meta.adetailer,
        adetailerModel: meta.adetailerModel,
      });

      // Submit job
      const jobData = {
        workflow,
        metadata: {
          ...meta,
          seed: newSeed,
        },
      };

      const response = await fetch("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(jobData),
      });

      if (response.ok) {
        toast.success("Remix queued! Creating variation...", {
          icon: "✨",
          duration: settings.ui.toastSuccessDuration,
        });
      } else {
        throw new Error("Failed to queue remix");
      }
    } catch (error) {
      console.error("Remix error:", error);
      toast.error("Failed to create remix");
    } finally {
      setRemixing(false);
    }
  };

  // Navigate to Img2Img with this image as source
  const handleImg2Img = useCallback(async () => {
    try {
      // Upload the image for Img2Img use
      const response = await fetch(`/api/view/output/${item.name}`);
      const blob = await response.blob();

      // Get image dimensions
      const img = new Image();
      img.src = URL.createObjectURL(blob);
      await new Promise((resolve) => {
        img.onload = resolve;
      });

      navigate("/img2img", {
        state: {
          sourceImage: {
            filename: item.name,
            previewUrl: URL.createObjectURL(blob),
            width: img.width,
            height: img.height,
            needsSync: true,
          },
        },
      });
      toast.success("Image loaded for Img2Img", { icon: "🖼️" });
    } catch (error) {
      console.error("Failed to load image for Img2Img:", error);
      toast.error("Failed to load image");
    }
  }, [item.name, navigate]);

  // Navigate to Inpaint with this image as source
  const handleInpaint = useCallback(async () => {
    try {
      // Fetch the image for Inpaint use
      const response = await fetch(`/api/view/output/${item.name}`);
      const blob = await response.blob();

      // Get image dimensions
      const img = new Image();
      img.src = URL.createObjectURL(blob);
      await new Promise((resolve) => {
        img.onload = resolve;
      });

      navigate("/inpaint", {
        state: {
          sourceImage: {
            filename: item.name,
            previewUrl: URL.createObjectURL(blob),
            width: img.width,
            height: img.height,
            needsSync: true,
          },
        },
      });
      toast.success("Image loaded for Inpainting", { icon: "🎨" });
    } catch (error) {
      console.error("Failed to load image for Inpaint:", error);
      toast.error("Failed to load image");
    }
  }, [item.name, navigate]);

  return (
    <div
      className={`bg-gray-800 rounded-2xl overflow-hidden border transition-all ${selected ? "border-blue-500 ring-2 ring-blue-500/50" : "border-gray-700"}`}
    >
      {/* Header */}
      <div className="p-4 border-b border-gray-700 flex justify-between items-center bg-gray-900/50 gap-4">
        <div className="flex items-center gap-3 min-w-0 flex-1">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-blue-500 to-purple-500 flex items-center justify-center text-xs font-bold flex-shrink-0">
            AI
          </div>
          <div className="min-w-0">
            <h3 className="text-sm font-bold text-white truncate">
              {loading
                ? "Loading..."
                : (typeof metadata?.checkpoint === "object"
                    ? metadata.checkpoint.display_name ||
                      metadata.checkpoint.name
                    : metadata?.checkpoint
                  )?.replace(".safetensors", "") || "Unknown Model"}
            </h3>
            <p className="text-xs text-gray-400 truncate">
              {(() => {
                const timestamp = item.date || item.mtime;
                if (!timestamp) return "Unknown date";

                let date;
                if (typeof timestamp === "string") {
                  // ISO string or similar
                  date = new Date(
                    timestamp.endsWith("Z") ? timestamp : timestamp + "Z",
                  );
                } else if (timestamp > 1e12) {
                  // Milliseconds (13+ digits)
                  date = new Date(timestamp);
                } else if (timestamp > 0) {
                  // Seconds (Unix timestamp)
                  date = new Date(timestamp * 1000);
                } else {
                  return "Unknown date";
                }

                return isNaN(date.getTime())
                  ? "Unknown date"
                  : date.toLocaleString();
              })()}
            </p>
          </div>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={() => setShowDetails(!showDetails)}
            className={`p-2 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors ${showDetails ? "bg-gray-800" : ""}`}
            title={showDetails ? "Hide Details" : "Show Details"}
            aria-label={showDetails ? "Hide Details" : "Show Details"}
            aria-pressed={showDetails}
          >
            {showDetails ? <ChevronUp size={18} /> : <ChevronDown size={18} />}
          </button>
          {selectionMode ? (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onSelect(item.name);
              }}
              className={`p-2 rounded-lg ${selected ? "bg-blue-500 text-white" : "bg-gray-700 text-gray-400"}`}
              aria-label={selected ? "Deselect item" : "Select item"}
              aria-pressed={selected}
            >
              <Check size={18} />
            </button>
          ) : (
            <>
              {/* Primary actions - always visible */}
              <button
                onClick={handleReuse}
                className="p-2 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white"
                title="Reuse Parameters"
                aria-label="Reuse Parameters"
              >
                <RefreshCw size={18} />
              </button>
              <a
                href={`/api/view/output/${item.name}`}
                download
                className="p-2 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white flex items-center"
                title="Download"
                aria-label="Download"
              >
                <Download size={18} />
              </a>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  onDelete(item.name);
                }}
                className="p-2 hover:bg-red-900/50 rounded-lg text-gray-400 hover:text-red-400"
                title="Delete"
                aria-label="Delete"
              >
                <Trash2 size={18} />
              </button>

              {/* Secondary actions - visible on md+ screens */}
              <div className="hidden md:flex gap-2">
                <button
                  onClick={handleRemix}
                  disabled={remixing}
                  className="p-2 hover:bg-purple-900/50 rounded-lg text-gray-400 hover:text-purple-400 disabled:opacity-50"
                  title="Quick Remix (new seed)"
                  aria-label="Quick Remix (new seed)"
                >
                  {remixing ? (
                    <Loader2 size={18} className="animate-spin" />
                  ) : (
                    <Sparkles size={18} />
                  )}
                </button>
                <button
                  onClick={handleImg2Img}
                  className="p-2 hover:bg-orange-900/50 rounded-lg text-gray-400 hover:text-orange-400"
                  title="Use as Img2Img source"
                  aria-label="Use as Img2Img source"
                >
                  <ImageIcon size={18} />
                </button>
                <button
                  onClick={handleInpaint}
                  className="p-2 hover:bg-pink-900/50 rounded-lg text-gray-400 hover:text-pink-400"
                  title="Inpaint this image"
                  aria-label="Inpaint this image"
                >
                  <Paintbrush size={18} />
                </button>
              </div>

              {/* Mobile overflow menu - visible only on small screens */}
              <div className="md:hidden relative group">
                <button
                  className="p-2 hover:bg-gray-700 rounded-lg text-gray-400 hover:text-white"
                  title="More actions"
                  aria-label="More actions"
                >
                  <MoreHorizontal size={18} />
                </button>
                {/* Dropdown menu */}
                <div className="absolute right-0 top-full mt-1 bg-gray-900 border border-gray-700 rounded-lg shadow-xl py-1 z-10 opacity-0 invisible group-focus-within:opacity-100 group-focus-within:visible transition-all min-w-[160px]">
                  <button
                    onClick={handleRemix}
                    disabled={remixing}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left text-gray-300 hover:bg-gray-800 disabled:opacity-50"
                  >
                    {remixing ? (
                      <Loader2 size={16} className="animate-spin" />
                    ) : (
                      <Sparkles size={16} />
                    )}
                    Remix
                  </button>
                  <button
                    onClick={handleImg2Img}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left text-gray-300 hover:bg-gray-800"
                  >
                    <ImageIcon size={16} />
                    Img2Img
                  </button>
                  <button
                    onClick={handleInpaint}
                    className="w-full flex items-center gap-3 px-4 py-2.5 text-sm text-left text-gray-300 hover:bg-gray-800"
                  >
                    <Paintbrush size={16} />
                    Inpaint
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Image with Context Menu */}
      <ContextMenu
        disabled={selectionMode}
        actions={createImageActions({
          onCopySeed: async () => {
            let meta = metadata;
            if (!meta) {
              try {
                const res = await fetch(`/api/view/output/${item.name}.json`);
                if (res.ok) meta = await res.json();
              } catch {
                // Metadata sidecar is optional; seed copy falls back to unavailable state.
              }
            }
            if (meta?.seed) {
              navigator.clipboard.writeText(String(meta.seed));
              toast.success(`Seed copied: ${meta.seed}`, { icon: "📋" });
            } else {
              toast.error("Seed not available");
            }
          },
          onDownload: () => {
            const link = document.createElement("a");
            link.href = `/api/view/output/${item.name}`;
            link.download = item.name;
            link.click();
          },
          onViewParams: () => onClick(item),
          onRemix: handleRemix,
          onDelete: () => onDelete(item.name),
        })}
      >
        <div
          className="relative group cursor-pointer bg-black/50"
          onClick={() => {
            if (selectionMode) onSelect(item.name);
            else onClick(item);
          }}
        >
          <ProgressiveImage
            blurhash={item.blurhash}
            src={`/api/view/output/${item.name}`}
            medium={item.thumbnail_medium || item.medium}
            alt={item.name}
            size="full"
            aspectRatio="auto"
            className="w-full"
          />
        </div>
      </ContextMenu>

      {/* Details */}
      {showDetails && (
        <div className="p-6 space-y-6 bg-gray-900/30 border-t border-gray-800">
          {loading ? (
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
      )}
    </div>
  );
});

export default FeedCard;
