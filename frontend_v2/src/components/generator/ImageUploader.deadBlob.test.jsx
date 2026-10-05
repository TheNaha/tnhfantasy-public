import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import ImageUploader from './ImageUploader';

/**
 * A persisted `blob:` URL made the dropzone unreachable.
 *
 * The user's-visible half of the `generatorStore` `partialize` defect:
 * `ipAdapters[i].image.previewUrl` was a `URL.createObjectURL(file)` value that
 * got written to localStorage. Blob URLs are scoped to the document that
 * created them, so it is dead after a reload — but the persisted entry is still
 * truthy, and this component branches on truthiness. The result is an
 * `<img>` rendering a dead URL over the drop area, with the dropzone
 * underneath unreachable, leaving only the clear button as a way out.
 *
 * These cases pin the branch: `previewUrl` must be a live URL to count as an
 * image at all.
 */

describe('ImageUploader', () => {
    it('shows the dropzone when there is no image', () => {
        render(<ImageUploader image={null} onImageSelect={() => {}} onClear={() => {}} />);

        expect(screen.getByText(/Drop image here or click to upload/i)).toBeInTheDocument();
    });

    it('shows a dead blob previewUrl as the broken image it is, not as a dropzone', () => {
        // Documents the CURRENT behaviour, and therefore why the store fix is
        // load-bearing: this component cannot tell a live blob URL from a dead
        // one. If this ever starts rendering a dropzone for a dead blob, the
        // store fix is no longer the only thing standing between a user and an
        // unreachable dropzone.
        render(
            <ImageUploader
                image={{ previewUrl: 'blob:http://100.150.0.4:5174/deadbeef' }}
                onImageSelect={() => {}}
                onClear={() => {}}
            />,
        );

        expect(screen.getByRole('img')).toHaveAttribute(
            'src',
            'blob:http://100.150.0.4:5174/deadbeef'
        );
        expect(screen.queryByText(/Drop image here or click to upload/i)).toBeNull();
    });

    it('offers a clear control that is the only escape from that state', () => {
        render(
            <ImageUploader
                image={{ previewUrl: 'blob:http://100.150.0.4:5174/deadbeef' }}
                onImageSelect={() => {}}
                onClear={() => {}}
            />,
        );

        expect(screen.getByRole('button', { name: /clear|remove/i })).toBeInTheDocument();
    });

    it('uses localPreview for a server-hosted image', () => {
        render(
            <ImageUploader
                image={{ localPreview: '/api/v2/files/preview/abc.png' }}
                onImageSelect={() => {}}
                onClear={() => {}}
            />,
        );

        expect(screen.getByRole('img').getAttribute('src')).toMatch(/preview\/abc\.png$/);
    });
});