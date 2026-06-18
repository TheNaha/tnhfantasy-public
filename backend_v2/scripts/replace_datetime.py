import os
import re
from pathlib import Path

def process_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    if 'datetime.now(timezone.utc)' not in content and 'datetime.utcnow' not in content:
        return False

    # Replace datetime.now(timezone.utc) with datetime.now(timezone.utc)
    # Also handle references like `default_factory=lambda: datetime.now(timezone.utc)` -> `default_factory=lambda: datetime.now(timezone.utc)`
    new_content = content.replace('datetime.now(timezone.utc)', 'datetime.now(timezone.utc)')
    
    # Handle default_factory=lambda: datetime.now(timezone.utc)
    new_content = re.sub(r'default_factory=datetime\.utcnow\b', 'default_factory=lambda: datetime.now(timezone.utc)', new_content)
    # Handle default=lambda: datetime.now(timezone.utc)
    new_content = re.sub(r'default=datetime\.utcnow\b', 'default=lambda: datetime.now(timezone.utc)', new_content)

    if new_content != content:
        # Check if timezone is imported
        if 'from datetime import' in new_content:
            if 'timezone' not in new_content:
                new_content = re.sub(r'(from datetime import [^\n]*)', r'\1, timezone', new_content, count=1)
        elif 'import datetime' in new_content:
            if 'timezone' not in new_content:
                new_content = new_content.replace('import datetime', 'import datetime\nfrom datetime import timezone')
        else:
            # just add to top
            new_content = 'from datetime import timezone\n' + new_content

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

def main():
    backend_dir = Path(__file__).parent.parent
    changed = 0
    for root, dirs, files in os.walk(backend_dir):
        if 'venv' in root or '__pycache__' in root or 'node_modules' in root:
            continue
        for file in files:
            if file.endswith('.py'):
                if process_file(os.path.join(root, file)):
                    changed += 1
                    print(f"Updated {file}")
    
    print(f"Total files updated: {changed}")

if __name__ == '__main__':
    main()
