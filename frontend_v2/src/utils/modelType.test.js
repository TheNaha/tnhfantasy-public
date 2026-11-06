import { describe, it, expect } from 'vitest';
import {
    isPonyModel,
    isFluxModel,
    isAuraFlowModel,
    getModelFamily,
    areModelsCompatible,
    resolveModelType,
} from './modelType';

describe('modelType utility tests', () => {
    describe('isPonyModel', () => {
        it('matches standard Pony, Pony V6, and Pony V7', () => {
            expect(isPonyModel({ base_model: 'Pony' })).toBe(true);
            expect(isPonyModel({ base_model: 'Pony Diffusion V6' })).toBe(true);
            expect(isPonyModel({ base_model: 'Pony V7' })).toBe(true);
            expect(isPonyModel({ base_model: 'Pony XL' })).toBe(true);
            expect(isPonyModel({ baseModel: 'PONY V6' })).toBe(true);
            expect(isPonyModel({ base_model: 'SDXL 1.0' })).toBe(false);
            expect(isPonyModel({ base_model: 'Flux.1 D' })).toBe(false);
        });
    });

    describe('isFluxModel', () => {
        it('matches Flux variants', () => {
            expect(isFluxModel({ base_model: 'Flux' })).toBe(true);
            expect(isFluxModel({ base_model: 'Flux.1 D' })).toBe(true);
            expect(isFluxModel({ base_model: 'Flux.1 Schnell' })).toBe(true);
            expect(isFluxModel({ base_model: 'SDXL' })).toBe(false);
        });
    });

    describe('isAuraFlowModel', () => {
        it('matches AuraFlow variants', () => {
            expect(isAuraFlowModel({ base_model: 'AuraFlow' })).toBe(true);
            expect(isAuraFlowModel({ base_model: 'SDXL' })).toBe(false);
        });
    });

    describe('resolveModelType', () => {
        it('resolves backend model types correctly', () => {
            expect(resolveModelType({ base_model: 'Flux.1 D' })).toBe('flux');
            expect(resolveModelType({ base_model: 'SDXL 1.0' })).toBe('sdxl');
            expect(resolveModelType({ base_model: 'Pony V6' })).toBe('sdxl');
            expect(resolveModelType({ base_model: 'Illustrious' })).toBe('sdxl');
            expect(resolveModelType({ base_model: 'SD 1.5' })).toBe('sd15');
        });
    });

    describe('getModelFamily', () => {
        it('categorizes models into expected families', () => {
            expect(getModelFamily('SDXL 1.0')).toBe('sdxl');
            expect(getModelFamily('SDXL Turbo')).toBe('sdxl');
            expect(getModelFamily('Pony V6')).toBe('pony');
            expect(getModelFamily('Pony V7')).toBe('pony');
            expect(getModelFamily('Illustrious')).toBe('illustrious');
            expect(getModelFamily('Illustrious XL')).toBe('illustrious');
            expect(getModelFamily('NoobAI-XL')).toBe('illustrious');
            expect(getModelFamily('Flux.1 Dev')).toBe('flux');
            expect(getModelFamily('SD 1.5')).toBe('sd15');
            expect(getModelFamily('SD 3.5 Large')).toBe('sd3');
            expect(getModelFamily('AuraFlow')).toBe('auraflow');
        });
    });

    describe('areModelsCompatible', () => {
        it('identifies SDXL family cross-compatibility', () => {
            const ckptIllus = { base_model: 'Illustrious' };
            const loraPony = { base_model: 'Pony V6' };
            const loraSdxl = { base_model: 'SDXL 1.0' };
            const loraNoob = { base_model: 'NoobAI' };
            const loraFlux = { base_model: 'Flux.1 D' };
            const loraSd15 = { base_model: 'SD 1.5' };

            // SDXL-architecture finetunes share tensor layouts and are cross-compatible
            expect(areModelsCompatible(ckptIllus, loraPony)).toBe(true);
            expect(areModelsCompatible(ckptIllus, loraSdxl)).toBe(true);
            expect(areModelsCompatible(ckptIllus, loraNoob)).toBe(true);
            expect(areModelsCompatible(ckptIllus, { base_model: 'Illustrious' })).toBe(true);

            // Incompatible across architectural boundaries
            expect(areModelsCompatible(ckptIllus, loraFlux)).toBe(false);
            expect(areModelsCompatible(ckptIllus, loraSd15)).toBe(false);
        });

        it('identifies Flux family compatibility', () => {
            const ckptFlux = { base_model: 'Flux' };
            const loraFluxDev = { base_model: 'Flux.1 Dev' };
            const loraSdxl = { base_model: 'SDXL' };

            expect(areModelsCompatible(ckptFlux, loraFluxDev)).toBe(true);
            expect(areModelsCompatible(ckptFlux, loraSdxl)).toBe(false);
        });
    });
});
