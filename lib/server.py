import sys


def select_server(servers, state, name_arg=None, filter_fn=None, prompt="Select a server"):
    """Return a single server dict.

    If name_arg is given, look it up directly.
    Otherwise show a numbered menu filtered by filter_fn (or all servers).
    """
    candidates = [s for s in servers if filter_fn is None or filter_fn(s)]
    if not candidates:
        sys.exit("No matching servers found in honey-net.json")

    if name_arg:
        matches = [s for s in candidates if s["name"] == name_arg]
        if not matches:
            sys.exit(f"Server '{name_arg}' not found in honey-net.json")
        return matches[0]

    if len(candidates) == 1:
        return candidates[0]

    print(f"\n{prompt}:")
    for i, s in enumerate(candidates, start=1):
        e      = state.get(s["name"], {})
        pub_ip = e.get("public_ip")    or "(no public IP)"
        ts_ip  = e.get("tailscale_ip") or "(no Tailscale IP)"
        ports  = ", ".join(str(p) for p in s.get("ports", [])) or "none"
        print(f"  [{i}] {s['name']:<25} type={s['type']:<10} "
              f"ports={ports:<12} public={pub_ip:<16} tailscale={ts_ip}")
    print()
    choice = input("Enter number: ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(candidates)):
        sys.exit("Invalid selection")
    return candidates[int(choice) - 1]
