# Ceph

Ceph-related API paths persist simulated cluster, pool, OSD, and monitor state.
They do not speak to a live Ceph cluster.

Legacy path aliases (for example historical `ceph/pools` spellings) map onto the
shared handlers so older majors remain fully routed.
