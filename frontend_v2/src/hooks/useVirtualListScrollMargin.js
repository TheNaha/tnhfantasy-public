import { useLayoutEffect, useState } from 'react';

export function useVirtualListScrollMargin(containerRef) {
    const [scrollMargin, setScrollMargin] = useState(0);

    useLayoutEffect(() => {
        const container = containerRef.current;
        if (!container) return undefined;

        const update = () => {
            const rect = container.getBoundingClientRect();
            setScrollMargin(Math.max(0, rect.top + window.scrollY));
        };

        update();
        window.addEventListener('resize', update);
        const observer = typeof ResizeObserver !== 'undefined'
            ? new ResizeObserver(update)
            : null;
        observer?.observe(container);

        return () => {
            window.removeEventListener('resize', update);
            observer?.disconnect();
        };
    }, [containerRef]);

    return scrollMargin;
}
