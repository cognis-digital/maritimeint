# Demo 01 - Basic: Suspected ship-to-ship transfer

This scenario contains a small AIS feed for three vessels operating off the
South China Sea. Two of them exhibit the classic sanctions-evasion playbook.

## Vessels

- **477123456 (HORIZON STAR)** - a tanker that goes dark for ~10 hours, then
  loiters in open water and meets another ship.
- **352987654 (BLUE PEARL)** - the second tanker; it loiters at the same spot
  and stays within half a nautical mile of HORIZON STAR for over an hour
  (a ship-to-ship transfer signature).
- **636099887 (CLONE)** - a spoofed identity: the same MMSI "teleports"
  across the ocean far faster than any ship can travel, and broadcasts two
  conflicting vessel names.

## Run it

```bash
python -m maritimeint analyze demos/01-basic/feed.json
python -m maritimeint --format json analyze demos/01-basic/feed.json
python -m maritimeint gaps demos/01-basic/feed.json --gap-hours 6
python -m maritimeint rendezvous demos/01-basic/feed.json
```

## Expected signals

- `ais_gap` on 477123456 (~10h dark window)
- `loitering` on both tankers
- `rendezvous` between 477123456 and 352987654
- `speed_jump` + `identity_conflict` on 636099887

The `analyze` risk ranking should place the spoofed MMSI and the two
rendezvousing tankers at the top.
