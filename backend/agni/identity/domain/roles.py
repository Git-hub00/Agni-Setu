"""Role keys, workspaces and capability names (security s.5 permission matrix; ADR-05).

A role binding admits a workspace and its baseline read scope. Statutory powers (deciding,
approving grants/policies, certificate status instruments) are separate approved
`AuthorityGrant` capabilities and are never implied by a role.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class RoleKey(StrEnum):
    OFFICER = "OFFICER"
    SUPERVISOR = "SUPERVISOR"
    LEADERSHIP = "LEADERSHIP"
    ADMIN = "ADMIN"
    POLICY_APPROVER = "POLICY_APPROVER"


class Workspace(StrEnum):
    APPLICANT = "applicant"
    OFFICER = "officer"
    SUPERVISOR = "supervisor"
    LEADERSHIP = "leadership"
    ADMIN = "admin"
    POLICY = "policy"
    PUBLIC = "public"


ROLE_WORKSPACE: Final[dict[RoleKey, Workspace]] = {
    RoleKey.OFFICER: Workspace.OFFICER,
    RoleKey.SUPERVISOR: Workspace.SUPERVISOR,
    RoleKey.LEADERSHIP: Workspace.LEADERSHIP,
    RoleKey.ADMIN: Workspace.ADMIN,
    RoleKey.POLICY_APPROVER: Workspace.POLICY,
}


class Capability(StrEnum):
    """Separately granted powers (data model `authority_grant.capability`)."""

    CASE_DECIDE = "case.decide"
    CERTIFICATE_STATUS = "certificate.status"
    POLICY_APPROVE = "policy.approve"
    POLICY_ACTIVATE = "policy.activate"
    GRANT_APPROVE = "grant.approve"
    STAFF_PROVISION = "staff.provision"
    EXPORT_SENSITIVE = "export.sensitive"
    NOTICE_PUBLISH = "notice.publish"


class ScopeKind(StrEnum):
    GLOBAL = "GLOBAL"
    JURISDICTION = "JURISDICTION"
    SERVICE = "SERVICE"
