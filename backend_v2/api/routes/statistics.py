# Statistics routes - Analytics and usage data
#
# Provides aggregated statistics computed from the output image gallery and
# job database.  Data is cached for 5 minutes (see `cache_stats` decorator)
# to avoid expensive file-system scans on every request.
#
# KEY ENDPOINTS:
#   GET /api/statistics          – Overall usage summary (job counts, generation stats)
#   GET /api/statistics/timeline – Daily generation counts for chart rendering
import asyncio
import re
from datetime import datetime
from typing import Any

from fastapi import APIRouter

from api.deps import cache_stats, get_logger
from config import settings
from services.gallery_indexer import gallery_indexer

logger = get_logger("statistics_route")

router = APIRouter(prefix="/api/statistics", tags=["statistics"])

# Output directory - will be configured via environment or settings
OUTPUT_DIR = settings.output_dir


def _calculate_statistics() -> dict[str, Any]:
    """
    Synchronous worker function to calculate basic statistics.
    Should be run in a thread pool to avoid blocking the event loop.
    """
    stats = {
        "total_images": 0,
        "models": {},
        "loras": {},
        "samplers": {},
        "schedulers": {},
        "avg_generation_time": 0,
        "total_generation_time": 0,
        "images_by_date": {},
        "popular_settings": {
            "steps": {},
            "cfg": {},
            "resolution": {}
        },
        "enriched_metadata_count": 0,
        "legacy_metadata_count": 0,
    }
    
    total_duration = 0
    duration_count = 0
    
    # Use GalleryIndexer for fast in-memory access
    try:
        all_files = gallery_indexer.get_all_files()
        
        for file_data in all_files:
            meta = file_data.get("metadata", {})
            if not meta:
                continue

            stats["total_images"] += 1

            # Track metadata version
            if meta.get("metadata_version") == "2.0":
                stats["enriched_metadata_count"] += 1
            else:
                stats["legacy_metadata_count"] += 1

            # Model usage - handle both string and dict formats
            checkpoint = meta.get("checkpoint")
            if checkpoint:
                if isinstance(checkpoint, dict):
                    model_name = checkpoint.get("name") or checkpoint.get("filename", "Unknown")
                else:
                    model_name = str(checkpoint)
                stats["models"][model_name] = stats["models"].get(model_name, 0) + 1

            # LoRA usage
            loras = meta.get("loras")
            if loras and isinstance(loras, list):
                for lora in loras:
                    if isinstance(lora, dict):
                        lora_name = lora.get("name") or lora.get("filename", "Unknown")
                    else:
                        lora_name = str(lora)
                    stats["loras"][lora_name] = stats["loras"].get(lora_name, 0) + 1

            # Sampler usage
            if "sampler" in meta:
                sampler = meta["sampler"]
                stats["samplers"][sampler] = stats["samplers"].get(sampler, 0) + 1

            # Scheduler usage
            if "scheduler" in meta:
                scheduler = meta["scheduler"]
                stats["schedulers"][scheduler] = stats["schedulers"].get(scheduler, 0) + 1

            # Generation time
            job = meta.get("job")
            if job and isinstance(job, dict):
                duration = job.get("duration_seconds")
                if duration is not None and duration > 0:
                    total_duration += duration
                    duration_count += 1

            # Settings popularity
            if "steps" in meta:
                steps = str(meta["steps"])
                stats["popular_settings"]["steps"][steps] = stats["popular_settings"]["steps"].get(steps, 0) + 1

            if "cfg" in meta:
                cfg = str(meta["cfg"])
                stats["popular_settings"]["cfg"][cfg] = stats["popular_settings"]["cfg"].get(cfg, 0) + 1

            if "width" in meta and "height" in meta:
                res = f"{meta['width']}x{meta['height']}"
                stats["popular_settings"]["resolution"][res] = stats["popular_settings"]["resolution"].get(res, 0) + 1

            # Images by date
            completed_at = None
            if job and isinstance(job, dict):
                completed_at = job.get("completed_at")
            
            if not completed_at:
                completed_at = file_data.get("modified_time", file_data.get("date", 0))

            if completed_at:
                try:
                    date = datetime.fromtimestamp(completed_at).strftime("%Y-%m-%d")
                    stats["images_by_date"][date] = stats["images_by_date"].get(date, 0) + 1
                except Exception as e:
                    logger.warning("statistics_date_parsing_failed", error=str(e))

    except Exception as e:
        logger.error("statistics_calculation_failed", error=str(e))
    
    # Calculate averages
    if duration_count > 0:
        stats["avg_generation_time"] = round(total_duration / duration_count, 2)
        stats["total_generation_time"] = round(total_duration, 2)
    
    # Sort dictionaries by count (descending)
    stats["models"] = dict(sorted(stats["models"].items(), key=lambda x: x[1], reverse=True))
    stats["loras"] = dict(sorted(stats["loras"].items(), key=lambda x: x[1], reverse=True))
    stats["samplers"] = dict(sorted(stats["samplers"].items(), key=lambda x: x[1], reverse=True))
    stats["schedulers"] = dict(sorted(stats["schedulers"].items(), key=lambda x: x[1], reverse=True))
    
    # Sort settings
    for key in stats["popular_settings"]:
        stats["popular_settings"][key] = dict(sorted(
            stats["popular_settings"][key].items(), 
            key=lambda x: x[1], 
            reverse=True
        ))
    
    # Sort dates
    stats["images_by_date"] = dict(sorted(stats["images_by_date"].items()))
    
    return stats


def _calculate_detailed_statistics(time_range: str = "all") -> dict[str, Any]:
    """
    Synchronous worker function to calculate detailed statistics.
    Should be run in a thread pool to avoid blocking the event loop.
    Supports filtering by time_range: "24h", "7d", "30d", "all"
    """
    # Initialize detailed stats structure
    detailed_stats = {
        # Timeline data
        "timeline": {
            "daily": {},      # date: count
            "hourly": {},     # hour (0-23): count
            "weekday": {},    # 0-6 (Mon-Sun): count
        },
        
        # Model usage with detailed stats
        "models": {
            "checkpoints": {},    # name: count
            "loras": {},          # name: count
            "lora_weights": [],   # [{name, avg_weight, count}]
            "vaes": {},           # name: count
            "samplers": {},       # name: count
            "schedulers": {}      # name: count
        },
        
        # Settings distributions
        "settings": {
            "steps": {},          # steps: count
            "cfg": {},            # cfg: count
            "resolutions": {},    # "widthxheight": count
            "seeds_random": 0,
            "seeds_fixed": 0
        },
        
        # Prompt analytics
        "prompts": {
            "keywords": {},       # word: frequency
            "lengths": [],        # list of prompt lengths
            "negative_usage": 0,
            "total": 0,
            "common_tags": {}     # common prompt tags
        },
        
        # Performance metrics
        "performance": {
            "by_model": {},       # model: {total_time, count, avg}
            "by_resolution": {},  # resolution: {total_time, count, avg}
            "by_steps": {},       # steps: {total_time, count, avg}
            "fastest": None,
            "slowest": None,
            "total_time": 0,
            "avg_time": 0
        },
        
        # Advanced analytics
        "model_sampler_matrix": {},   # {model: {sampler: count}}
        "correlations": {
            "steps_cfg": [],              # [{steps, cfg, count}]
            "model_resolution": []        # [{model, resolution, count}]
        },
        
        # Metadata
        "total_images": 0,
        "enriched_count": 0,
        "legacy_count": 0
    }
    
    # For tracking lora weights
    lora_data = {}  # {lora_name: [weights]}
    
    # Performance tracking
    all_durations = []
    
    # Common stop words for prompt analysis
    stop_words = {
        'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'can', 'her', 
        'was', 'one', 'our', 'out', 'day', 'get', 'has', 'him', 'his', 'how', 
        'man', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'boy', 'did', 
        'its', 'let', 'put', 'say', 'she', 'too', 'use', 'with', 'from', 'that',
        'this', 'will', 'have', 'been', 'more', 'when', 'into', 'some', 'than'
    }
    
    # Use GalleryIndexer for fast in-memory access
    try:
        all_files = gallery_indexer.get_all_files()
        
        now_ts = datetime.now().timestamp()
        cutoff_ts = 0
        if time_range == "24h":
            cutoff_ts = now_ts - (24 * 3600)
        elif time_range == "7d":
            cutoff_ts = now_ts - (7 * 24 * 3600)
        elif time_range == "30d":
            cutoff_ts = now_ts - (30 * 24 * 3600)

        for file_data in all_files:
            meta = file_data.get("metadata", {})
            if not meta:
                continue
            
            completed_at = None
            if "job" in meta and isinstance(meta["job"], dict):
                job_completed_at = meta["job"].get("completed_at")
                if isinstance(job_completed_at, str):
                    try:
                        # Parse ISO 8601 string to timestamp
                        # e.g., "2026-06-22T17:21:42.123Z"
                        job_completed_at = job_completed_at.replace("Z", "+00:00")
                        completed_at = datetime.fromisoformat(job_completed_at).timestamp()
                    except ValueError as e:
                        logger.warning("job_completed_at_parse_failed", error=str(e))
                elif isinstance(job_completed_at, (int, float)):
                    completed_at = float(job_completed_at)
            
            if not completed_at:
                completed_at = file_data.get("modified_time", file_data.get("date", 0))

            if cutoff_ts > 0 and (not completed_at or float(completed_at) < cutoff_ts):
                continue
        
            detailed_stats["total_images"] += 1

            # Track metadata version
            if meta.get("metadata_version") == "2.0":
                detailed_stats["enriched_count"] += 1
            else:
                detailed_stats["legacy_count"] += 1

            # === TIMELINE DATA ===
            if completed_at:
                try:
                    dt = datetime.fromtimestamp(completed_at)

                    # Daily
                    date_str = dt.strftime("%Y-%m-%d")
                    detailed_stats["timeline"]["daily"][date_str] = \
                        detailed_stats["timeline"]["daily"].get(date_str, 0) + 1

                    # Hourly
                    hour = str(dt.hour)
                    detailed_stats["timeline"]["hourly"][hour] = \
                        detailed_stats["timeline"]["hourly"].get(hour, 0) + 1

                    # Weekday (0=Monday, 6=Sunday)
                    weekday = str(dt.weekday())
                    detailed_stats["timeline"]["weekday"][weekday] = \
                        detailed_stats["timeline"]["weekday"].get(weekday, 0) + 1
                except Exception as e:
                    logger.warning("timeline_data_parse_failed", error=str(e))

            # === MODEL DATA ===
            # Checkpoints
            if "checkpoint" in meta and isinstance(meta["checkpoint"], dict):
                checkpoint_name = meta["checkpoint"].get("name", "Unknown")
                detailed_stats["models"]["checkpoints"][checkpoint_name] = \
                    detailed_stats["models"]["checkpoints"].get(checkpoint_name, 0) + 1

            # LoRAs with weights
            if "loras" in meta and isinstance(meta["loras"], list):
                for lora in meta["loras"]:
                    if isinstance(lora, dict):
                        lora_name = lora.get("name", "Unknown")
                        lora_weight = lora.get("weight", 1.0)

                        detailed_stats["models"]["loras"][lora_name] = \
                            detailed_stats["models"]["loras"].get(lora_name, 0) + 1

                        # Track weights for averaging
                        if lora_name not in lora_data:
                            lora_data[lora_name] = []
                        lora_data[lora_name].append(float(lora_weight))

            # VAE
            if "vae" in meta:
                vae_name = meta["vae"] if isinstance(meta["vae"], str) else \
                           meta["vae"].get("name", "Unknown") if isinstance(meta["vae"], dict) else "Unknown"
                detailed_stats["models"]["vaes"][vae_name] = \
                    detailed_stats["models"]["vaes"].get(vae_name, 0) + 1

            # Sampler
            if "sampler" in meta:
                sampler = meta["sampler"]
                detailed_stats["models"]["samplers"][sampler] = \
                    detailed_stats["models"]["samplers"].get(sampler, 0) + 1

            # Scheduler
            if "scheduler" in meta:
                scheduler = meta["scheduler"]
                detailed_stats["models"]["schedulers"][scheduler] = \
                    detailed_stats["models"]["schedulers"].get(scheduler, 0) + 1

            # === SETTINGS DATA ===
            if "steps" in meta:
                steps = str(meta["steps"])
                detailed_stats["settings"]["steps"][steps] = \
                    detailed_stats["settings"]["steps"].get(steps, 0) + 1

            if "cfg" in meta:
                cfg = str(float(meta["cfg"]))  # Normalize floats
                detailed_stats["settings"]["cfg"][cfg] = \
                    detailed_stats["settings"]["cfg"].get(cfg, 0) + 1

            if "width" in meta and "height" in meta:
                resolution = f"{meta['width']}x{meta['height']}"
                detailed_stats["settings"]["resolutions"][resolution] = \
                    detailed_stats["settings"]["resolutions"].get(resolution, 0) + 1

            # Seed tracking
            if "seed" in meta:
                seed = meta["seed"]
                if seed == -1 or seed is None:
                    detailed_stats["settings"]["seeds_random"] += 1
                else:
                    detailed_stats["settings"]["seeds_fixed"] += 1

            # === PROMPT ANALYTICS ===
            if "prompt" in meta:
                prompt = str(meta["prompt"])
                detailed_stats["prompts"]["total"] += 1
                detailed_stats["prompts"]["lengths"].append(len(prompt))
                
                # Extract keywords (simple word frequency)
                words = re.findall(r'\b[a-zA-Z]{3,}\b', prompt.lower())
                for word in words:
                    if word not in stop_words:
                        detailed_stats["prompts"]["keywords"][word] = \
                            detailed_stats["prompts"]["keywords"].get(word, 0) + 1

            if meta.get("negativePrompt"):
                detailed_stats["prompts"]["negative_usage"] += 1

            # === PERFORMANCE METRICS ===
            if "job" in meta and isinstance(meta["job"], dict):
                duration = meta["job"].get("duration_seconds")
                if duration and duration > 0:
                    all_durations.append(duration)
                    
                    # By model
                    if "checkpoint" in meta and isinstance(meta["checkpoint"], dict):
                        model_name = meta["checkpoint"].get("name")
                        if model_name:
                            if model_name not in detailed_stats["performance"]["by_model"]:
                                detailed_stats["performance"]["by_model"][model_name] = {
                                    "total_time": 0, "count": 0, "avg": 0
                                }
                            detailed_stats["performance"]["by_model"][model_name]["total_time"] += duration
                            detailed_stats["performance"]["by_model"][model_name]["count"] += 1
                    
                    # By resolution
                    if "width" in meta and "height" in meta:
                        res = f"{meta['width']}x{meta['height']}"
                        if res not in detailed_stats["performance"]["by_resolution"]:
                            detailed_stats["performance"]["by_resolution"][res] = {
                                "total_time": 0, "count": 0, "avg": 0
                            }
                        detailed_stats["performance"]["by_resolution"][res]["total_time"] += duration
                        detailed_stats["performance"]["by_resolution"][res]["count"] += 1
                    
                    # By steps
                    if "steps" in meta:
                        steps = str(meta["steps"])
                        if steps not in detailed_stats["performance"]["by_steps"]:
                            detailed_stats["performance"]["by_steps"][steps] = {
                                "total_time": 0, "count": 0, "avg": 0
                            }
                        detailed_stats["performance"]["by_steps"][steps]["total_time"] += duration
                        detailed_stats["performance"]["by_steps"][steps]["count"] += 1

            # === ADVANCED ANALYTICS ===
            # Model-Sampler matrix
            if "checkpoint" in meta and "sampler" in meta:
                if isinstance(meta["checkpoint"], dict):
                    model_name = meta["checkpoint"].get("name", "Unknown")
                    sampler = meta["sampler"]
                    
                    if model_name not in detailed_stats["model_sampler_matrix"]:
                        detailed_stats["model_sampler_matrix"][model_name] = {}
                    
                    detailed_stats["model_sampler_matrix"][model_name][sampler] = \
                        detailed_stats["model_sampler_matrix"][model_name].get(sampler, 0) + 1

            # Steps-CFG correlation
            if "steps" in meta and "cfg" in meta:
                found = False
                for item in detailed_stats["correlations"]["steps_cfg"]:
                    if item["steps"] == meta["steps"] and item["cfg"] == meta["cfg"]:
                        item["count"] += 1
                        found = True
                        break
                if not found:
                    detailed_stats["correlations"]["steps_cfg"].append({
                        "steps": meta["steps"],
                        "cfg": meta["cfg"],
                        "count": 1
                    })
                
    except Exception as e:
        logger.error("statistics_calculation_failed", error=str(e))
    
    # === POST-PROCESSING ===
    
    # Calculate LoRA weight averages
    for lora_name, weights in lora_data.items():
        avg_weight = sum(weights) / len(weights) if weights else 0
        detailed_stats["models"]["lora_weights"].append({
            "name": lora_name,
            "avg_weight": round(avg_weight, 2),
            "count": len(weights)
        })
    
    # Sort lora_weights by count
    detailed_stats["models"]["lora_weights"].sort(key=lambda x: x["count"], reverse=True)
    
    # Calculate performance averages
    for model_data in detailed_stats["performance"]["by_model"].values():
        if model_data["count"] > 0:
            model_data["avg"] = round(model_data["total_time"] / model_data["count"], 2)
    
    for res_data in detailed_stats["performance"]["by_resolution"].values():
        if res_data["count"] > 0:
            res_data["avg"] = round(res_data["total_time"] / res_data["count"], 2)
    
    for steps_data in detailed_stats["performance"]["by_steps"].values():
        if steps_data["count"] > 0:
            steps_data["avg"] = round(steps_data["total_time"] / steps_data["count"], 2)
    
    # Overall performance
    if all_durations:
        detailed_stats["performance"]["total_time"] = round(sum(all_durations), 2)
        detailed_stats["performance"]["avg_time"] = round(sum(all_durations) / len(all_durations), 2)
        detailed_stats["performance"]["fastest"] = round(min(all_durations), 2)
        detailed_stats["performance"]["slowest"] = round(max(all_durations), 2)
    
    # Sort top keywords (limit to top 100)
    sorted_keywords = sorted(
        detailed_stats["prompts"]["keywords"].items(),
        key=lambda x: x[1],
        reverse=True
    )[:100]
    detailed_stats["prompts"]["keywords"] = dict(sorted_keywords)
    
    # Calculate prompt length stats
    if detailed_stats["prompts"]["lengths"]:
        lengths = detailed_stats["prompts"]["lengths"]
        detailed_stats["prompts"]["avg_length"] = round(sum(lengths) / len(lengths), 1)
        detailed_stats["prompts"]["min_length"] = min(lengths)
        detailed_stats["prompts"]["max_length"] = max(lengths)
    else:
        detailed_stats["prompts"]["avg_length"] = 0
        detailed_stats["prompts"]["min_length"] = 0
        detailed_stats["prompts"]["max_length"] = 0
    
    # Sort correlations by count
    detailed_stats["correlations"]["steps_cfg"].sort(key=lambda x: x["count"], reverse=True)
    
    # Sort timeline data
    detailed_stats["timeline"]["daily"] = dict(sorted(detailed_stats["timeline"]["daily"].items()))
    
    return detailed_stats


from core.exceptions import ComfyError


@router.get("")
@cache_stats
async def get_statistics():
    """Generate comprehensive statistics from image metadata files."""
    if not gallery_indexer.is_ready:
        await asyncio.to_thread(gallery_indexer._ready_event.wait, 5.0)
    if not gallery_indexer.is_ready:
        raise ComfyError("Gallery indexer is still scanning files. Please wait.", code="SERVICE_UNAVAILABLE")
        
    return await asyncio.to_thread(_calculate_statistics)


@router.get("/detailed")
@cache_stats
async def get_detailed_statistics(timeRange: str = "all"):
    """
    Extended statistics with data optimized for charts and visualizations.
    Provides timeline data, distributions, and advanced analytics.
    """
    if not gallery_indexer.is_ready:
        await asyncio.to_thread(gallery_indexer._ready_event.wait, 5.0)
    if not gallery_indexer.is_ready:
        raise ComfyError("Gallery indexer is still scanning files. Please wait.", code="SERVICE_UNAVAILABLE")
        
    return await asyncio.to_thread(_calculate_detailed_statistics, timeRange)


@router.get("/summary")
async def get_stats_summary():
    """Quick summary statistics."""
    base_stats = await get_statistics()
    return {
        "total_images": base_stats.get("total_images", 0),
        "models_used": len(base_stats.get("models", {})),
        "loras_used": len(base_stats.get("loras", {})),
        "avg_generation_time": base_stats.get("avg_generation_time", 0),
        "top_model": list(base_stats.get("models", {}).keys())[0] if base_stats.get("models") else None,
        "top_sampler": list(base_stats.get("samplers", {}).keys())[0] if base_stats.get("samplers") else None,
    }
