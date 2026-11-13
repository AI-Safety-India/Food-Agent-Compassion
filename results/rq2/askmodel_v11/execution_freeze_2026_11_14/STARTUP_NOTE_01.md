# Startup correction — no study attempts

The first detached worker exited before importing the frozen runner: `ModuleNotFoundError: capacity_runner`. No summary, intent ledger, model load or study answer existed. The remote launch script directory was not on that interpreter's import path.

The corrected version explicitly inserts its own resolved directory into `sys.path` before importing the same frozen runner. The original worker, PID record and log remain preserved; version 2 uses a new worker filename, PID record and log. The runner, execution manifest, inputs, references, decoding and analysis rules are unchanged. This is an engineering-startup repair, not a repeated study attempt.
