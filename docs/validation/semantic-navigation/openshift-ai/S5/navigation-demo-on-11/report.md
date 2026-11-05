# G5 navigation demo run 11

## Outcome

Navigation never started. The fixture stopped during its installed adapter
regression checks, before the operator hold. The new ingress drain assumed the
production `timings` member on the test's lightweight adapter fixture and
raised `AttributeError`. Cleanup and restoration succeeded. The correction
guards the immediate drain when a test double does not implement `drain()`;
run 12's installed adapter suite then passed all 10 tests.
