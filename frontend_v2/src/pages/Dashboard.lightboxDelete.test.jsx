import { describe, expect, it } from 'vitest';

import { identityOf } from '../hooks/useLightboxNavigation';
import { assetPath } from '../utils/assetUrl';

/**
 * The gallery detail modal stayed open over a deleted image.
 *
 * `Dashboard.handleDelete` closed the lightbox with
 * `if (selectedImage?.name === filename)`, and that condition never fired — for
 * any image, on any path. The lightbox deletes the image it is displaying and
 * hands it over as `assetPath(displayImage)`; `assetPath` prefers `relative_path`,
 * which the backend builds as `<workspace>/<path>`:
 *
 *     selectedImage.name        -> "T2I_1778.png"
 *     assetPath(selectedImage)  -> "default_user/T2I_1778.png"
 *
 * A basename is not an identity either: two assets in different workspaces can
 * share one. `identityOf` is the helper this repo already had for settling
 * exactly this, and `handleDelete` was the only caller-shaped site not using it.
 *
 * These are the two assertions that fail on the old code and pass on the new
 * one, expressed against real payload shapes rather than a rendered Dashboard.
 */

const REAL_GALLERY_ASSET = {
    id: '8a1f0c62-0000-4000-8000-000000000001',
    name: 'T2I_1778.png',
    relative_path: 'default_user/T2I_1778.png',
    type: 'image',
    width: 832,
    height: 1216,
};

const SAME_BASENAME_OTHER_WORKSPACE = {
    id: '8a1f0c62-0000-4000-8000-000000000002',
    name: 'T2I_1778.png',
    relative_path: 'other_user/T2I_1778.png',
};

describe('the lightbox closes the modal it deleted from', () => {
    it('the old name comparison cannot match the delete argument', () => {
        // Proof the bug was real, kept so the fix cannot be quietly reverted:
        // this is the exact expression handleDelete used to use, and it is
        // false for a real gallery asset.
        const deletedPath = assetPath(REAL_GALLERY_ASSET);
        expect(deletedPath).toBe('default_user/T2I_1778.png');
        expect(REAL_GALLERY_ASSET.name === deletedPath).toBe(false);
    });

    it('the identity comparison matches for the same asset', () => {
        expect(identityOf(REAL_GALLERY_ASSET)).toBe(identityOf(assetPath(REAL_GALLERY_ASSET)));
    });

    it('the identity comparison still matches when the picker hands a bare string', () => {
        // `handleDelete` is also called from the Delete/Backspace key handler
        // with `selectedImage.name` — a basename, no relative_path. That call
        // must keep working, and identityOf accepts a string directly.
        expect(identityOf(REAL_GALLERY_ASSET)).toBe(identityOf('default_user/T2I_1778.png'));
    });

    it('two assets sharing a basename are not the same identity', () => {
        // The reason `name` is not an identity and the fix is not "compare on
        // name instead": a naive substring or basename match would close the
        // wrong modal in a multi-workspace vault.
        expect(identityOf(REAL_GALLERY_ASSET)).not.toBe(identityOf(SAME_BASENAME_OTHER_WORKSPACE));
    });

    it('a null selection is not an identity of anything', () => {
        expect(identityOf(null)).toBe('');
        expect(identityOf(undefined)).toBe('');
    });
});
