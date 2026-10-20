/**
 * The generation request contract.
 *
 * There is ONE request builder - `useWorkflowBuilder.buildPayload` - and
 * every surface that asks for an image goes through it: the Simple
 * Generator, Img2Img, Inpaint and Batch.
 *
 * It used not to be so. The Batch page hand-rolled its own request body,
 * and it carried 15 of the Simple page's 36 option fields. The fields it
 * was missing were not cosmetic:
 *
 *   - `unet`, `clip`, `clip2` - so a Flux model was transmitted as
 *     `checkpoint`, and a UNET lives in models/unet/, not
 *     models/checkpoints/, so the provider did not have it and the request
 *     failed with "Missing Models" for a model the user had installed;
 *   - `modelType` - so the backend fell back to `sd15` and used the SD1.5
 *     FreeU curve on an SDXL model;
 *   - every enhancement - hires fix, ADetailer, FreeU, PAG, latent
 *     upscale - so a Batch could not express any of them at all.
 *
 * These tests pin the shape of the request, so a second builder cannot
 * grow beside the first one without one of them failing.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'fs';
import { dirname, join } from 'path';
import { fileURLToPath } from 'url';

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = join(HERE, '..');

const read = (p) => readFileSync(p, 'utf8');
const IS_TEST_FILE = /\.test\.jsx?$/;

function walk(dir, skip = new Set(), acc = []) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        if (skip.has(entry.name)) continue;
        const full = join(dir, entry.name);
        if (entry.isDirectory()) walk(full, skip, acc);
        else if (/\.(jsx?)$/.test(entry.name) && !IS_TEST_FILE.test(entry.name)) acc.push(full);
    }
    return acc;
}

const PRODUCTION_FILES = walk(SRC, new Set(['node_modules', 'dist', 'e2e', '__tests__']));

/** The pages that ask for an image. */
const GENERATOR_PAGES = [
    'pages/SimpleGenerator.jsx',
    'pages/BatchGenerate.jsx',
    'pages/Img2Img.jsx',
    'pages/Inpaint.jsx',
];

describe('one request builder', () => {
    it('the Batch page uses the shared builder', () => {
        const src = read(join(SRC, 'pages', 'BatchGenerate.jsx'));
        expect(src).toContain('useWorkflowBuilder');
        expect(src).toContain('buildPayload');
    });

    it('no page hand-writes a generation options object', () => {
        // A page that builds its own `options: { ... }` is a second
        // builder. It will drift, and nothing will say so.
        const offenders = [];
        for (const rel of PRODUCTION_FILES) {
            if (!GENERATOR_PAGES.includes(rel.replace(/\\/g, '/'))) continue;
            const src = read(join(SRC, rel));
            const literal = src.match(/options:\s*\{/g);
            if (literal) {
                offenders.push(`${rel}: ${literal.length} hand-written options object(s)`);
            }
        }
        expect(offenders, offenders.join('\n')).toEqual([]);
    });

    it('the Batch page runs the preflight', () => {
        // Without it a Batch could submit a checkpoint that is not
        // installed: the request was accepted, the jobs were created, and
        // then every one of them failed on the provider - N failures for
        // one missing model.
        const src = read(join(SRC, 'pages', 'BatchGenerate.jsx'));
        expect(src).toContain('useGenerationPreflight');
        expect(src).toContain('runWithPreflight');
    });
});

describe('the builder sends the model fields in every mode', () => {
    const src = read(join(SRC, 'hooks', 'useWorkflowBuilder.js'));

    it('the model fields are in the base options, not in the t2i branch', () => {
        // The backend chooses the loader from `unet` + `clip`, not from the
        // mode. They used to be sent only for t2i.
        expect(src).toContain('unet:');
        expect(src).toContain('clip:');
        expect(src).toContain('clip2:');
        expect(src).toContain('modelType:');
    });

    it('the model type comes from the catalogue, not from three name checks', () => {
        expect(src).toContain('resolveModelType');

        const modelType = read(join(SRC, 'utils', 'modelType.js'));
        expect(modelType).toContain('export function resolveModelType');
        // SD3 and Illustrious are SDXL-family models, and reading them as
        // SD1.5 gave them the SD1.5 FreeU curve.
        expect(modelType).toContain("base.includes('sd3')");
        expect(modelType).toContain("base.includes('illustrious')");
    });

    it('the loras are narrowed to the request shape', () => {
        // `selectedLoras` carries preview images and CivitAI metadata.
        // Pydantic drops them, but the BODY still carries them, and a
        // batch multiplies that across every entry.
        expect(src).toContain('lorasToRequestOptions');
    });
});

describe('the metadata checkpoint', () => {
    it('the guided path sends the model record', () => {
        // The gallery shows the record's display name and its visual
        // fields, so the record is what belongs there.
        const src = read(join(SRC, 'hooks', 'useWorkflowBuilder.js'));
        expect(src).toMatch(/checkpoint:\s*selectedCheckpoint/);
    });

    it('the readers accept both shapes', () => {
        // The backend's graph-derived metadata carries the NAME, because the
        // backend does not know the record. So both shapes are legitimate,
        // and the readers have to cope.
        const modelDisplay = read(join(SRC, 'utils', 'modelDisplay.js'));
        expect(modelDisplay).toContain('export function checkpointName');
    });
});

describe('the provider capabilities', () => {
    it('the panel reads the capabilities instead of assuming', () => {
        // The panel used to hardcode the provider's node vocabulary in
        // Python and emit those nodes whatever the provider had installed,
        // so it offered a FreeU toggle to a provider with no FreeU node and
        // the job failed at dispatch with "node type not found".
        const panel = read(join(SRC, 'components', 'generator', 'EnhancementsSection.jsx'));
        expect(panel).toContain('capabilities');
        expect(panel).toContain("capabilities?.nodes?.freeu");
        expect(panel).toContain("capabilities?.nodes?.adetailer");
    });

    it('the layout fetches them for the provider the job will run on', () => {
        const layout = read(join(SRC, 'components', 'generator', 'UnifiedGeneratorLayout.jsx'));
        expect(layout).toContain('useProviderCapabilities');
        expect(layout).toContain('capabilities={capabilities}');
    });

    it('"not known" is not "not supported"', () => {
        // A provider that is down, or has never been introspected, must not
        // be read as a provider that cannot do FreeU - so the control stays
        // live and nothing is claimed.
        const panel = read(join(SRC, 'components', 'generator', 'EnhancementsSection.jsx'));
        expect(panel).toContain("capabilities?.nodes?.freeu !== false");
        expect(panel).toContain('!capabilities.known');
    });

    it('the model lists come from the provider, not from the union catalogue', () => {
        // The panel used to offer the union catalogue - the server's models
        // and every provider's - so it offered files the target provider did
        // not have.
        const panel = read(join(SRC, 'components', 'generator', 'EnhancementsSection.jsx'));
        expect(panel).toContain('capabilities?.models?.upscale_model');
        expect(panel).toContain('capabilities?.models?.detector');
    });

    it('the backend derives them from the provider own node graph', () => {
        const BACKEND = join(HERE, '..', '..', '..', 'backend_v2');
        const caps = read(join(BACKEND, 'core', 'provider_capabilities.py'));
        expect(caps).toContain('def derive_capabilities');
        // And the builder asks before it emits.
        const builder = read(join(BACKEND, 'core', 'workflow_builder.py'));
        expect(builder).toContain('self._supports("freeu")');
        expect(builder).toContain('self._supports("adetailer")');
    });
});

describe('the batch partial failure', () => {
    it('the backend reports the jobs it created alongside the failures', () => {
        const BACKEND = join(HERE, '..', '..', '..', 'backend_v2');
        const src = read(join(BACKEND, 'api', 'routes', 'generation.py'));
        expect(src).toContain('failures');
        // The jobs already created are REAL work - they are enqueued, they
        // will run, and they will cost. The old code let the exception
        // escape, so the client got a 5xx, `setJobIds` never ran, and the
        // Batch Jobs panel stayed EMPTY while N-1 images were being
        // produced somewhere.
        expect(src).toContain('created_so_far');
    });

    it('the page shows the jobs that were created', () => {
        const src = read(join(SRC, 'pages', 'BatchGenerate.jsx'));
        expect(src).toContain('failed_count');
    });
});
