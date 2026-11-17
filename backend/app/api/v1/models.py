"""Compatibility module.

The OpenAI-shaped ``GET /v1/models`` lives in ``app/api/v1/openai.py`` so that the
persona list and the chat surface share one resolution path. This module intentionally
exports no router to avoid a duplicate route registration.
"""
