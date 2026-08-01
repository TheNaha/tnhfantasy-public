import ast
import os


def check_unreachable(filepath):
    with open(filepath, 'r') as f:
        try:
            tree = ast.parse(f.read(), filename=filepath)
        except SyntaxError:
            return
            
    for node in ast.walk(tree):
        if hasattr(node, 'body') and isinstance(node.body, list):
            for i in range(len(node.body) - 1):
                stmt = node.body[i]
                if isinstance(stmt, (ast.Return, ast.Raise, ast.Break, ast.Continue)):
                    next_stmt = node.body[i+1]
                    print(f"{filepath}:{next_stmt.lineno} unreachable code after {type(stmt).__name__} at line {stmt.lineno}")

for root, _, files in os.walk('api/routes'):
    for file in files:
        if file.endswith('.py'):
            check_unreachable(os.path.join(root, file))
