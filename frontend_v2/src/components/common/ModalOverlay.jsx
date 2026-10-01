import { createPortal } from 'react-dom';

import { useEscapeKey } from '../../hooks/useEscapeKey';

/**
 * The backdrop layer every dialog needs: portal, Escape to dismiss, and a
 * backdrop click that does not fire when the panel is clicked.
 *
 * Children render exactly as written, so adopting this is a one-line change —
 * replace the dialog's own `fixed inset-0` wrapper:
 *
 *   - <div className="fixed inset-0 z-50 bg-black/80" onClick={onClose}>
 *   -   <div onClick={(e) => e.stopPropagation()}> ...panel... </div>
 *   - </div>
 *   + <ModalOverlay onClose={onClose} className="z-50 bg-black/80">
 *   +   ...panel...
 *   + </ModalOverlay>
 *
 * A dialog that only needs Escape, and keeps its own animation structure, can
 * call useEscapeKey directly instead of restructuring its markup.
 *
 * `centered={false}` drops the flex/centering/padding defaults for the rare
 * dialog that scrolls its own full-bleed layout (e.g. the model metadata
 * sheet); the backdrop click and Escape still come from this component.
 *
 * `role="dialog"` deliberately is NOT set here. This is the backdrop layer; the
 * panel inside it is the dialog. 22 of the dialog components already declare
 * `role="dialog"` on that panel, and putting the role here as well nests a
 * dialog inside a dialog — which testing-library rejects outright, and which
 * assistive tech resolves arbitrarily. The components that genuinely lack the
 * role need it on their panel; adding it to the shared backdrop is the wrong
 * layer and breaks the ones that are already right.
 */
export function ModalOverlay({
    isOpen = true,
    onClose,
    closeOnBackdrop = true,
    centered = true,
    className = '',
    children,
}) {
    useEscapeKey(onClose, isOpen);

    if (!isOpen) return null;

    const layout = centered ? 'flex items-center justify-center p-4' : '';

    return createPortal(
        <div
            className={`fixed inset-0 ${layout} ${className}`.trim()}
            data-modal-overlay=""
            onClick={closeOnBackdrop ? onClose : undefined}
        >
            {children}
        </div>,
        document.body,
    );
}

export default ModalOverlay;
