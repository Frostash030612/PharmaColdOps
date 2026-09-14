"""FastAPI decision service for PharmaColdOps.

Serves the *real* Python rule engine (``src/rule_engine``) to the static demo
(``frontend-vue`` / ``index-zh.html``). The demo stays fully offline by
default and opts into this backend with ``?api=http://host:port``.

Contract boundary: this service is authoritative about decision *semantics*
(disposition, rule_no, reshipment, risk score + cause code, evidence
classification). Human-facing wording (reasons, regulations, cause text) is
localised on the client so the English and Chinese demos do not force two
languages into the Python engine.
"""
