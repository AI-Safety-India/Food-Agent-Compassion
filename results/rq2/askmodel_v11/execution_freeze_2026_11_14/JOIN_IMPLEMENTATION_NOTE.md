# Exact-run join implementation timing

The exact selected-history-to-original-run join was specified in the committed generation protocol. Its pure helper and five synthetic tests were completed after worker launch and before any study answer was inspected or semantically scored. This records implementation timing rather than claiming all implementation preceded launch.

The helper does not change input selection, references, answer scoring or study denominators. It deduplicates original run IDs across multiple selected option contexts and distinguishes having a selected run from having the exact ordered option's selected context. It never extrapolates answers to other original runs. Score0 is the existing RQ1 annotation, not proof of no prior language or internal evaluation.
