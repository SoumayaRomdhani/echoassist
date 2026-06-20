"""Retrieval-augmented generation: chunking, embeddings, vector store, retriever.

The offline pipeline (documents -> chunk -> embed -> index) is never run during a
call (ARCHITECTURE.md §4). At query time the retriever does hybrid dense+sparse
search, RRF fusion, and cross-encoder reranking.
"""
