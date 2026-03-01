const fs = require('fs');

const path = 'src/hooks/usePullToRefresh.jsx';
let content = fs.readFileSync(path, 'utf8');

content = content.replace(
    `        // Only enable pull-to-refresh when scrolled to top
        // Prioritize window scroll as it's the most common scroll container for full-page views
        const target = e.target;
        if (target && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName?.toUpperCase())) return;

        // Only enable pull-to-refresh when scrolled to top
        // Prioritize window scroll as it's the most common scroll container for full-page views
        const scrollTop = window.scrollY > 0 ? window.scrollY : (document.documentElement.scrollTop > 0 ? document.documentElement.scrollTop : (containerRef.current?.scrollTop ?? 0));`,
    `        const target = e.target;
        if (target && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName?.toUpperCase())) return;

        // Only enable pull-to-refresh when scrolled to top
        // Prioritize window scroll as it's the most common scroll container for full-page views
        const scrollTop = window.scrollY > 0 ? window.scrollY : (document.documentElement.scrollTop > 0 ? document.documentElement.scrollTop : (containerRef.current?.scrollTop ?? 0));`
);

fs.writeFileSync(path, content);
