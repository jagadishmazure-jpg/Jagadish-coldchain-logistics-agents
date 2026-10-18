# Port Congestion Diversion Playbook

## Diversion Triggers
Consider diversion when ALL of the following hold: port congestion is rated
high or severe, the shipment delay probability is at or above 0.6, and the
cargo is perishable with less than 48 hours of remaining shelf life. If any
trigger is missing, monitor instead of diverting.

## Approved Alternate Ports
POLA, POLB, and SAN are mutually approved alternates for Southern California
reefer freight. Diversion to any other port requires VP Operations approval.
The playbook assumes drayage capacity is confirmed before the diversion order
is issued; never divert a load without a confirmed drayage slot.

## Confirmation Gate
Every diversion order requires dispatcher confirmation in the system before
it is sent to the driver. The confirmation, the congestion readings, and the
delay probability at decision time are written to the audit log. Automatic
diversion without human confirmation is prohibited.

## Post-Diversion
After diversion, increase tracking cadence to every 30 minutes until the
load clears the alternate port. Notify the customer of the new ETA within
one hour of the diversion decision.
