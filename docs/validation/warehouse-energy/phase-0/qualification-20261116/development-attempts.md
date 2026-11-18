# Development attempts retained outside the qualification counts

The [archive](development-attempts.tar.gz) preserves these attempts. None counts
toward the 36-trial physical matrix or the final four-case route series.

| Attempt | Disposition | Finding / correction |
| --- | --- | --- |
| `pilot-a-up` | Failed before traversal | The generated OBJ omitted normals. The pinned DART/ODE loader rejected it and crashed. Added per-face unit normals and a closed-mesh regression check. |
| `pilot-a-up-2` | **Invalid actuator evidence**, despite its historical runner `PASS` | Physical traversal/hold completed, but PostUpdate force samples were all zero after physics cleared the command components. Moved the observation-only plugin to PreUpdate after force controllers and added nonzero-effort evidence requirements. |
| `pilot-a-down` | Supporting pilot only | Loaded downhill travel and hold passed with nonzero bounded torque; excluded from the independently reset matrix. |
| `nav-A-up-1` | Startup error; no task dispatched | Trial node assigned to rclpy's read-only `clients` property. Renamed the member to `lifecycle_clients`. Launcher stopped all child processes. |
| `nav-A-up-2` | Supporting direct-route pilot | RMF-dispatched A uphill passed; the later final series adds accepted schedule mirror evidence. |
| `navigation-series-v1/A-up`, `A-down` | Passing but superseded route trials | Included accepted schedule mirror updates and physical route agreement. Repeated against the corrected full world for final qualification. |
| `navigation-series-v1/B-up` | Failed and cancelled | A full-height perpendicular deck overlapped the last 0.75 m of ramp B. Robot stalled at x=21.237 m with bounded wheel effort; Nav2 reported failure to make progress. Clipped the deck to the side boundary and added a top pad beginning at the actual crest x=22 m. Added a geometry regression check. |

The isolated ramp matrix already had its upper plateau beginning at the exact
ramp endpoint, so the full-warehouse deck correction does not alter its geometry
or invalidate the matrix. The final live route series repeats all four cases in
the corrected full warehouse. The failure is a fixture collision-geometry error,
not evidence of lower energy use or a successful task.
