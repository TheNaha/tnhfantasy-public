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
import { useConfirmation } from "../../store/confirmationStore";

import { api, ApiError, createIdempotencyKey, generateApi } from "../../api";
import { GUIDED } from "../../api/generate";
import useSettingsStore from "../../store/settingsStore";
import ProgressiveImage from "../ProgressiveImage";
import ContextMenu, { createImageActions } from "../ContextMenu";
import { checkpointName, getCheckpointDisplayName } from "../../utils/modelDisplay";
import { assetMetadataUrl, assetUrl, assetPath } from "../../utils/assetUrl";
import { formatTimestamp } from "../../utils/dateTime";
import { copyToClipboard } from "../../utils/clipboard";
import {
  applyGeneratorStateFromMetadata,
} from "../../utils/reuseParameters";
import { buildGeneratorPayload } from "../../hooks/useWorkflowBuilder";
import { useGenerationPreflight } from "../../hooks/useGenerationPreflight";
import FeedCardDetails from "./feed-card/FeedCardDetails";
import FeedCardActions from "./feed-card/FeedCardActions";
import { refetchNewestGalleryPage } from "../../hooks/useGallery";

/**
 * Ceiling for the intrinsic-size probe. A blob that decodes normally settles in
 * single-digit milliseconds; without a ceiling a blob the browser refuses to
 * decode leaves the promise pending and the menu item permanently inert.
 */
const DIMENSION_PROBE_TIMEOUT_MS = 10000;

/**
 * A model NAME, whichever shape the metadata carried it in.
 *
 * The guided path stores the model RECORD; the backend's graph-derived
 * metadata stores the name. Both are legitimate, so both are read.
 */
function modelName(value) {
  if (!value) return null;
  if (typeof value === "string") return value;
  if (typeof value === "object") return value.name || value.display_name || null;
  return null;
}

/**
 * The model a job's metadata names, as the RESOLVED model fields.
 *
 * The loader is chosen from `unet` + `clip`, not from the mode, so a job
 * that ran a UNET has to be remixed as a UNET. The remix used to assemble
 * its own options and sent `unet: undefined, clip: undefined` for a guided
 * Flux image - the metadata never carried them - so the backend built
 * `CheckpointLoaderSimple{ckpt_name: "flux1-dev.safetensors"}` and asked
 * models/checkpoints/ for a file that lives in models/unet/.
 */
function remixModel(meta) {
  const unet = modelName(meta.unet);
  const clip = modelName(meta.clip);
  const clip2 = modelName(meta.clip2);
  const vae = modelName(meta.vae);
  const checkpoint = checkpointName(meta);

  return {
    // A UNET model has no checkpoint to name: the backend keys the loader
    // on `unet`, and a UNET does not live in models/checkpoints/.
    checkpoint: unet ? null : checkpoint,
    unet,
    clip,
    clip2,
    vae,
    modelType: meta.modelType || null,
  };
}

/**
 * The generator state a job's metadata describes.
 *
 * This is the store's shape, so the shared builder can read it. The remix
 * used to spread the metadata into an options object of its own, which is
 * how it lost the model type, the IP adapter's "Stop At", and every
 * deliberate zero: `strength || 1.0` turned a LoRA the user had turned off
 * back on.
 */
function remixSnapshot(meta) {
  const model = remixModel(meta);
  const record = meta.checkpoint && typeof meta.checkpoint === "object"
    ? meta.checkpoint
    : (model.checkpoint ? { name: model.checkpoint, display_name: model.checkpoint } : null);

  return {
    prompt: meta.prompt,
    negativePrompt: meta.negativePrompt,
    steps: meta.steps,
    cfg: meta.cfg,
    sampler: meta.sampler,
    scheduler: meta.scheduler,
    width: meta.width,
    height: meta.height,
    batchSize: meta.batchSize,
    clipSkip: meta.clipSkip,
    selectedCheckpoint: record,
    selectedVae: model.vae,
    selectedClip: model.clip,
    selectedClip2: model.clip2,
    model,
    selectedLoras: meta.loras,
    controlnets: meta.controlnets,
    ipAdapters: meta.ipAdapters,
    hiresFix: meta.hiresFix,
    hiresUpscaler: meta.hiresUpscaler,
    hiresDenoise: meta.hiresDenoise,
    hiresUpscale: meta.hiresUpscale,
    hiresSteps: meta.hiresSteps,
    adetailer: meta.adetailer,
    adetailerModel: meta.adetailerModel,
    adetailerPrompt: meta.adetailerPrompt,
    adetailerSteps: meta.adetailerSteps,
    adetailerDenoise: meta.adetailerDenoise,
    adetailerInpaintMasked: meta.adetailerInpaintMasked,
    enableFreeU: meta.enableFreeU,
    enablePAG: meta.enablePAG,
    pagScale: meta.pagScale,
    enableLatentUpscale: meta.enableLatentUpscale,
    latentUpscaleMultiplier: meta.latentUpscaleMultiplier,
    sourceImage: meta.sourceImage ? { filename: meta.sourceImage } : null,
    denoise: meta.denoise,
    maskBlur: meta.maskBlur,
    growMask: meta.growMask,
  };
}

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
  const itemPath = assetPath(item);
  const metadataEndpoint = assetMetadataUrl(itemPath);
  const imageEndpoint = assetUrl(itemPath);
  const detailsId = useId();

  // Lazy-load full metadata using React Query when user expands details, reuses, or remixes
  const queryClient = useQueryClient();
  const { confirm } = useConfirmation();
  const [detailsLoading, setDetailsLoading] = useState(false);

  // If we already have it in the react-query cache, we can use it immediately.
  const cachedMeta = queryClient.getQueryData(['metadata', itemPath]);
  const metadata = cachedMeta || item.metadata;

  const ensureMetadata = useCallback(async () => {
    if (metadata) return metadata;
    try {
      const data = await queryClient.fetchQuery({
        queryKey: ['metadata', itemPath],
        queryFn: () => api.get(metadataEndpoint),
        staleTime: Infinity, // metadata doesn't change
      });
      return data;
    } catch (error) {
      if (error instanceof ApiError && error.status === 404) return null;
      throw error;
    }
  }, [metadata, itemPath, metadataEndpoint, queryClient]);

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

  /**
   * Read the intrinsic size off a freshly fetched blob.
   *
   * Both call sites used to be `new Promise(resolve => { img.onload = resolve })`
   * with no `onerror` and no timeout, so a blob the browser could not decode —
   * a truncated file, a 200 response that is not an image, a decode that never
   * settles — left the promise pending forever: the `catch` in
   * `openSourceImage` was never reached, `dimensionUrl` was never revoked, and
   * the menu item was inert with no way back. Every exit path now settles.
   */
  const readImageDimensions = useCallback(async (blob) => {
    const dimensionUrl = URL.createObjectURL(blob);
    try {
      return await new Promise((resolve, reject) => {
        const img = new Image();
        let timer = null;
        const settle = (fn, value) => {
          if (timer !== null) clearTimeout(timer);
          timer = null;
          img.onload = null;
          img.onerror = null;
          fn(value);
        };
        timer = setTimeout(
          () => settle(reject, new Error("Timed out reading image dimensions")),
          DIMENSION_PROBE_TIMEOUT_MS
        );
        img.onload = () => settle(resolve, {
          width: img.naturalWidth || img.width,
          height: img.naturalHeight || img.height,
        });
        img.onerror = () => settle(reject, new Error("Image could not be decoded"));
        img.src = dimensionUrl;
      });
    } finally {
      URL.revokeObjectURL(dimensionUrl);
    }
  }, []);

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
  const { runWithPreflight } = useGenerationPreflight();

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

      // The SAME builder the generator pages use, fed from this job's
      // metadata. The remix used to assemble an options object of its own -
      // a second request builder that had to agree with the first one, and
      // did not: it lost the UNET and its text encoders, the model type and
      // the IP adapter's "Stop At", and its `|| 1.0` fallbacks turned a
      // deliberate `strength: 0` back into full strength.
      const { options, metadata } = buildGeneratorPayload(
        meta.type || "t2i",
        remixSnapshot(meta),
        {
          seed: newSeed,
          maskResult: meta.maskImage ? { filename: meta.maskImage } : undefined,
        }
      );

      // The preflight, like the generator pages: a remix of a model that is
      // not installed should say so before the job is created, not fail on
      // the provider a minute later.
      const { ok } = await runWithPreflight(options, {
        onValid: async () =>
          generateApi.workflow(options, metadata, {
            kind: GUIDED,
            idempotencyKey: createIdempotencyKey("generate-remix"),
          }),
      });
      if (!ok) return;

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

  // Navigate to Img2Img / Inpaint with this image as source.
  //
  // The preview handed to the route is `imageEndpoint`, the same URL the card
  // already renders, and not a second `URL.createObjectURL(blob)`. The blob
  // round-trip bought nothing: the target pages fall back to their own asset
  // URL when `previewUrl` is absent, `ImageUploader` only revokes `blob:`
  // URLs, and the object URL was never revoked here — it was handed to
  // `navigate()` and forgotten, and `generatorStore.partialize` drops
  // `sourceImage`, so nothing on a reload could reclaim it either. The blob is
  // now scoped to the dimension probe, which revokes it on every path.
  const openSourceImage = useCallback(async (route, successToast, icon) => {
    try {
      const blob = await loadImageBlob();
      const { width, height } = await readImageDimensions(blob);

      navigate(route, {
        state: {
          sourceImage: {
            filename: itemPath,
            previewUrl: imageEndpoint,
            width,
            height,
            needsSync: true,
          },
        },
      });
      toast.success(successToast, { icon });
    } catch {
      toast.error("Failed to load image");
    }
  }, [imageEndpoint, itemPath, loadImageBlob, navigate, readImageDimensions]);

  const handleImg2Img = useCallback(
    () => openSourceImage("/img2img", "Image loaded for Img2Img", "🖼️"),
    [openSourceImage]
  );

  const handleInpaint = useCallback(
    () => openSourceImage("/inpaint", "Image loaded for Inpainting", "🎨"),
    [openSourceImage]
  );

  const handleShowDetails = async () => {
    if (!showDetails && !metadata) {
      setDetailsLoading(true);
      await ensureMetadata();
      setDetailsLoading(false);
    }
    setShowDetails(!showDetails);
  };

  const handleMoveAsset = useCallback(async () => {
    const assetId = item.id || itemPath;
    const workspace = prompt("Move to workspace (leave empty to keep current):") || undefined;
    const ok = await confirm({
        title: 'Move Asset',
        message: `Move asset ${item.name} to workspace: ${workspace || 'current'}?`,
        confirmText: 'Move',
    });
    if (ok) {
      try {
        await api.post(`/api/v2/assets/${assetId}/move`, {
          workspace: workspace || item.workspace || 'main',
          copy_file: false,
        });
        toast.success("Asset moved", { icon: "📁" });
        await refetchNewestGalleryPage(queryClient);
      } catch {
        toast.error("Failed to move asset");
      }
    }
  }, [item, itemPath, queryClient, confirm]);

  const handleCopyAsset = useCallback(async () => {
    const assetId = item.id || itemPath;
    const workspace = prompt("Copy to workspace (leave empty for current):") || undefined;
    const ok = await confirm({
        title: 'Copy Asset',
        message: `Copy asset ${item.name} to workspace: ${workspace || 'current'}?`,
        confirmText: 'Copy',
    });
    if (ok) {
      try {
        await api.post(`/api/v2/assets/${assetId}/move`, {
          workspace: workspace || item.workspace || 'main',
          copy_file: true,
        });
        toast.success("Asset copied", { icon: "📋" });
        await refetchNewestGalleryPage(queryClient);
      } catch {
        toast.error("Failed to copy asset");
      }
    }
  }, [item, itemPath, queryClient, confirm]);

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
          onDelete: () => onDelete(itemPath),
          onMoveAsset: handleMoveAsset,
          onCopyAsset: handleCopyAsset,
        })}
      >
        <div
          className="relative group cursor-pointer bg-black/50"
          onClick={() => {
            if (selectionMode) onSelect(itemPath);
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
