# Risk x Delay Escalation Tiers

## Tier Definitions
- T1 Normal: delay probability below 0.4 and risk class low. Routine
  monitoring.
- T2 Watch: delay probability 0.4 to below 0.7, or risk class medium.
  Increase tracking cadence and monitor the next readings.
- T3 High: delay probability at or above 0.7, or risk class high.
  Proactive customer notification and evaluate the port diversion playbook.
- T4 Critical: a confirmed temperature breach with delay probability at or
  above 0.7, or high risk with delay probability at or above 0.8.
  Quarantine the trailer, start the breach protocol, prepare reroute or
  diversion options, and notify the customer proactively.

## Required Actions per Tier
Each tier's actions are mandatory, not advisory. Skipping a T3 customer
notification or a T4 quarantine is a compliance violation and is flagged in
the audit review.

## Confirmation Gates
T3 and T4 high-impact actions — rerouting a shipment, diverting a port call,
or cancelling a shipment — require explicit human confirmation through the
confirmation gate before execution. The gate token, the approver, and the
decision timestamp are recorded in the audit log. No autonomous rerouting.
