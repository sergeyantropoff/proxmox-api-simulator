# SDN

Software-defined networking handlers cover declared zones, VNets, subnets,
controllers, IPAM, DNS, fabrics, locks, and related dry-run/rollback style
operations for the active major.

State is local to the simulator database. Switching majors 6–9 updates which
SDN methods exist on the wire; all declared ones are implemented.
