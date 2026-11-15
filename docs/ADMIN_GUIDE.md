# BizPilot AI — Administrator Guide

## Roles and permissions

Six roles ship with the application: Super Admin, Business Admin, Finance Manager,
Sales Manager, Inventory Manager and Employee. Custom roles can be created from
**Roles and Permissions** with any combination of the 62 permissions. Permissions are
enforced in the service layer, so hiding a button is never the only protection.

| Role | Typical access |
| --- | --- |
| Super Admin | Everything, including security and backups |
| Business Admin | All business modules, approvals, analytics, knowledge, security view |
| Finance Manager | Finance, approvals, reports |
| Sales Manager | Sales, customers, sales analytics |
| Inventory Manager | Inventory, suppliers, purchase orders |
| Employee | Dashboard and read-only views |

## AI providers

**AI Providers** (Knowledge Center) and **AI Governance** (Security Center) control
routing. Four policies: Local first, Cloud first, Task based, Offline. Cloud sharing is
off by default; enabling it still never sends RESTRICTED data (credentials, keys) and
redacts CONFIDENTIAL content.

## Autonomy policies

**Operations Center → Autonomy** lists every allowlisted action with its mode:
AUTOMATIC, APPROVAL or RESTRICTED. Set maximum amounts, allowed roles and daily limits.
Deleting financial history is restricted by code and cannot be made automatic.

## Approvals

**Operations Center → Approvals** shows each request with the exact action, financial
impact, evidence and risk. Approving executes once; changing the amount, supplier,
quantity or items invalidates the approval and requires a new one. A user cannot approve
their own request when another eligible approver exists.

## Document permissions

Restricted documents are visible only to named roles or users, or to holders of
`knowledge.manage`. Filters are applied before retrieval, so restricted text never
reaches the AI.

## Security monitoring

**Security Center → Monitoring** turns repeated failed logins, access denials, export
bursts and permission changes into reviewable events. Mark them acknowledged, dismissed
or confirmed incident. These are indicators, not accusations.

## Backups

Create a backup from **Security Center → Backup**. Backups are integrity-checked before
being recorded. Restores require explicit confirmation and a valid backup. Back up
`%LOCALAPPDATA%\BizPilotAI\secrets\app.key` separately — without it, MFA enrolments
cannot be decrypted.

## Updates

1. Create a backup.
2. Run the new installer over the existing installation.
3. Launch once so migrations apply.
4. Verify in **Settings → About** that the version and schema are current.

If a migration fails, the application stops and logs the reason in
`%LOCALAPPDATA%\BizPilotAI\logs`. Restore the backup before retrying.
