import { describe, it, expect } from 'vitest';
import {
    CARD_ACCEPT,
    CARD_MAX_BYTES,
    DEFAULT_CARD_EXPORT_FORMAT,
    assertCharacterCardFile,
    buildCharacterCardExportFilename,
    buildCharacterCardExportUrl,
    cardExportFormatLabel,
    cardSpecLabel,
    isCharacterCardFile,
    normalizeCardCompatibility,
    normalizeCardImportResult,
    preservedCardMetadataGroups,
} from './characterCards';

const makeFile = (name, size = 128, type = '') => ({ name, size, type });

describe('character card file validation', () => {
    it('accepts png and json cards', () => {
        expect(CARD_ACCEPT).toContain('.png');
        expect(CARD_ACCEPT).toContain('.json');
        expect(isCharacterCardFile(makeFile('Lyra.PNG'))).toBe(true);
        expect(CARD_ACCEPT).toContain('.charx');
        expect(isCharacterCardFile(makeFile('lyra.charx'))).toBe(true);
        expect(isCharacterCardFile(makeFile('notes.txt'))).toBe(false);
        expect(isCharacterCardFile(null)).toBe(false);
    });

    it('rejects unsupported extensions with a readable message', () => {
        expect(() => assertCharacterCardFile(makeFile('lyra.txt'))).toThrow(/png.*json.*charx/i);
        expect(() => assertCharacterCardFile(null)).toThrow(/no file selected/i);
    });

    it('rejects empty and oversized cards before uploading', () => {
        expect(() => assertCharacterCardFile(makeFile('lyra.png', 0))).toThrow(/empty/i);
        expect(() => assertCharacterCardFile(makeFile('lyra.json', CARD_MAX_BYTES + 1))).toThrow(/too large/i);
        expect(assertCharacterCardFile(makeFile('lyra.json', 1024))).toBe(true);
    });
});

describe('normalizeCardImportResult', () => {
    it('handles the legacy bare-character response', () => {
        const { character, compatibility } = normalizeCardImportResult({ id: 'ch1', name: 'Aria' });
        expect(character).toEqual({ id: 'ch1', name: 'Aria' });
        expect(compatibility.hasReport).toBe(false);
        expect(compatibility.lost).toEqual([]);
        expect(compatibility.warnings).toEqual([]);
        expect(compatibility.lossless).toBe(true);
    });

    it('unwraps a character/compatibility envelope', () => {
        const { character, compatibility } = normalizeCardImportResult({
            character: { id: 'ch2', name: 'Orrin' },
            compatibility: {
                format: 'v2',
                spec: 'chara_card_v2.0',
                spec_version: '2.0',
                warnings: ['Tag list was mapped to visual tags'],
                lost_fields: ['extensions.tavern_helper'],
                preserved_fields: ['card_metadata'],
            },
        });

        expect(character).toEqual({ id: 'ch2', name: 'Orrin' });
        expect(compatibility.hasReport).toBe(true);
        expect(compatibility.format).toBe('v2');
        expect(compatibility.spec).toBe('chara_card_v2.0');
        expect(compatibility.specVersion).toBe('2.0');
        expect(compatibility.warnings[0].label).toBe('Tag list was mapped to visual tags');
        expect(compatibility.lost.map((e) => e.label)).toEqual(['extensions.tavern_helper']);
        expect(compatibility.preserved.map((e) => e.label)).toEqual(['card_metadata']);
        expect(compatibility.lossless).toBe(false);
    });

    it('survives alternate report/field key names', () => {
        const { character, compatibility } = normalizeCardImportResult({
            card: { id: 'ch3', name: 'Sable' },
            import_report: {
                card_format: 'json',
                dropped_fields: [{ field: 'post_history_instructions', reason: 'stored in editor' }],
                kept_fields: ['alternate_greetings'],
                messages: ['Embedded lorebook converted'],
            },
        });

        expect(character).toEqual({ id: 'ch3', name: 'Sable' });
        expect(compatibility.format).toBe('json');
        expect(compatibility.lost).toEqual([
            { id: 'post_history_instructions', label: 'post_history_instructions', detail: 'stored in editor' },
        ]);
        expect(compatibility.preserved.map((e) => e.label)).toEqual(['alternate_greetings']);
        expect(compatibility.warnings.map((e) => e.label)).toEqual(['Embedded lorebook converted']);
    });

    it('unwraps a data envelope and tolerates null payloads', () => {
        expect(normalizeCardImportResult({ data: { id: 'ch4', name: 'Nyx' } }).character).toEqual({
            id: 'ch4',
            name: 'Nyx',
        });
        const empty = normalizeCardImportResult(null);
        expect(empty.character).toBeNull();
        expect(empty.compatibility.hasReport).toBe(false);
    });
});

describe('normalizeCardCompatibility', () => {
    it('reads boolean detail flags', () => {
        const compat = normalizeCardCompatibility({
            lorebook_converted: true,
            unknown_extensions_preserved: 'false',
        });
        expect(compat.lorebookConverted).toBe(true);
        expect(compat.unknownExtensionsPreserved).toBe(false);
        expect(compat.hasReport).toBe(true);
    });

    it('de-duplicates and drops empty entries', () => {
        const compat = normalizeCardCompatibility({
            lost_fields: ['a', 'a', '', '  ', null, { key: 'b' }],
        });
        expect(compat.lost.map((e) => e.label)).toEqual(['a', 'b']);
        expect(compat.warnings).toEqual([]);
    });

    it('returns safe defaults for a missing report', () => {
        expect(normalizeCardCompatibility(undefined)).toEqual({
            format: '',
            spec: '',
            specVersion: '',
            warnings: [],
            lost: [],
            preserved: [],
            inert: [],
            lorebookConverted: null,
            unknownExtensionsPreserved: null,
            hasReport: false,
            lossless: true,
        });
    });

    it('is not lossless when features are preserved but not executed', () => {
        // The bucket that was missing. A card whose SillyTavern extensions
        // survive the trip but change nothing here is not "fully compatible" -
        // the data is safe, the BEHAVIOUR is not the same.
        const report = normalizeCardCompatibility({
            format: 'png',
            preserved_but_inert: [
                { name: 'data.extensions.regex_scripts', detail: 'preserved, not executed' },
            ],
        });
        expect(report.inert).toHaveLength(1);
        expect(report.inert[0].label).toContain('regex_scripts');
        expect(report.lossless).toBe(false);
    });
});

describe('export helpers', () => {
    it('omits the format param for the default export', () => {
        expect(buildCharacterCardExportUrl('ch1')).toBe('/api/v2/characters/ch1/export');
        expect(buildCharacterCardExportUrl('ch1', DEFAULT_CARD_EXPORT_FORMAT)).toBe(
            '/api/v2/characters/ch1/export'
        );
        expect(buildCharacterCardExportUrl(null)).toBeNull();
    });

    it('requests explicit formats for v3 and json', () => {
        expect(buildCharacterCardExportUrl('ch1', 'v3')).toBe('/api/v2/characters/ch1/export?format=v3');
        expect(buildCharacterCardExportUrl('ch1', 'json')).toBe('/api/v2/characters/ch1/export?format=json');
    });

    it('keeps the legacy filename for the default export', () => {
        expect(buildCharacterCardExportFilename({ name: 'Lyra Vane' })).toBe('Lyra_Vane_v2.png');
        expect(buildCharacterCardExportFilename({ name: 'Lyra Vane' }, 'v2')).toBe('Lyra_Vane_v2.png');
        expect(buildCharacterCardExportFilename({ name: 'Lyra Vane' }, 'v3')).toBe('Lyra_Vane_v3.png');
        expect(buildCharacterCardExportFilename({ name: 'Lyra Vane' }, 'json')).toBe('Lyra_Vane.json');
        expect(buildCharacterCardExportFilename({}, 'v3')).toBe('character_v3.png');
    });

    it('labels export formats for user-facing messages', () => {        expect(cardExportFormatLabel('default')).toBe('Default PNG');
        expect(cardExportFormatLabel('v2')).toBe('V2 PNG');
        expect(cardExportFormatLabel('v3')).toBe('V3 PNG');
        expect(cardExportFormatLabel('json')).toBe('JSON');
        expect(cardExportFormatLabel(undefined)).toBe('Default PNG');
        expect(cardExportFormatLabel('nonsense')).toBe('Default PNG');
    });
});

describe('card provenance helpers', () => {
    it('derives a compact spec label', () => {
        expect(cardSpecLabel('chara_card_v3', '3.0')).toBe('V3 · 3.0');
        expect(cardSpecLabel('chara_card_v2')).toBe('V2');
        expect(cardSpecLabel('')).toBe('');
    });

    it('summarizes preserved card metadata groups', () => {
        expect(preservedCardMetadataGroups(null)).toEqual([]);
        expect(preservedCardMetadataGroups({})).toEqual([]);
        expect(
            preservedCardMetadataGroups({
                root: { creator: 'x' },
                data: { post_history_instructions: 'p', assets: { image: 1 }, extensions: { regex_scripts: [] } },
                spec: 'chara_card_v2',
            })
        ).toEqual([
            { id: 'root', label: 'root', keys: ['creator'] },
            { id: 'data', label: 'data', keys: ['post_history_instructions'] },
            { id: 'data.extensions', label: 'data.extensions', keys: ['regex_scripts'] },
            { id: 'data.assets', label: 'data.assets', keys: ['image'] },
        ]);
    });

    it('reports an embedded character book group', () => {
        expect(preservedCardMetadataGroups({ data: { character_book: { entries: [] } } })).toEqual([
            { id: 'data.character_book', label: 'data.character_book', keys: ['embedded lorebook'] },
        ]);
    });
});
