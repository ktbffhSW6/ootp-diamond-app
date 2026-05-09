"""Provider adapters — one module per backend.

D14 commits to a thin ``AIClient`` interface with concrete adapters
per provider, no vendor lock-in. v1 ships Anthropic + OpenAI; adding
a new provider = drop in another module + register in
``client.get_active_client``.
"""
