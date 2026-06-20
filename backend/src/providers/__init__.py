"""Provider abstraction layer.

All STT / LLM / TTS access goes through the base interfaces in this package
(ARCHITECTURE.md §2, §5). No vendor SDK is imported outside a concrete provider
implementation module.
"""
