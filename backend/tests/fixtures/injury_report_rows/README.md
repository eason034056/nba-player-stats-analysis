# Injury-report row fixtures

synthetic: true

The tests do not store an official NBA PDF and do not copy text from one.
`test_spo150_injury_report_rows.py` builds a short PDF in memory with reportlab
(a test-only dependency). The player names (`Doe, Jr., Alex`, `Smith, Alex`,
`Rivera, Ana`, `Chen, Mei`) and the reasons (`Left Thumb Sprain`,
`Right Knee; Soreness`, `Left Ankle; Dislocation`) are made up. They only
reproduce the column layout: a header, a two-comma name, a wrapped reason,
a page break, `NOT YET SUBMITTED`, and `ALL PLAYERS AVAILABLE`.
