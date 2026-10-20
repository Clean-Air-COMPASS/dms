# Reference Threshold test plugin

This package exists only for deployment and end-to-end tests. Its check code is
not referenced by CompassAQ application source. Tests install its standard
Python entry-point metadata in an isolated directory to prove that discovery,
configuration, execution, persistence, and presentation use the public QC
plugin contract.
