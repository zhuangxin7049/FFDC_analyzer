"""Read the workspace without importing application code; emit structural evidence."""
import ast
import collections
import hashlib
import io
import json
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs' / '_audit'
CORE = {'app.py', 'ffdc_chat.py', 'workspace_analysis.py', 'workspace_ui.py', 'ffdc_config.py', 'ffdc_jobs.py'}
SECRET = re.compile(r'(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[^\s"\']+|Basic\s+[A-Za-z0-9+/=]{12,})', re.I)


def clean(value):
    return SECRET.sub('[REDACTED]', str(value))


def expr(node, limit=240):
    return clean(ast.unparse(node))[:limit] if node is not None else 'None'


def own_walk(node):
    yield node
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            continue
        yield from own_walk(child)


def typ(node):
    if isinstance(node, ast.Constant):
        return type(node.value).__name__
    if isinstance(node, (ast.Dict, ast.DictComp)):
        return 'dict'
    if isinstance(node, (ast.List, ast.ListComp)):
        return 'list'
    if isinstance(node, ast.Tuple):
        return 'tuple'
    if isinstance(node, (ast.Set, ast.SetComp)):
        return 'set'
    if isinstance(node, (ast.Compare, ast.BoolOp)):
        return 'bool'
    if isinstance(node, ast.JoinedStr):
        return 'str'
    if isinstance(node, ast.Call):
        name = expr(node.func)
        if name in {'str', 'int', 'bool', 'float', 'dict', 'list', 'tuple', 'set', 'Path'}:
            return name
        if name.endswith(('json.loads', 'json.load')):
            return 'JSON value'
        if name.endswith(('.read_text', '.decode', '.join', '.strip', '.geturl')):
            return 'str'
        if name.endswith(('.read_bytes', '.encode', '.getvalue')):
            return 'bytes or stream value'
    return 'dynamic (not annotated)'


def scan_py(path, text):
    tree = ast.parse(text, filename=str(path))
    funcs, classes, imports, configs, effects = [], [], [], [], []
    all_loads = collections.Counter(n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load))
    calls = collections.Counter(expr(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call))

    def visit(body, prefix=''):
        for node in body:
            if isinstance(node, ast.ClassDef):
                attrs = {}
                for n in ast.walk(node):
                    if isinstance(n, (ast.Assign, ast.AnnAssign)):
                        for target in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                            if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) and target.value.id == 'self':
                                attrs[target.attr] = {'line': n.lineno, 'value': expr(n.value), 'type': typ(n.value)}
                classes.append({'name': prefix + node.name, 'line': node.lineno, 'end': node.end_lineno, 'bases': [expr(b) for b in node.bases], 'attributes': attrs})
                visit(node.body, prefix + node.name + '.')
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                nodes = list(own_walk(node))
                args = []
                positional = node.args.posonlyargs + node.args.args
                defaults = [None] * (len(positional) - len(node.args.defaults)) + list(node.args.defaults)
                for arg, default in zip(positional + node.args.kwonlyargs, defaults + node.args.kw_defaults):
                    args.append({'name': arg.arg, 'type': expr(arg.annotation) if arg.annotation else (typ(default) if default is not None else 'not annotated'), 'default': expr(default) if default is not None else '(required)'})
                for arg, symbol in ((node.args.vararg, '*'), (node.args.kwarg, '**')):
                    if arg:
                        args.append({'name': symbol + arg.arg, 'type': 'tuple' if symbol == '*' else 'dict', 'default': '(variadic)'})
                returns = [{'line': n.lineno, 'expression': expr(n.value, 400), 'type': typ(n.value)} for n in nodes if isinstance(n, ast.Return)]
                writes = [n for n in nodes if isinstance(n, ast.Call) and re.search(r'\.(?:write_text|write_bytes|open|unlink|mkdir|rmtree|copyfileobj|replace|rename|urlopen|run|Popen|start|acquire|release|extractall)\b', expr(n.func))]
                local_calls = sorted({expr(n.func) for n in nodes if isinstance(n, ast.Call)})
                fn = {'name': prefix + node.name, 'line': node.lineno, 'end': node.end_lineno, 'doc': ast.get_docstring(node) or '', 'args': args, 'returns': returns, 'return_annotation': expr(node.returns) if node.returns else '', 'calls': local_calls, 'globals': [x for n in nodes if isinstance(n, ast.Global) for x in n.names], 'effects': [{'line': n.lineno, 'expression': expr(n, 400)} for n in writes], 'raises': [{'line': n.lineno, 'expression': expr(n.exc)} for n in nodes if isinstance(n, ast.Raise)], 'dict_keys': sorted({str(k.value) for n in nodes if isinstance(n, ast.Dict) for k in n.keys if isinstance(k, ast.Constant) and isinstance(k.value, str)})}
                funcs.append(fn)
    visit(tree.body)
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            modules = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or '']
            imports.extend({'line': n.lineno, 'module': m, 'statement': expr(n), 'unused_candidates': [a.asname or a.name.split('.')[0] for a in n.names if not all_loads[a.asname or a.name.split('.')[0]]]} for m in modules)
        if isinstance(n, ast.Call) and expr(n.func) in {'os.environ.get', 'os.getenv'}:
            configs.append({'line': n.lineno, 'name': expr(n.args[0]) if n.args else '?', 'default': expr(n.args[1], 1000) if len(n.args) > 1 else 'None'})
    for n in tree.body:
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            effects.append({'line': n.lineno, 'kind': type(n).__name__, 'expression': expr(n, 450)})
    nested = []
    def depth(n, level=0):
        is_control = isinstance(n, (ast.If, ast.For, ast.AsyncFor, ast.While, ast.Try, ast.With))
        level = level + int(is_control)
        if is_control and level > 3:
            nested.append({'line': n.lineno, 'depth': level, 'kind': type(n).__name__})
        for child in ast.iter_child_nodes(n):
            depth(child, 0 if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) else level)
    depth(tree)
    numbers = collections.defaultdict(list)
    for n in ast.walk(tree):
        if isinstance(n, ast.Constant) and type(n.value) in {int, float} and n.value not in {-1, 0, 1, 2}:
            numbers[str(n.value)].append(n.lineno)
    fingerprints = collections.defaultdict(list)
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.end_lineno - n.lineno >= 5:
            normalized = ast.Module(body=n.body, type_ignores=[])
            fingerprints[hashlib.sha256(ast.dump(normalized, include_attributes=False).encode()).hexdigest()].append({'name': n.name, 'line': n.lineno})
    tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    human = '\n'.join(t.string for t in tokens if t.type in {tokenize.COMMENT, tokenize.STRING})
    return {'functions': funcs, 'classes': classes, 'imports': imports, 'environment': configs, 'module_effects': effects, 'nesting': nested, 'numeric_literals': dict(numbers), 'identical_function_bodies': [v for v in fingerprints.values() if len(v) > 1], 'print_calls': [{'line': n.lineno, 'expression': expr(n)} for n in ast.walk(tree) if isinstance(n, ast.Call) and expr(n.func) == 'print'], 'calls': dict(calls), 'language': {'latin_words': len(re.findall(r'\b[A-Za-z]{3,}\b', human)), 'han_characters': len(re.findall(r'[\u4e00-\u9fff]', human))}, 'leading_tabs': [i for i, line in enumerate(text.splitlines(), 1) if line.startswith('\t')], 'top_level_definition_spacing': [{'line': b.lineno, 'blank_lines': sum(not x.strip() for x in text.splitlines()[a.end_lineno:b.lineno - 1])} for a, b in zip(tree.body, tree.body[1:]) if isinstance(b, (ast.FunctionDef, ast.ClassDef)) and sum(not x.strip() for x in text.splitlines()[a.end_lineno:b.lineno - 1]) < 2]}


def main():
    inventory, modules, errors = [], {}, []
    root_entries = sorted(p.name for p in ROOT.iterdir())
    for path in sorted(ROOT.rglob('*')):
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(('docs/', '.git/')):
            continue
        if path.is_symlink():
            inventory.append({'path': rel, 'kind': 'symlink; not followed'})
            continue
        if not path.is_file():
            inventory.append({'path': rel, 'kind': 'directory'})
            continue
        try:
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            binary = b'\0' in data[:8192]
            try:
                text = data.decode('utf-8') if not binary else None
                encoding = 'UTF-8' if text is not None else 'binary'
            except UnicodeDecodeError:
                text = None
                encoding = 'non-UTF-8 or binary'
            role = 'runtime' if rel in CORE or rel.startswith('static/') else 'test' if path.parent == ROOT and path.name.startswith('test_') else 'historical backup' if path.name.startswith('app.py.') else 'support script' if path.parent == ROOT and path.suffix == '.py' else 'artifact/data/config/vendor'
            inventory.append({'path': rel, 'kind': role, 'bytes': len(data), 'sha256': sha, 'encoding': encoding, 'lines': len(text.splitlines()) if text is not None else None, 'full_bytes_read': True})
            if text is not None and (path.parent == ROOT and (path.suffix == '.py' or path.name.startswith('app.py.'))):
                modules[rel] = scan_py(path, text)
        except Exception as exc:
            errors.append({'path': rel, 'error': type(exc).__name__ + ': ' + str(exc)})
    groups = collections.defaultdict(list)
    for row in inventory:
        if row.get('sha256'):
            groups[row['sha256']].append(row['path'])
    result = {'scope': 'Full byte-read inventory excluding generated docs and git internals; full AST traversal for root Python sources and historical app copies. Binary artifacts are hashed, not semantically interpreted. No application code imported or executed.', 'python': sys.version, 'root_entries': root_entries, 'inventory': inventory, 'modules': modules, 'errors': errors, 'duplicate_files': [v for v in groups.values() if len(v) > 1]}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'structure.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'files': sum('sha256' in r for r in inventory), 'bytes_read': sum(r.get('bytes', 0) for r in inventory), 'modules': len(modules), 'runtime_functions': sum(len(modules[n]['functions']) for n in CORE), 'errors': errors, 'core_language': {n: modules[n]['language'] for n in CORE}}, indent=2))


if __name__ == '__main__':
    main()
