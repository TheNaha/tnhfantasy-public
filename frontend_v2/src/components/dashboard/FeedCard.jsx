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
import { useQueryClient } from "@tanstack/react-query";
import toast from "react-hot-toast";

import { api, ApiError, createIdempotencyKey, generateApi } from "../../api";
import useSettingsStore from "../../store/settingsStore";
import ProgressiveImage from "../ProgressiveImage";
import ContextMenu, { createImageActions } from "../ContextMenu";
import { getCheckpointDisplayName } from "../../utils/modelDisplay";
import { assetMetadataUrl, assetUrl } from "../../utils/assetUrl";
import { formatTimestamp } from "../../utils/dateTime";
import { copyToClipboard } from "../../utils/clipboard";
import {
  applyGeneratorStateFromMetadata,
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
  const metadataEndpoint = assetMetadataUrl(item.name);
  const imageEndpoint = assetUrl(item.name);
  const detailsId = useId();

  // Lazy-load full metadata using React Query when user expands details, reuses, or remixes
  const queryClient = useQueryClient();
  const [detailsLoading, setDetailsLoading] = useState(false);

  // If we already have it in the react-query cache, we can use it immediately.
  const cachedMeta = queryClient.getQueryData(['metadata', item.name]);
  const metadata = cachedMeta || item.metadata;

  const ensureMetadata = useCallback(async () => {
    if (metadata) return metadata;
    try {
      const data = await queryClient.fetchQuery({
        queryKey: ['metadata', item.name],
        queryFn: () => api.get(metadataEndpoint),
        staleTime: Infinity, // metadata doesn't change
      });
      return data;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }, [metadata, item.name, metadataEndpoint, queryClient]);

  const loadImageBlob = useCallback(async () => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(imageEndpoint, { signal: controller.signal });
      if (!response.ok) throw new Error(`Failed to load image: ${response.status}`);
      return response.blob();
    } finally {
      clearTimeout(timer);
    }
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

      const applied = await applyGeneratorStateFromMetadata(meta);
      if (!applied) {
        toast.error("Could not parse reusable parameters from this image.");
        return;
      }

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

      // Build options
      const options = {
        mode: meta.type || 't2i',
        ...meta,
        seed: newSeed,
        // Override the image input to make sure it feeds correctly for img2img
        inputImage: meta.sourceImage, 
        checkpoint: meta.checkpoint?.name || meta.checkpoint,
        unet: meta.unet?.name || meta.unet,
        clip: meta.clip?.name || meta.clip,
        vae: meta.vae?.name || meta.vae,
        clip2: meta.clip2?.name || meta.clip2,
        loras: meta.loras?.map(l => ({ name: l.name || l, strength: l.strength || 1.0 })),
        controlnets: meta.controlnets?.map(c => ({
            name: c.name || c,
            image: c.image,
            preprocessor: c.preprocessor || "None",
            strength: c.strength || 1.0
        })),
        ipAdapters: meta.ipAdapters?.map(ip => ({
            model: ip.model,
            clipVision: ip.clipVision,
            image: ip.image,
            weight: ip.weight || 1.0
        }))
      };

      const metadata = {
        ...meta,
        seed: newSeed,
      };

      await generateApi.workflow(options, metadata, {
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
    } catch {
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
    } catch {
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

  const handleMoveAsset = useCallback(async () => {
    const assetId = item.id || item.name;
    const workspace = prompt("Move to workspace (leave empty to keep current):") || undefined;
    if (window.confirm(`Move asset ${item.name} to workspace: ${workspace || 'current'}?`)) {
      try {
        await api.post(`/api/v2/assets/${assetId}/move`, {
          workspace: workspace || item.workspace || 'main',
          copy: false,
        });
        toast.success("Asset moved", { icon: "📁" });
        queryClient.invalidateQueries({ queryKey: ['gallery'] });
      } catch {
        toast.error("Failed to move asset");
      }
    }
  }, [item, queryClient]);

  const handleCopyAsset = useCallback(async () => {
    const assetId = item.id || item.name;
    const workspace = prompt("Copy to workspace (leave empty for current):") || undefined;
    if (window.confirm(`Copy asset ${item.name} to workspace: ${workspace || 'current'}?`)) {
      try {
        await api.post(`/api/v2/assets/${assetId}/move`, {
          workspace: workspace || item.workspace || 'main',
          copy: true,
        });
        toast.success("Asset copied", { icon: "📋" });
        queryClient.invalidateQueries({ queryKey: ['gallery'] });
      } catch {
        toast.error("Failed to copy asset");
      }
    }
  }, [item, queryClient]);

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
              await copyToClipboard(String(meta.seed));
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
          onMoveAsset: handleMoveAsset,
          onCopyAsset: handleCopyAsset,
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
