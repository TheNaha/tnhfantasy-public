import { useState, useEffect, memo, useRef, useMemo, useCallback } from "react";
import {
  Search,
  Image as ImageIcon,
  Check,
  Loader2,
  ChevronDown,
  Layers,
  Info,
  Star,
} from "lucide-react";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { api, filesApi } from "../api";
import toast from "react-hot-toast";

const ModelSelector = memo(function ModelSelector({
  label,
  value,
  selectedModel: externalSelectedModel, // Accept full model object for display
  preview,
  metadata,
  onChange,
  directory, // e.g. "models/checkpoints"
  initialModels = [], // Optional initial data
  autoOpen = false, // Auto-open the modal on mount
  onAutoOpenComplete, // Callback when auto-open modal is closed
  onVersionChange, // Callback when version is changed
  onInfoClick, // NEW: Callback for info button click
}) {
  const [isOpen, setIsOpen] = useState(autoOpen);
  const [search, setSearch] = useState("");
  const [models, setModels] = useState(initialModels);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [internalSelectedModel, setInternalSelectedModel] = useState(null);
  const [hasMore, setHasMore] = useState(true);
  const [, setOffset] = useState(0);
  const offsetRef = useRef(0); // Track offset with ref to avoid stale closures
  const loadingRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const [expandedModel, setExpandedModel] = useState(null);
  const [showVersionDropdown, setShowVersionDropdown] = useState(false);

  // Use external selected model if provided, otherwise use internal
  const selectedModel = externalSelectedModel || internalSelectedModel;

  // Helper to get model data with specific version applied
  const getModelWithVersion = (model, version) => {
    if (!version) return model;
    const file = version.file || {};
    const versionImages = version.images || [];
    const previewImage = versionImages[0]?.url || model.preview;

    return {
      ...model,
      // File name for the generator (actual filename)
      name: file.filename || model.name,
      // Keep display_name from parent model
      display_name: model.display_name,
      // Keep civitai_id for preview image fallback
      civitai_id: model.civitai_id,
      // Use version-specific preview if available
      preview: previewImage,
      // Version-specific data
      base_model: version.base_model || model.base_model,
      trained_words: version.trained_words || [],
      default_version: version.name,
      version_description: version.description || "",
      selectedVersionId: version.id,
      // Size from version file
      size: file.size_kb ? file.size_kb * 1024 : model.size,
      // Keep original model reference for version switching
      _originalModel: model,
    };
  };

  // Handle autoOpen prop changes
  useEffect(() => {
    if (autoOpen) {
      setIsOpen(true);
    }
  }, [autoOpen]);

  // Handle modal close - notify parent if this was an auto-open
  const handleClose = useCallback(() => {
    setIsOpen(false);
    if (onAutoOpenComplete) {
      onAutoOpenComplete();
    }
  }, [onAutoOpenComplete]);

  // Handle Escape key to close modal
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e) => {
      if (e.key === "Escape") {
        handleClose();
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleClose]);

  // Sort and Filter state
  const [sortBy, setSortBy] = useState("name"); // 'name', 'date', 'size', 'rating'
  const [filterBaseModel, setFilterBaseModel] = useState("all"); // 'all', 'SD 1.5', 'SDXL', etc.
  const [filterType, setFilterType] = useState("all"); // 'all', 'Checkpoint', 'LORA', etc.
  const [showNSFW, setShowNSFW] = useState(true);

  // Sync initialModels
  useEffect(() => {
    if (initialModels && initialModels.length > 0) {
      setModels(initialModels);
    }
  }, [initialModels]);

  // Handle value changes - only update internal if no external model provided
  useEffect(() => {
    if (!externalSelectedModel && value) {
      const found = models.find((m) => m.name === value);
      if (found) {
        setInternalSelectedModel({
          ...found,
          preview: found.preview || preview,
          metadata: found.metadata || metadata,
        });
      } else {
        setInternalSelectedModel({
          name: value,
          preview: preview,
          metadata: metadata,
        });
      }
    } else if (!externalSelectedModel && !value) {
      setInternalSelectedModel(null);
    }
  }, [value, models, preview, metadata, externalSelectedModel]);

  const fetchModels = useCallback(async (loadMore = false) => {
    if (!directory) return;

    if (loadMore) {
      if (loadingMoreRef.current) return;
      loadingMoreRef.current = true;
      setLoadingMore(true);
    } else {
      if (loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
    }

    try {
      // Use ref for offset to avoid stale closure issues
      const currentOffset = loadMore ? offsetRef.current : 0;

      // Map frontend sortBy to API sort param
      const sortMap = {
        name: "name_asc",
        date: "date_desc",
        size: "size_desc",
        rating: "rating_desc",
      };
      const params = new URLSearchParams({
        directory,
        limit: "50",
        offset: currentOffset.toString(),
        sort: sortMap[sortBy] || "name_asc",
      });
      if (search) params.append("search", search);

      const res = await fetch(`/api/files?${params}`);
      const data = await res.json();
      const newModels = data.files || [];

      if (loadMore) {
        setModels((prev) => [...prev, ...newModels]);
        const newOffset = currentOffset + 50;
        setOffset(newOffset);
        offsetRef.current = newOffset;
      } else {
        setModels(newModels);
        setOffset(50);
        offsetRef.current = 50;
      }

      setHasMore(newModels.length === 50);
    } catch (error) {
      console.error("Failed to fetch models", error);
    } finally {
      if (loadMore) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      } else {
        loadingRef.current = false;
        setLoading(false);
      }
    }
  }, [directory, search, sortBy]);

  // Fetch models with debounce
  useEffect(() => {
    if (!isOpen) return;

    // If initialModels are provided and no directory, use initialModels only
    // This supports combining models from multiple directories (e.g., checkpoints + unet)
    if (!directory && initialModels.length > 0) {
      return; // Use provided initialModels, don't fetch
    }

    if (!directory) return; // No directory and no initialModels - nothing to show

    // Reset pagination when search or sort changes
    setOffset(0);
    offsetRef.current = 0;
    setHasMore(true);

    const timer = setTimeout(() => {
      fetchModels(false);
    }, 300);

    return () => clearTimeout(timer);
  }, [isOpen, directory, initialModels.length, fetchModels]);

  // Filter and sort models
  const filteredAndSortedModels = useMemo(() => {
    let result = [...models];

    // Apply filters
    if (filterBaseModel !== "all") {
      result = result.filter((m) => m.base_model === filterBaseModel);
    }

    if (filterType !== "all") {
      result = result.filter((m) => m.type === filterType);
    }

    if (!showNSFW) {
      result = result.filter((m) => !m.nsfw);
    }

    // Apply sorting
    result.sort((a, b) => {
      switch (sortBy) {
        case "name":
          return (a.name || "").localeCompare(b.name || "");
        case "date":
          return (b.modified_time || 0) - (a.modified_time || 0);
        case "size":
          return (b.size || 0) - (a.size || 0);
        case "rating":
          return (b.stats?.thumbsUp || 0) - (a.stats?.thumbsUp || 0);
        default:
          return 0;
      }
    });

    return result;
  }, [models, sortBy, filterBaseModel, filterType, showNSFW]);

  // Infinite scroll sentinel
  const sentinelRef = useInfiniteScroll({
    hasMore: hasMore && !loading,
    onLoadMore: () => fetchModels(true),
    loading: loadingMore,
    rootMargin: "300px",
  });

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-gray-500">{label}</label>

      {/* Trigger Box */}
      <div className="relative">
        <div className="w-full bg-gray-900 border border-gray-700 rounded-lg p-3 flex items-center gap-3 hover:border-blue-500 transition-colors text-left group">
          {/* Clickable main area */}
          <button
            onClick={() => setIsOpen(true)}
            className="flex items-center gap-3 flex-1 min-w-0"
            aria-label={`Select ${label}`}
            aria-haspopup="dialog"
            aria-expanded={isOpen}
          >
            {/* Preview Image */}
            {(() => {
              if (selectedModel?.civitai_id) {
                return (
                  <img
                    src={`/api/v2/models/preview/${selectedModel.civitai_id}`}
                    alt={selectedModel?.display_name || selectedModel?.name}
                    className="w-10 h-10 rounded object-cover bg-gray-800 flex-shrink-0"
                    onError={(e) => {
                      e.target.style.display = "none";
                    }}
                  />
                );
              }
              if (selectedModel?.preview) {
                return (
                  <img
                    src={selectedModel.preview}
                    alt={selectedModel?.name}
                    className="w-10 h-10 rounded object-cover bg-gray-800 flex-shrink-0"
                    onError={(e) => {
                      e.target.style.display = "none";
                    }}
                  />
                );
              }
              return (
                <div className="w-10 h-10 rounded bg-gray-800 flex items-center justify-center text-gray-600 group-hover:text-gray-400 flex-shrink-0">
                  <ImageIcon size={20} />
                </div>
              );
            })()}

            {/* Model Name */}
            <div className="flex-1 min-w-0 text-left">
              <div
                className="text-sm font-medium text-white truncate"
                title={selectedModel?.display_name || selectedModel?.name}
              >
                {selectedModel?.display_name ||
                  selectedModel?.name ||
                  "Select a model..."}
              </div>
              {selectedModel?.base_model && (
                <div className="text-xs text-gray-500">
                  {selectedModel.base_model}
                </div>
              )}
            </div>
          </button>

          {/* Version Selector (inside the box) */}
          {selectedModel?.versions && selectedModel.versions.length > 1 && (
            <div className="relative">
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  setShowVersionDropdown(!showVersionDropdown);
                }}
                className={`px-2 py-1 rounded text-xs font-medium flex items-center gap-1 transition-colors ${
                  showVersionDropdown
                    ? "bg-purple-500/20 text-purple-300 border border-purple-500/50"
                    : "bg-gray-800 text-gray-400 border border-gray-700 hover:border-purple-500/50 hover:text-purple-300"
                }`}
                title="Switch version"
                aria-label={`Switch version for ${selectedModel.name}`}
                aria-haspopup="true"
                aria-expanded={showVersionDropdown}
              >
                <Layers size={12} />
                <span>{selectedModel.default_version || "v1"}</span>
                <ChevronDown
                  size={12}
                  className={`transition-transform ${showVersionDropdown ? "rotate-180" : ""}`}
                />
              </button>

              {/* Version Dropdown */}
              {showVersionDropdown && (
                <div className="absolute z-50 top-full mt-1 right-0 min-w-[280px] bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
                  <div className="p-2 border-b border-gray-700 flex justify-between items-center">
                    <span className="text-xs text-gray-400 font-medium">
                      Select Version
                    </span>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        setShowVersionDropdown(false);
                      }}
                      className="text-gray-500 hover:text-white"
                    >
                      ✕
                    </button>
                  </div>
                  <div className="max-h-64 overflow-y-auto">
                    {selectedModel.versions.map((version) => {
                      const file = version.file || {};
                      const isSelected =
                        selectedModel.selectedVersionId === version.id ||
                        (version.is_default &&
                          !selectedModel.selectedVersionId);
                      return (
                        <button
                          key={version.id}
                          onClick={(e) => {
                            e.stopPropagation();
                            const modelWithVersion = getModelWithVersion(
                              selectedModel._originalModel || selectedModel,
                              version,
                            );
                            if (onVersionChange) {
                              onVersionChange(modelWithVersion);
                            } else {
                              onChange(modelWithVersion);
                            }
                            setShowVersionDropdown(false);

                            // Trigger word suggestions
                            if (
                              version.trained_words &&
                              version.trained_words.length > 0
                            ) {
                              toast(
                                (t) => (
                                  <div className="flex flex-col gap-2">
                                    <span className="font-medium">
                                      Found trigger words!
                                    </span>
                                    <div className="flex gap-2">
                                      <button
                                        onClick={() => {
                                          window.dispatchEvent(
                                            new CustomEvent("addTriggerWords", {
                                              detail: version.trained_words,
                                            }),
                                          );
                                          toast.dismiss(t.id);
                                        }}
                                        className="bg-blue-600 text-white text-xs px-2 py-1 rounded"
                                      >
                                        Add to Prompt
                                      </button>
                                      <button
                                        onClick={() => toast.dismiss(t.id)}
                                        className="text-gray-400 text-xs"
                                      >
                                        Dismiss
                                      </button>
                                    </div>
                                  </div>
                                ),
                                { duration: 5000, icon: "💡" },
                              );
                            }
                          }}
                          className={`w-full px-3 py-2 text-left hover:bg-gray-700 flex items-center justify-between gap-2 ${isSelected ? "bg-gray-700/50" : ""}`}
                        >
                          <div className="flex-1 min-w-0">
                            <div className="text-sm text-white truncate flex items-center gap-2">
                              {version.name}
                              {version.is_default && (
                                <span className="text-xs bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">
                                  default
                                </span>
                              )}
                            </div>
                            <div className="text-xs text-gray-500 truncate">
                              {version.base_model || "Unknown"} •{" "}
                              {file.size_kb
                                ? `${(file.size_kb / 1024 / 1024).toFixed(2)} GB`
                                : ""}
                            </div>
                          </div>
                          <div className="flex items-center gap-1 flex-shrink-0">
                            {/* Set as Default Button */}
                            {!version.is_default && (
                              <button
                                onClick={async (e) => {
                                  e.stopPropagation();
                                  const baseModel =
                                    selectedModel._originalModel ||
                                    selectedModel;
                                  try {
                                    await api.post(
                                      `/api/v2/models/${baseModel.model_id}/set-default-version/${version.id}`,
                                    );
                                    toast.success(
                                      `Set "${version.name}" as default`,
                                    );
                                    // Refresh models list
                                    if (directory) {
                                      const res = await filesApi.list({
                                        directory,
                                      });
                                      setModels(res.files || []);
                                      // Update versions in the selected model
                                      const updatedModel = (
                                        res.files || []
                                      ).find(
                                        (m) =>
                                          m.model_id === baseModel.model_id,
                                      );
                                      if (updatedModel && onChange) {
                                        onChange({
                                          ...updatedModel,
                                          _originalModel: updatedModel,
                                        });
                                      }
                                    }
                                    setShowVersionDropdown(false);
                                  } catch {
                                    toast.error(
                                      "Failed to set default version",
                                    );
                                  }
                                }}
                                className="p-1 hover:bg-gray-600 rounded text-gray-500 hover:text-yellow-400 transition-colors"
                                title="Set as default version"
                              >
                                <Star size={14} />
                              </button>
                            )}
                            {isSelected && (
                              <div className="text-blue-400">✓</div>
                            )}
                          </div>
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Info Button (inside the box) */}
          {onInfoClick && selectedModel?.civitai_id && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onInfoClick(selectedModel);
              }}
              className="p-2 rounded text-gray-400 hover:text-blue-300 hover:bg-gray-800 border border-transparent hover:border-gray-700 transition-colors"
              title="View Model Details"
              aria-label={`View details for ${selectedModel.name}`}
            >
              <Info size={18} />
            </button>
          )}
        </div>
      </div>

      {/* Modal/Dropdown */}
      {isOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/80 flex items-center justify-center p-4"
          role="dialog"
          aria-modal="true"
          aria-labelledby="model-selector-title"
          onClick={handleClose}
        >
          <div
            className="bg-gray-900 w-full max-w-4xl h-[80vh] rounded-2xl border border-gray-800 flex flex-col shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div className="p-4 border-b border-gray-800 space-y-3">
              <div className="flex justify-between items-center gap-4">
                <h3
                  id="model-selector-title"
                  className="text-lg font-bold text-white"
                >
                  Select {label}
                </h3>
                <button
                  onClick={handleClose}
                  className="p-2 hover:bg-gray-800 rounded-full text-gray-400 hover:text-white"
                  aria-label="Close modal"
                >
                  ✕
                </button>
              </div>

              {/* Search Bar */}
              <div className="relative">
                <Search
                  className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500"
                  size={18}
                />
                <input
                  type="text"
                  placeholder="Search models by name, tags, description..."
                  aria-label="Search models"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="w-full bg-gray-800 border border-gray-700 rounded-full pl-10 pr-4 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
                  autoFocus
                />
              </div>

              {/* Sort and Filter */}
              <div className="flex gap-2 flex-wrap">
                <select
                  value={sortBy}
                  onChange={(e) => setSortBy(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="name">Sort: Name</option>
                  <option value="date">Sort: Date</option>
                  <option value="size">Sort: Size</option>
                  <option value="rating">Sort: Rating</option>
                </select>

                <select
                  value={filterBaseModel}
                  onChange={(e) => setFilterBaseModel(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="all">All Base Models</option>
                  <option value="SD 1.5">SD 1.5</option>
                  <option value="SDXL 1.0">SDXL</option>
                  <option value="SD 3">SD 3</option>
                  <option value="Pony">Pony</option>
                </select>

                <select
                  value={filterType}
                  onChange={(e) => setFilterType(e.target.value)}
                  className="bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-blue-500"
                >
                  <option value="all">All Types</option>
                  <option value="Checkpoint">Checkpoint</option>
                  <option value="LORA">LoRA</option>
                  <option value="TextualInversion">Embedding</option>
                </select>

                <label className="flex items-center gap-2 bg-gray-800 border border-gray-700 rounded-lg px-3 py-1.5 text-xs text-white cursor-pointer hover:border-blue-500">
                  <input
                    type="checkbox"
                    checked={showNSFW}
                    onChange={(e) => setShowNSFW(e.target.checked)}
                    className="rounded w-3 h-3"
                  />
                  Show NSFW
                </label>

                {(filterBaseModel !== "all" ||
                  filterType !== "all" ||
                  !showNSFW) && (
                  <button
                    onClick={() => {
                      setFilterBaseModel("all");
                      setFilterType("all");
                      setShowNSFW(true);
                    }}
                    className="bg-red-900/30 border border-red-800 rounded-lg px-3 py-1.5 text-xs text-red-300 hover:bg-red-900/50"
                    aria-label="Clear all filters"
                  >
                    Clear Filters
                  </button>
                )}
              </div>
            </div>

            {/* Grid */}
            <div className="flex-1 overflow-y-auto p-4">
              {loading ? (
                <div className="flex justify-center py-20 text-gray-500">
                  <Loader2 className="animate-spin" />
                </div>
              ) : filteredAndSortedModels.length === 0 ? (
                <div className="text-center py-20 text-gray-500">
                  {models.length === 0
                    ? "No models found"
                    : "No models match your filters"}
                </div>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {filteredAndSortedModels.map((model) => {
                    const versions = model.versions || [];
                    const hasMultipleVersions = versions.length > 1;
                    const isExpanded = expandedModel === model.model_id;

                    return (
                      <div
                        key={model.model_id || model.name}
                        className="relative"
                      >
                        {/* Main Model Card */}
                        <button
                          onClick={() => {
                            if (hasMultipleVersions && !isExpanded) {
                              // First click on multi-version: expand to show versions
                              setExpandedModel(model.model_id);
                              return;
                            }
                            // Single version or already expanded: select this model
                            onChange(model);
                            handleClose();

                            // Check for suggestions
                            if (
                              model.trained_words &&
                              model.trained_words.length > 0
                            ) {
                              toast(
                                (t) => (
                                  <div className="flex flex-col gap-2">
                                    <span className="font-medium">
                                      Found trigger words!
                                    </span>
                                    <div className="flex gap-2">
                                      <button
                                        onClick={() => {
                                          window.dispatchEvent(
                                            new CustomEvent("addTriggerWords", {
                                              detail: model.trained_words,
                                            }),
                                          );
                                          toast.dismiss(t.id);
                                        }}
                                        className="bg-blue-600 text-white text-xs px-2 py-1 rounded"
                                      >
                                        Add to Prompt
                                      </button>
                                      <button
                                        onClick={() => toast.dismiss(t.id)}
                                        className="text-gray-400 text-xs"
                                      >
                                        Dismiss
                                      </button>
                                    </div>
                                  </div>
                                ),
                                { duration: 5000, icon: "💡" },
                              );
                            }

                            if (
                              model.base_model?.includes("SDXL") ||
                              model.base_model?.includes("Illustrious")
                            ) {
                              toast(
                                (t) => (
                                  <div className="flex flex-col gap-2">
                                    <span className="font-medium">
                                      SDXL-Based Model Detected
                                    </span>
                                    <div className="flex gap-2">
                                      <button
                                        onClick={() => {
                                          window.dispatchEvent(
                                            new CustomEvent(
                                              "applySDXLSettings",
                                            ),
                                          );
                                          toast.dismiss(t.id);
                                        }}
                                        className="bg-purple-600 text-white text-xs px-2 py-1 rounded"
                                      >
                                        Apply SDXL Settings
                                      </button>
                                      <button
                                        onClick={() => toast.dismiss(t.id)}
                                        className="text-gray-400 text-xs"
                                      >
                                        Dismiss
                                      </button>
                                    </div>
                                  </div>
                                ),
                                { duration: 5000, icon: "⚙️" },
                              );
                            }
                          }}
                          className={`w-full group relative aspect-[2/3] rounded-xl overflow-hidden border text-left transition-all ${
                            value === model.name
                              ? "border-blue-500 ring-2 ring-blue-500/50"
                              : "border-gray-800 hover:border-gray-600"
                          }`}
                        >
                          {/* Image */}
                          {(() => {
                            if (model.civitai_id) {
                              return (
                                <img
                                  src={`/api/v2/models/preview/${model.civitai_id}`}
                                  alt={model.display_name || model.name}
                                  className="absolute inset-0 w-full h-full object-cover transition-transform group-hover:scale-105"
                                  loading="lazy"
                                  onError={(e) => {
                                    e.target.style.display = "none";
                                  }}
                                />
                              );
                            }
                            if (model.preview) {
                              return (
                                <img
                                  src={model.preview}
                                  alt={model.display_name || model.name}
                                  className="absolute inset-0 w-full h-full object-cover transition-transform group-hover:scale-105"
                                  loading="lazy"
                                  onError={(e) => {
                                    e.target.style.display = "none";
                                  }}
                                />
                              );
                            }
                            return (
                              <div className="absolute inset-0 bg-gray-800 flex flex-col items-center justify-center text-gray-600 p-4">
                                <ImageIcon
                                  size={32}
                                  className="mb-2 opacity-50"
                                />
                                <span className="text-xs text-center break-all opacity-50">
                                  {model.display_name || model.name}
                                </span>
                              </div>
                            );
                          })()}

                          {/* Overlay */}
                          <div className="absolute inset-0 bg-gradient-to-t from-black/90 via-black/20 to-transparent p-4 flex flex-col justify-end">
                            <div className="font-medium text-white text-sm line-clamp-2 leading-tight">
                              {model.display_name || model.name}
                            </div>
                            <div className="flex items-center gap-2 mt-1">
                              {model.size && (
                                <span className="text-xs text-gray-400">
                                  {(model.size / 1024 / 1024 / 1024).toFixed(2)}{" "}
                                  GB
                                </span>
                              )}
                              {model.default_version && (
                                <span className="text-xs text-gray-500">
                                  {model.default_version}
                                </span>
                              )}
                            </div>
                          </div>

                          {/* Version Badge (top-left) */}
                          {hasMultipleVersions && (
                            <div
                              className={`absolute top-2 left-2 flex items-center gap-1 px-2 py-1 rounded-full text-xs font-medium shadow-lg transition-colors ${
                                isExpanded
                                  ? "bg-blue-500 text-white"
                                  : "bg-gray-900/80 text-gray-300 hover:bg-gray-800"
                              }`}
                            >
                              <Layers size={12} />
                              {versions.length}
                              <ChevronDown
                                size={12}
                                className={`transition-transform ${isExpanded ? "rotate-180" : ""}`}
                              />
                            </div>
                          )}

                          {/* Selected Check */}
                          {value === model.name && (
                            <div className="absolute top-2 right-2 bg-blue-500 text-white p-1 rounded-full shadow-lg">
                              <Check size={14} />
                            </div>
                          )}
                        </button>

                        {/* Version Dropdown (expanded) */}
                        {isExpanded && hasMultipleVersions && (
                          <div className="absolute z-10 left-0 right-0 top-full mt-1 bg-gray-800 border border-gray-700 rounded-lg shadow-xl overflow-hidden">
                            <div className="p-2 border-b border-gray-700 flex justify-between items-center">
                              <span className="text-xs text-gray-400">
                                Select Version
                              </span>
                              <button
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setExpandedModel(null);
                                }}
                                className="text-gray-500 hover:text-white text-xs"
                              >
                                ✕
                              </button>
                            </div>
                            <div className="max-h-48 overflow-y-auto">
                              {versions.map((version) => {
                                const file = version.file || {};
                                const isDefault = version.is_default;
                                return (
                                  <button
                                    key={version.id}
                                    onClick={(e) => {
                                      e.stopPropagation();
                                      const modelWithVersion =
                                        getModelWithVersion(model, version);
                                      onChange(modelWithVersion);
                                      setExpandedModel(null);
                                      handleClose();

                                      // Trigger word suggestions
                                      if (
                                        version.trained_words &&
                                        version.trained_words.length > 0
                                      ) {
                                        toast(
                                          (t) => (
                                            <div className="flex flex-col gap-2">
                                              <span className="font-medium">
                                                Found trigger words!
                                              </span>
                                              <div className="flex gap-2">
                                                <button
                                                  onClick={() => {
                                                    window.dispatchEvent(
                                                      new CustomEvent(
                                                        "addTriggerWords",
                                                        {
                                                          detail:
                                                            version.trained_words,
                                                        },
                                                      ),
                                                    );
                                                    toast.dismiss(t.id);
                                                  }}
                                                  className="bg-blue-600 text-white text-xs px-2 py-1 rounded"
                                                >
                                                  Add to Prompt
                                                </button>
                                                <button
                                                  onClick={() =>
                                                    toast.dismiss(t.id)
                                                  }
                                                  className="text-gray-400 text-xs"
                                                >
                                                  Dismiss
                                                </button>
                                              </div>
                                            </div>
                                          ),
                                          { duration: 5000, icon: "💡" },
                                        );
                                      }
                                    }}
                                    className="w-full px-3 py-2 text-left hover:bg-gray-700 flex items-center justify-between gap-2"
                                  >
                                    <div className="flex-1 min-w-0">
                                      <div className="text-sm text-white truncate flex items-center gap-2">
                                        {version.name}
                                        {isDefault && (
                                          <span className="text-xs bg-blue-500/20 text-blue-400 px-1.5 py-0.5 rounded">
                                            default
                                          </span>
                                        )}
                                      </div>
                                      <div className="text-xs text-gray-500 truncate">
                                        {version.base_model || "Unknown"} •{" "}
                                        {file.size_kb
                                          ? `${(file.size_kb / 1024 / 1024).toFixed(2)} GB`
                                          : ""}
                                      </div>
                                    </div>
                                    {value === file.filename && (
                                      <Check
                                        size={14}
                                        className="text-blue-400 flex-shrink-0"
                                      />
                                    )}
                                  </button>
                                );
                              })}
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}

              {/* Infinite Scroll Sentinel */}
              <div ref={sentinelRef} className="h-4" />

              {/* Loading More Indicator */}
              {loadingMore && (
                <div className="flex justify-center py-4">
                  <Loader2 className="animate-spin text-gray-400" size={24} />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
});

export default ModelSelector;
