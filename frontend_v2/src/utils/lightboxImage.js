import { assetPath } from './assetUrl';

/**
 * Shape a session's asset into an image the lightbox can actually work with.
 *
 * A session is a way of grouping *images*, but the list endpoint does not return
 * images — it returns `session_assets` rows, and those are FLAT: `prompt`,
 * `negative_prompt`, `cfg`, `seed`, `steps`, `sampler`, `scheduler`,
 * `checkpoint` and `loras` are top-level fields, not a `metadata` object. The
 * lightbox reads `selectedImage.metadata`, so handed one of these raw it showed
 * "No metadata available" for an image whose prompt and seed were sitting right
 * there in the payload.
 *
 * The sidecar is no help either: `assetMetadataUrl` fetches
 * `<image path>.json` from the output directory, and for a library that was
 * written by a worker rather than by ComfyUI's own save step, that file simply
 * does not exist — 404. So the information has to come from the row we already
 * have.
 *
 * `metadata_` is `metadata_` in Python and `metadata` on the wire; this is the
 * wire shape, which is what the client sees everywhere else.
 */
export function toLightboxImage(asset) {
    if (!asset) return null;

    const {
        prompt,
        negative_prompt: negativePrompt,
        cfg,
        seed,
        steps,
        sampler,
        scheduler,
        vae,
        checkpoint,
        loras,
        width,
        height,
        // An already-shaped image carries its metadata HERE rather than in the
        // flattened fields, and it must win: a gallery image has real baked
        // metadata and almost none of the flat keys, so rebuilding from them
        // would replace a prompt and a seed with empty strings.
        metadata: existing,
        ...rest
    } = asset;

    // Defined-ness, not truthiness: a seed of 0 and a cfg of 0 are real values,
    // and `?:` would silently drop both.
    const pick = (flat, baked, ...keys) => {
        for (const key of keys) {
            if (flat !== undefined && flat !== null) return flat;
            const value = baked?.[key];
            if (value !== undefined && value !== null) return value;
        }
        return null;
    };

    const baked = existing && typeof existing === 'object' ? existing : {};

    return {
        ...rest,
        name: assetPath(asset),
        type: 'image',
        width: width ?? rest.width ?? null,
        height: height ?? rest.height ?? null,
        // The key names here are the ones `ImageLightbox` actually reads —
        // `metadata.sampler`, `metadata.checkpoint`, `metadata.negative` — and
        // they are NOT the `_name` variants the gallery carries, nor is the
        // negative prompt `negative_prompt`. Setting the tidier names produced
        // "SAMPLER" and "MODEL Unknown" on a modal whose whole job is to show
        // what an image was generated from, with every value sitting right there
        // in the payload. `_name` aliases are written too, because other parts
        // of the app read those.
        metadata: {
            ...baked,
            prompt: pick(prompt, baked, 'prompt') ?? '',
            negative: pick(negativePrompt, baked, 'negative', 'negative_prompt', 'negativePrompt') ?? '',
            negative_prompt: pick(negativePrompt, baked, 'negative_prompt', 'negativePrompt') ?? '',
            cfg: pick(cfg, baked, 'cfg'),
            seed: pick(seed, baked, 'seed'),
            steps: pick(steps, baked, 'steps'),
            sampler: pick(sampler, baked, 'sampler', 'sampler_name'),
            sampler_name: pick(sampler, baked, 'sampler_name', 'sampler'),
            scheduler: pick(scheduler, baked, 'scheduler'),
            vae: pick(vae, baked, 'vae'),
            // The lightbox handles a string or an object here, so the session
            // row's plain filename displays correctly without inventing the
            // gallery's `{name, ...}` object.
            checkpoint: pick(checkpoint, baked, 'checkpoint', 'checkpoint_name'),
            checkpoint_name: pick(checkpoint, baked, 'checkpoint_name', 'checkpoint'),
            loras: Array.isArray(loras) ? loras : (baked.loras ?? []),
        },
    };
}
