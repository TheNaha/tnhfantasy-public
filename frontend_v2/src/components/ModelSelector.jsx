import { useState, useEffect, memo, useRef, useMemo, useCallback } from "react";
import { Loader2 } from "lucide-react";
import { createPortal } from "react-dom";
import { useInfiniteScroll } from "../hooks/useInfiniteScroll";
import { filesApi } from "../api";
import TriggerBox from "./model-selector/TriggerBox";
import ModelFilterBar from "./model-selector/ModelFilterBar";
import ModelGridCard from "./model-selector/ModelGridCard";

const ModelSelector = memo(function ModelSelector({
  label,
  value,
  selectedModel: externalSelectedModel,
  preview,
  metadata,
  onChange,
  directory,
  initialModels = [],
  autoOpen = false,
  onAutoOpenComplete,
  onVersionChange,
  onInfoClick,
  onAddTriggerWords,
  onApplySDXLSettings,
  showAvailabilityBadge = false,
  providers = [],
  providersLoading = false,
}) {
  const [isOpen, setIsOpen] = useState(autoOpen);
  const [search, setSearch] = useState("");
  const [models, setModels] = useState(initialModels);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [internalSelectedModel, setInternalSelectedModel] = useState(null);
  const [hasMore, setHasMore] = useState(true);

  const offsetRef = useRef(0);
  const loadingRef = useRef(false);
  const loadingMoreRef = useRef(false);
  const abortControllerRef = useRef(null);
  const [expandedModel, setExpandedModel] = useState(null);

  const selectedModel = useMemo(() => {
    let sm = externalSelectedModel || internalSelectedModel;
    if (sm && (!sm.versions || sm.versions.length === 0)) {
       const matchingModel = models.find(m => m.name === sm.name || m.name === sm._originalModel?.name || m.display_name === sm.display_name);
       if (matchingModel) {
          sm = { 
            ...matchingModel, 
            ...sm, 
            versions: matchingModel.versions,
            civitai_id: sm.civitai_id || matchingModel.civitai_id,
            preview: sm.preview || matchingModel.preview,
            base_model: sm.base_model || matchingModel.base_model
          };
       }
    }
    return sm;
  }, [externalSelectedModel, internalSelectedModel, models]);

  const getModelWithVersion = useCallback((model, version) => {
    if (!version) return model;
    const file = version.file || {};
    const versionImages = version.images || [];
    const selectedVersionPreviewId = version.civitai_version_id || version.id;
    const directPreviewImage = versionImages[0]?.url || model.preview;
    const proxyPreviewImage = model.civitai_id
      ? (() => {
          const params = new URLSearchParams({ image_index: "0" });
          if (selectedVersionPreviewId) {
            params.set("version_id", String(selectedVersionPreviewId));
          }
          return `/api/v2/models/preview/${model.civitai_id}?${params.toString()}`;
        })()
      : null;
    const previewImage = directPreviewImage || proxyPreviewImage;

    return {
      ...model,
      name: file.filename || model.name,
      display_name: model.display_name,
      civitai_id: model.civitai_id,
      preview: previewImage,
      base_model: version.base_model || model.base_model,
      trained_words: version.trained_words || [],
      default_version: version.name,
      version_description: version.description || "",
      selectedVersionId: version.id,
      selectedVersionPreviewId,
      size: file.size_kb ? file.size_kb * 1024 : model.size,
      _originalModel: model,
    };
  }, []);

  useEffect(() => {
    if (autoOpen) setIsOpen(true);
  }, [autoOpen]);

  const handleClose = useCallback(() => {
    setIsOpen(false);
    if (onAutoOpenComplete) onAutoOpenComplete();
  }, [onAutoOpenComplete]);

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e) => { if (e.key === "Escape") handleClose(); };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, handleClose]);

  const [sortBy, setSortBy] = useState("name");
  const [filterBaseModel, setFilterBaseModel] = useState("all");
  const [filterType, setFilterType] = useState("all");
  const [showNSFW, setShowNSFW] = useState(true);

  useEffect(() => {
    if (initialModels?.length > 0) setModels(initialModels);
  }, [initialModels]);

  useEffect(() => {
    if (!externalSelectedModel && value) {
      const found = models.find((m) => m.name === value);
      if (found) {
        setInternalSelectedModel({ ...found, preview: found.preview || preview, metadata: found.metadata || metadata });
      } else {
        setInternalSelectedModel({ name: value, preview, metadata });
      }
    } else if (!externalSelectedModel && !value) {
      setInternalSelectedModel(null);
    }
  }, [value, models, preview, metadata, externalSelectedModel]);

  const fetchModels = useCallback(async (loadMore = false) => {
    if (!directory) return;
    if (!loadMore && abortControllerRef.current) abortControllerRef.current.abort();

    if (loadMore) {
      if (loadingMoreRef.current) return;
      loadingMoreRef.current = true;
      setLoadingMore(true);
    } else {
      loadingRef.current = true;
      setLoading(true);
    }

    const abortController = new AbortController();
    if (!loadMore) abortControllerRef.current = abortController;

    try {
      const currentOffset = loadMore ? offsetRef.current : 0;
      const sortMap = { name: "name_asc", date: "date_desc", size: "size_desc", rating: "rating_desc" };
      const params = new URLSearchParams({
        directory, limit: "50", offset: currentOffset.toString(), sort: sortMap[sortBy] || "name_asc",
      });
      if (search) params.append("search", search);

      const data = await filesApi.list(Object.fromEntries(params.entries()), { signal: abortController.signal });
      const newModels = data.files || [];

      if (loadMore) {
        setModels((prev) => [...prev, ...newModels]);
        offsetRef.current = currentOffset + 50;
      } else {
        setModels(newModels);
        offsetRef.current = 50;
      }
      setHasMore(newModels.length === 50);
    } catch (error) {
      if (error.name === 'AbortError') return;
      console.error("Failed to fetch models", error);
    } finally {
      if (loadMore) { loadingMoreRef.current = false; setLoadingMore(false); }
      else { loadingRef.current = false; setLoading(false); }
    }
  }, [directory, search, sortBy]);

  useEffect(() => {
    if (!isOpen) return;
    if (!directory && initialModels.length > 0) return;
    if (!directory) return;

    if (initialModels.length > 0 && search === "" && sortBy === "name") {
        offsetRef.current = initialModels.length;
        return;
    }

    offsetRef.current = 0;
    setHasMore(true);
    const timer = setTimeout(() => fetchModels(false), 300);
    return () => { clearTimeout(timer); if (abortControllerRef.current) abortControllerRef.current.abort(); };
  }, [isOpen, directory, initialModels.length, search, sortBy, fetchModels]);

  const filteredAndSortedModels = useMemo(() => {
    let result = [...models];
    if (filterBaseModel !== "all" || filterType !== "all" || !showNSFW) {
      result = result.filter((m) => {
        if (filterBaseModel !== "all" && m.base_model !== filterBaseModel) return false;
        if (filterType !== "all" && m.type !== filterType) return false;
        if (!showNSFW && m.nsfw) return false;
        return true;
      });
    }
    result.sort((a, b) => {
      switch (sortBy) {
        case "name": return (a.name || "").localeCompare(b.name || "");
        case "date": return (b.modified_time || 0) - (a.modified_time || 0);
        case "size": return (b.size || 0) - (a.size || 0);
        case "rating": return (b.stats?.thumbsUp || 0) - (a.stats?.thumbsUp || 0);
        default: return 0;
      }
    });
    return result;
  }, [models, sortBy, filterBaseModel, filterType, showNSFW]);

  const sentinelRef = useInfiniteScroll({
    hasMore: hasMore && !loading,
    onLoadMore: () => fetchModels(true),
    loading: loadingMore,
    rootMargin: "300px",
  });

  const handleVersionSelect = useCallback((model, version) => {
    const modelWithVersion = getModelWithVersion(model, version);
    if (onVersionChange) onVersionChange(modelWithVersion);
    else onChange(modelWithVersion);
  }, [getModelWithVersion, onVersionChange, onChange]);

  return (
    <div className="space-y-2">
      <label className="block text-xs font-medium text-gray-500">{label}</label>

      {/* Trigger Box */}
      <TriggerBox
        label={label}
        selectedModel={selectedModel}
        isOpen={isOpen}
        onOpen={() => setIsOpen(true)}
        onChange={onChange}
        onVersionChange={onVersionChange}
        getModelWithVersion={getModelWithVersion}
        onInfoClick={onInfoClick}
        onAddTriggerWords={onAddTriggerWords}
        directory={directory}
        setModels={setModels}
      />

      {/* Modal */}
      {isOpen && createPortal(
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
                <h3 id="model-selector-title" className="text-lg font-bold text-white">
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
              <ModelFilterBar
                search={search}
                onSearchChange={setSearch}
                sortBy={sortBy}
                onSortChange={setSortBy}
                filterBaseModel={filterBaseModel}
                onFilterBaseModelChange={setFilterBaseModel}
                filterType={filterType}
                onFilterTypeChange={setFilterType}
                showNSFW={showNSFW}
                onShowNSFWChange={setShowNSFW}
                hasActiveFilters={filterBaseModel !== "all" || filterType !== "all" || !showNSFW}
                onClearFilters={() => { setFilterBaseModel("all"); setFilterType("all"); setShowNSFW(true); }}
              />
            </div>

            {/* Grid */}
            <div className="flex-1 overflow-y-auto p-4">
              {loading ? (
                <div className="flex justify-center py-20 text-gray-500">
                  <Loader2 className="animate-spin" />
                </div>
              ) : filteredAndSortedModels.length === 0 ? (
                <div className="text-center py-20 text-gray-500">
                  {models.length === 0 ? "No models found" : "No models match your filters"}
                </div>
              ) : (
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
                  {filteredAndSortedModels.map((model) => (
                    <ModelGridCard
                      key={model.model_id || model.name}
                      model={model}
                      value={value}
                      isExpanded={expandedModel === model.model_id}
                      onExpand={setExpandedModel}
                      onSelect={(m) => { onChange(m); handleClose(); }}
                      onVersionSelect={handleVersionSelect}
                      onAddTriggerWords={onAddTriggerWords}
                      onApplySDXLSettings={onApplySDXLSettings}
                      showAvailabilityBadge={showAvailabilityBadge}
                      providers={providers}
                      providersLoading={providersLoading}
                    />
                  ))}
                </div>
              )}

              <div ref={sentinelRef} className="h-4" />

              {loadingMore && (
                <div className="flex justify-center py-4">
                  <Loader2 className="animate-spin text-gray-400" size={24} />
                </div>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </div>
  );
});

export default ModelSelector;
