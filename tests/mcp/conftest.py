import importlib

collect_ignore_glob = []

if importlib.util.find_spec("mcp") is None:
    collect_ignore_glob.append("test_*.py")
