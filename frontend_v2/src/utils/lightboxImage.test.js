import { describe, expect, it } from 'vitest';

import { toLightboxImage } from './lightboxImage';

/**
 * A session's images have to behave like gallery images once they are open.
 *
 * The list endpoint returns `session_assets` rows, which are FLAT — `prompt`,
 * `seed`, `cfg` are top-level fields — while the lightbox reads
 * `selectedImage.metadata`. Handed a raw row it said "No metadata available"
 * for an image whose prompt and seed were in the payload, and then fell back to
 * fetching `<image>.json` from the output directory, which 404s because metadata
 * is baked into the image and nobody writes sidecars any more.
 */
const ROW = {
    id: 'a1',
    relative_path: 'default_user/main/2026/08/09/x.png',
    prompt: 'a lighthouse at dusk',
    negative_prompt: 'blurry',
    cfg: 6.5,
    seed: 8784929870804149,
    steps: 30,
    sampler: 'euler',
    scheduler: 'normal',
    checkpoint: 'nova.safetensors',
    loras: [{ name: 'Detail Slider' }],
    width: 1024,
    height: 1536,
};

describe('toLightboxImage', () => {
    it('folds the flat row into the metadata object the lightbox reads', () => {
        const image = toLightboxImage(ROW);
        expect(image.metadata.prompt).toBe('a lighthouse at dusk');
        expect(image.metadata.negative_prompt).toBe('blurry');
        expect(image.metadata.cfg).toBe(6.5);
        expect(image.metadata.seed).toBe(8784929870804149);
        expect(image.metadata.steps).toBe(30);
        // The names `ImageLightbox` reads, not the tidier aliases.
        expect(image.metadata.sampler).toBe('euler');
        expect(image.metadata.checkpoint).toBe('nova.safetensors');
        expect(image.metadata.negative).toBe('blurry');
        expect(image.metadata.loras).toEqual([{ name: 'Detail Slider' }]);
    });

    it('gives it a name so the lightbox can match it against a navigation list', () => {
        // `assetPath` falls back to `name`, and the lightbox identifies images by
        // it. Without a name the image is unlistable, which is what left the
        // counter reading "1 / 1+" with no way to move.
        expect(toLightboxImage(ROW).name).toBe(ROW.relative_path);
    });

    it('marks it as an image so the gallery flattener accepts it', () => {
        expect(toLightboxImage(ROW).type).toBe('image');
    });

    it('survives a sparse row without inventing values', () => {
        const image = toLightboxImage({ id: 'a2', relative_path: 'b.png' });
        expect(image.metadata.prompt).toBe('');
        expect(image.metadata.cfg).toBeNull();
        expect(image.metadata.loras).toEqual([]);
        expect(image.name).toBe('b.png');
    });

    it('leaves a gallery-shaped image — metadata only, no flat fields — intact', () => {
        // The two shapes that actually occur, and they are mutually exclusive: a
        // session row is flat, a gallery item nests. The regression this guards
        // is a shaper that rebuilds `metadata` from the flat keys, which for a
        // gallery image means replacing a real prompt and seed with empty
        // strings — so this case is the one that would hurt.
        const galleryItem = {
            id: 'g1',
            relative_path: 'default_user/main/2026/09/27/y.png',
            type: 'image',
            width: 832,
            height: 1216,
            metadata: {
                prompt: 'a lighthouse at dusk',
                negative_prompt: 'blurry',
                cfg: 6,
                seed: 8784929870804149,
                steps: 30,
                sampler_name: 'euler',
                loras: [{ name: 'Detail Slider' }],
                job_id: '7b7bc489',
            },
        };

        const image = toLightboxImage(galleryItem);
        expect(image.metadata.prompt).toBe('a lighthouse at dusk');
        expect(image.metadata.seed).toBe(8784929870804149);
        expect(image.metadata.job_id).toBe('7b7bc489');
        expect(image.metadata.loras).toEqual([{ name: 'Detail Slider' }]);
        expect(image.width).toBe(832);
        expect(image.name).toBe(galleryItem.relative_path);
    });

    it('keeps a zero seed and a zero cfg, which are real values', () => {
        // Truthiness would drop both, leaving a memory with a null seed and a
        // null cfg — the exact "why does this look different every time" bug.
        const image = toLightboxImage({ relative_path: 'z.png', seed: 0, cfg: 0 });
        expect(image.metadata.seed).toBe(0);
        expect(image.metadata.cfg).toBe(0);
    });

    it('returns null for nothing, so callers can filter without a guard', () => {
        expect(toLightboxImage(null)).toBeNull();
        expect(toLightboxImage(undefined)).toBeNull();
    });
});
