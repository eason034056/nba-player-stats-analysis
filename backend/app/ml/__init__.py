"""Offline dataset export for the player-props model.

Run ``python -m app.ml.build_dataset`` from ``backend/``. The export reads
prior games, opening game odds, and NBA absence context visible at one T.
The API process must not import this package: a full history does not fit
in the API container, and nothing here writes ``predictions``. A live
absence read uses ``team_absences`` with one team's rows, not this package's
season export.
"""
