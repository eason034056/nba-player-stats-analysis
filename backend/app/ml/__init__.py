"""Offline dataset export and the pregame baseline trainer.

Run ``python -m app.ml.build_dataset`` from ``backend/`` to write the
Parquet. Run ``python -m app.ml.train_baseline`` to fit one model per
catalog stat from that file. The export reads prior games, opening game
odds, and NBA absence context visible at one T. The trainer's headline
model uses the pregame form, schedule, and opening-odds columns only.

The API process must not import this package: a full history does not fit
in the API container, and nothing here writes ``predictions``. A live
absence read uses ``team_absences`` with one team's rows, not this package's
season export.
"""
