const fs = require('fs');

const path = 'src/hooks/usePullToRefresh.jsx';
let content = fs.readFileSync(path, 'utf8');

// We need to ignore input elements in handleTouchStart
// const target = e.target;
// if (['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON'].includes(target.tagName)) return;

content = content.replace(
    'const scrollTop = window.scrollY > 0 ? window.scrollY : (containerRef.current?.scrollTop ?? 0);',
    `const target = e.target;
        if (target && ['INPUT', 'TEXTAREA', 'SELECT', 'BUTTON', 'RANGE'].includes(target.tagName?.toUpperCase())) return;

        const scrollTop = window.scrollY > 0 ? window.scrollY : (document.documentElement.scrollTop > 0 ? document.documentElement.scrollTop : (containerRef.current?.scrollTop ?? 0));`
);

fs.writeFileSync(path, content);
