# Security

ArchAI treats requirements, retrieved content, tool descriptions, and imported metadata as untrusted
data. It never executes instructions from those sources and never deploys generated infrastructure.

Keep architect-provider credentials in environment variables or an approved secret manager. Generated
configuration contains secret references only. Source snapshots and local project state may be
sensitive; the project store uses restrictive local file permissions, but operators remain responsible
for disk encryption, backups, retention, and access control.

Report vulnerabilities privately to the repository owner rather than opening a public issue containing
secrets or exploit details.

