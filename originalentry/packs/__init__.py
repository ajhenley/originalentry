"""Content packs: pydantic schema, validation, and (later) the zip importer.

``schema`` is imported by both the app and the offline generator so they cannot disagree about
the pack format (T5). ``grading`` may import ``packs.schema`` but nothing else here.
"""
