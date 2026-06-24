import fs from 'fs';
import path from 'path';

const searchDirs = ['./src/pages', './src/components'];

function processFile(filePath) {
    if (!filePath.endsWith('.jsx')) return;
    
    let content = fs.readFileSync(filePath, 'utf8');
    let newContent = content;

    // 1. Remove double paddings that are wrapping pages
    newContent = newContent.replace(/className="min-h-screen\s+p-4\s+lg:p-8\s+relative"/g, 'className="relative w-full"');
    newContent = newContent.replace(/className="min-h-screen\s+p-4\s+lg:p-8"/g, 'className="w-full"');
    newContent = newContent.replace(/className="mx-auto\s+max-w-7xl\s+p-6"/g, 'className="mx-auto max-w-7xl"');
    
    // 2. Adjust heading sizes
    newContent = newContent.replace(/className="text-3xl\s+font-black/g, 'className="text-2xl md:text-3xl font-black');
    newContent = newContent.replace(/className="text-3xl\s+font-bold/g, 'className="text-2xl md:text-3xl font-bold');
    
    // 3. Make paddings responsive
    newContent = newContent.replace(/className="glass-panel\s+([^"]*?)p-6([^"]*?)"/g, 'className="glass-panel $1p-4 md:p-6$2"');
    newContent = newContent.replace(/className="([^"]*?)p-6\s+rounded-3xl([^"]*?)"/g, 'className="$1p-4 md:p-6 rounded-3xl$2"');
    
    // 4. Adjust spacing
    newContent = newContent.replace(/space-y-6/g, 'space-y-4 md:space-y-6');
    newContent = newContent.replace(/space-y-8/g, 'space-y-4 md:space-y-8');
    
    if (content !== newContent) {
        fs.writeFileSync(filePath, newContent);
        console.log('Updated:', filePath);
    }
}

function traverseDir(dir) {
    const files = fs.readdirSync(dir);
    for (const file of files) {
        const fullPath = path.join(dir, file);
        if (fs.statSync(fullPath).isDirectory()) {
            traverseDir(fullPath);
        } else {
            processFile(fullPath);
        }
    }
}

searchDirs.forEach(traverseDir);
console.log('Done');
