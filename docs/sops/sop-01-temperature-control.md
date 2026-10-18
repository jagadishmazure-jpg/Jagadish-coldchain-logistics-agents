# Cold-Chain Temperature Control Standard

## Fresh Perishables 0-4 C Rule
All fresh perishable cargo (dairy, produce, seafood, prepared foods) must be
held between 0 C and 4 C for the entire journey, from warehouse dispatch to
customer handoff. Any IoT reading above 4.0 C or below 0.0 C is a temperature
breach and triggers the breach response protocol. There are no grace degrees:
4.1 C is a breach.

## Frozen Goods -18 C or Below
Frozen cargo must remain at -18 C or below. Brief excursions to -15 C during
door openings are logged but do not trigger the breach protocol unless they
persist beyond 20 minutes.

## Monitoring Cadence
Reefer IoT sensors report temperature every 15 minutes. The dispatcher
dashboard flags any trailer with two consecutive out-of-range readings.
Manual thermometer checks are required at loading and unloading and must be
logged against the shipment record.

## Calibration
All reefer temperature probes are calibrated monthly against a reference
thermometer. A probe found drifting more than 0.5 C is replaced and the
trailer is quarantined until the replacement is verified.
