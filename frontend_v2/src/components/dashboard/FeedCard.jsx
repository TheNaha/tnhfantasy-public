import { useState, useRef, memo, useCallback, useId } from "react";
import { useNavigate } from "react-router-dom";
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

import { api, ApiError, createIdempotencyKey } from "../../api";
import { useGeneratorStore } from "../../store/generatorStore";
import useSettingsStore from "../../store/settingsStore";
import ProgressiveImage from "../ProgressiveImage";
import ContextMenu, { createImageActions } from "../ContextMenu";
import { getCheckpointDisplayName } from "../../utils/modelDisplay";
import { formatTimestamp } from "../../utils/dateTime";
import {
  buildGeneratorStateFromMetadata,
  hydrateGeneratorStateModelVisuals,
} from "../../utils/reuseParameters";
import FeedCardDetails from "./feed-card/FeedCardDetails";
import FeedCardActions from "./feed-card/FeedCardActions";

const FeedCard = memo(function FeedCard({
  item,
  selected,
  onSelect,
  onClick,
  selectionMode,
  onDelete,
}) {
  const [showDetails, setShowDetails] = useState(false);
  const [reusing, setReusing] = useState(false);
  const reuseLockRef = useRef(false);
  const navigate = useNavigate();
  const settings = useSettingsStore((state) => state.settings);
  const encodedName = encodeURIComponent(item.name);
  const metadataEndpoint = `/api/view/output/${encodedName}.json`;
  const imageEndpoint = `/api/view/output/${encodedName}`;
  const detailsId = useId();

  // Use item.metadata from the gallery indexer (already fetched with the file list)
  // Lazy-load full metadata only when user expands details, reuses, or remixes
  const [fetchedMetadata, setFetchedMetadata] = useState(null);
  const [detailsLoading, setDetailsLoading] = useState(false);
  const fetchInProgressRef = useRef(false);

  const metadata = fetchedMetadata || item.metadata;

  const ensureMetadata = useCallback(async () => {
    if (metadata) return metadata;
    if (fetchInProgressRef.current) return null;
    fetchInProgressRef.current = true;
    try {
      const data = await api.get(metadataEndpoint);
      setFetchedMetadata(data);
      return data;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    } finally {
      fetchInProgressRef.current = false;
    }
  }, [metadata, metadataEndpoint]);

  const loadImageBlob = useCallback(async () => {
    const response = await fetch(imageEndpoint);
    if (!response.ok) throw new Error(`Failed to load image: ${response.status}`);
    return response.blob();
  }, [imageEndpoint]);

  const handleReuse = async () => {
    if (reuseLockRef.current) {
      return;
    }

    reuseLockRef.current = true;
    setReusing(true);

    try {
      let meta = await ensureMetadata();
      if (!meta) {
        toast.error("Failed to load metadata");
        return;
      }

      const reuseState = buildGeneratorStateFromMetadata(meta);
      if (Object.keys(reuseState).length === 0) {
        toast.error("Could not parse reusable parameters from this image.");
        return;
      }

      const hydratedState = await hydrateGeneratorStateModelVisuals(reuseState);

      useGeneratorStore.getState().setAll(hydratedState);

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
    } finally {
      reuseLockRef.current = false;
      setReusing(false);
    }
  };

  // Quick Remix: Load params, randomize seed, and generate immediately
  const [remixing, setRemixing] = useState(false);

  const handleRemix = async () => {
    if (remixing) return;
    setRemixing(true);

    try {
      let meta = await ensureMetadata();
      if (!meta) {
        toast.error("Failed to load image metadata");
        return;
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

      await api.post("/api/generate", jobData, {
        idempotencyKey: createIdempotencyKey("generate-remix"),
      });
      toast.success("Remix queued! Creating variation...", {
        icon: "✨",
        duration: settings.ui.toastSuccessDuration,
      });
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
      const blob = await loadImageBlob();

      const dimensionUrl = URL.createObjectURL(blob);
      const img = new Image();
      img.src = dimensionUrl;
      await new Promise((resolve) => {
        img.onload = resolve;
      });
      URL.revokeObjectURL(dimensionUrl);

      const previewUrl = URL.createObjectURL(blob);
      navigate("/img2img", {
        state: {
          sourceImage: {
            filename: item.name,
            previewUrl,
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
  }, [item.name, loadImageBlob, navigate]);

  // Navigate to Inpaint with this image as source
  const handleInpaint = useCallback(async () => {
    try {
      const blob = await loadImageBlob();

      const dimensionUrl = URL.createObjectURL(blob);
      const img = new Image();
      img.src = dimensionUrl;
      await new Promise((resolve) => {
        img.onload = resolve;
      });
      URL.revokeObjectURL(dimensionUrl);

      const previewUrl = URL.createObjectURL(blob);
      navigate("/inpaint", {
        state: {
          sourceImage: {
            filename: item.name,
            previewUrl,
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
  }, [item.name, loadImageBlob, navigate]);

  const handleShowDetails = async () => {
    if (!showDetails && !metadata) {
      setDetailsLoading(true);
      await ensureMetadata();
      setDetailsLoading(false);
    }
    setShowDetails(!showDetails);
  };

  const checkpointDisplayName = getCheckpointDisplayName(metadata) || getCheckpointDisplayName(item) || "Unknown Model";

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
              {checkpointDisplayName}
            </h3>
            <p className="text-xs text-gray-400 truncate">
              {formatTimestamp(item.date || item.mtime)}
            </p>
          </div>
        </div>
        <div className="flex gap-2 flex-shrink-0">
          <button
            onClick={handleShowDetails}
            className={`p-2 rounded-lg hover:bg-gray-700 text-gray-400 hover:text-white transition-colors ${showDetails ? "bg-gray-800" : ""}`}
            title={showDetails ? "Hide Details" : "Show Details"}
            aria-label={showDetails ? "Hide Details" : "Show Details"}
            aria-pressed={showDetails}
            aria-expanded={showDetails}
            aria-controls={detailsId}
          >
            {showDetails ? <ChevronUp size={18} aria-hidden="true" /> : <ChevronDown size={18} aria-hidden="true" />}
          </button>
          <FeedCardActions
            item={item}
            selected={selected}
            selectionMode={selectionMode}
            onSelect={onSelect}
            reusing={reusing}
            remixing={remixing}
            imageEndpoint={imageEndpoint}
            handleReuse={handleReuse}
            handleRemix={handleRemix}
            handleImg2Img={handleImg2Img}
            handleInpaint={handleInpaint}
            onDelete={onDelete}
          />
        </div>
      </div>

      {/* Image with Context Menu */}
      <ContextMenu
        disabled={selectionMode}
        actions={createImageActions({
        onCopySeed: async () => {
          const meta = await ensureMetadata();
          if (meta?.seed) {
              navigator.clipboard.writeText(String(meta.seed));
              toast.success(`Seed copied: ${meta.seed}`, { icon: "📋" });
            } else {
              toast.error("Seed not available");
            }
          },
          onDownload: () => {
            const link = document.createElement("a");
            link.href = imageEndpoint;
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
            src={imageEndpoint}
            medium={item.thumbnail_medium || item.medium}
            alt={item.name}
            size="full"
            aspectRatio="auto"
            className="w-full"
          />
        </div>
      </ContextMenu>

      {/* Details */}
      <FeedCardDetails
        detailsId={detailsId}
        showDetails={showDetails}
        detailsLoading={detailsLoading}
        metadata={metadata}
      />
    </div>
  );
});

export default FeedCard;
