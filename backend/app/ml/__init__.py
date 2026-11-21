"""Offline dataset export for the player-props model.

Run ``python -m app.ml.build_dataset`` from ``backend/``. The export reads
prior games and opening game odds visible at T. The API process must not
import this package: a full history does not fit in the API container, and
nothing here writes ``predictions``.
"""
