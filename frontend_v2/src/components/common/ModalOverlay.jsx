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
 */
export function ModalOverlay({
    isOpen = true,
    onClose,
    closeOnBackdrop = true,
    className = '',
    children,
}) {
    useEscapeKey(onClose, isOpen);

    if (!isOpen) return null;

    return createPortal(
        <div
            className={`fixed inset-0 flex items-center justify-center p-4 ${className}`.trim()}
            data-modal-overlay=""
            onClick={closeOnBackdrop ? onClose : undefined}
        >
            {children}
        </div>,
        document.body,
    );
}

export default ModalOverlay;
