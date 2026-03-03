const fs = require('fs');
const path = 'frontend_v2/src/hooks/usePullToRefresh.jsx';
let content = fs.readFileSync(path, 'utf8');

// Replace the buggy scrollTop calculation
let newScrollTopLogic = `        // Find the actual scroll container dynamically
        const getScrollTop = () => {
            // Check if we are inside a custom main scroll container
            const mainContainer = document.getElementById('main-scroll-container');
            if (mainContainer) {
                const style = window.getComputedStyle(mainContainer);
                if (style.overflowY === 'auto' || style.overflowY === 'scroll') {
                    return mainContainer.scrollTop;
                }
            }

            // Fallback to window/document
            return window.scrollY || document.documentElement.scrollTop || containerRef.current?.scrollTop || 0;
        };

        const scrollTop = getScrollTop();`;

content = content.replace(
    /const scrollTop = window\.scrollY > 0 \? window\.scrollY : \(document\.documentElement\.scrollTop > 0 \? document\.documentElement\.scrollTop : \(containerRef\.current\?\.scrollTop \?\? 0\)\);/,
    newScrollTopLogic
);

fs.writeFileSync(path, content);
console.log("Updated usePullToRefresh.jsx");
