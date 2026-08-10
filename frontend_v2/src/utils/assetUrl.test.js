import { describe, it, expect } from 'vitest';
import { assetUrl, thumbUrl, assetMetadataUrl } from './assetUrl';

describe('assetUrl', () => {
    it('builds the full-resolution output URL', () => {
        expect(assetUrl('img.png')).toBe('/api/view/output/img.png');
    });

    it('URL-encodes the filename', () => {
        expect(assetUrl('my image.png')).toBe('/api/view/output/my%20image.png');
    });
});

describe('assetMetadataUrl', () => {
    it('appends .json', () => {
        expect(assetMetadataUrl('img.png')).toBe('/api/view/output/img.png.json');
    });

    it('URL-encodes the filename', () => {
        expect(assetMetadataUrl('a b.png')).toBe('/api/view/output/a%20b.png.json');
    });
});

describe('thumbUrl', () => {
    it('defaults to medium size', () => {
        expect(thumbUrl('img.png')).toBe('/api/thumbnail/medium/img.png');
    });

    it('supports a custom size', () => {
        expect(thumbUrl('img.png', { size: 'small' })).toBe('/api/thumbnail/small/img.png');
    });

    it('URL-encodes the filename', () => {
        expect(thumbUrl('my image.png')).toBe('/api/thumbnail/medium/my%20image.png');
    });
});
