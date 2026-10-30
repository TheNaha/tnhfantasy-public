# Spec Delta

## Purpose

Defines the provider contract so Modal, Beam, direct_url, and remote_agent engines stay aligned with their deployables and health checks, and job dispatch never silently fails.

## ADDED Requirements

### Requirement: Deployable-engine mapping

Each cloud worker (Modal, Beam, direct_url, remote_agent) SHALL map to exactly one engine in `services/engines/` as recorded in `deployables/README.md`.

#### Scenario: Engine has a deployable source

- **WHEN** an engine is configured in `services/engines/`
- **THEN** `deployables/README.md` lists a corresponding deployable for it

### Requirement: Health gating on provider status

A provider SHALL be considered healthy only when its status is `healthy`, and `enabled: false` SHALL mean the user paused it intentionally, never broken.

#### Scenario: Enabled false is not broken

- **WHEN** a provider has `enabled: false`
- **THEN** the system does not raise "needs attention" or propose deleting it

### Requirement: Provider core fork parity

The `deployables/provider_worker_core` and `remote_agent/provider_core` trees SHALL stay forked and never be unified; parity between them is pinned by contract test.

#### Scenario: Forks are not unified

- **WHEN** comparing `deployables/provider_worker_core` to `remote_agent/provider_core`
- **THEN** they remain separate trees with a pinned parity contract

### Requirement: Load balancer gates on healthy status

The load balancer SHALL only dispatch to providers whose status is `healthy`, and class-level state SHALL not accumulate untracked async tasks.

#### Scenario: Dispatch only to healthy providers

- **WHEN** selecting a provider for a job
- **THEN** only providers with `status == "healthy"` are eligible
