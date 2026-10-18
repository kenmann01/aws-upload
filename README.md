# aws-upload

Week 9 lab (GenSpark FDE course): take ONE agent from the Week 8 multi-agent
underwriting pipeline and deploy it two ways, then document and compare the
deployments.

- **Agent deployed:** the risk scoring agent (`risk_scoring_agent`), one of the
  two agents the lab brief suggests.
- **Target 1, "AWS":** a local, hand-rolled simulation of the AWS control plane
  (`simaws`): IAM roles with enforced least privilege, ECR-style registry,
  ECS-style task definitions and run-task with real IAM authorization checks,
  VPC/subnet/security-group config with a placement validator. No cloud account
  is used and no cloud service is called. Everything runs locally.
- **Target 2, "simulated on-prem":** the same service pointed at a local
  Ollama open-weight model, the Week 5/8 pattern the course uses to stand in
  for private model hosting inside a client boundary.

Both deployments run the **same frozen test input**: the real intake and
enrichment outputs that qwen3:8b produced for CASE-001 (Dana Whitfield) in the
Week 8 pipeline run, lifted verbatim from a committed Week 8 trace.

## Repo layout

```
deploy/input/test_input.json   frozen test input for both deployments
deploy/iam-policy.json         the task role's policy document (with per-statement justifications)
deploy/network.json            simulated VPC/subnet/security-group placement
src/riskservice/               the deployable unit: agent + LLM clients + CLI entrypoint
src/simaws/                    the simulated AWS control plane (iam, network, registry, ecs, cli)
scripts/deploy_aws_sim.py      end-to-end deployment to the simulated AWS environment
scripts/deploy_onprem.py       end-to-end deployment to local Ollama
docs/                          deployment document + comparison (rubric parts 3)
evidence/                      captured run transcripts (committed after run day)
```

## Quickstart

```
uv sync
uv run pytest -q                                    # offline, scripted backend
uv run python scripts/deploy_aws_sim.py --backend scripted
uv run python scripts/deploy_onprem.py --backend scripted
```

Run day (machine with Ollama):

```
ollama pull qwen3:4b                                # on-prem side model, one time
uv run python scripts/deploy_aws_sim.py | tee evidence/aws_sim_run.txt
uv run python scripts/deploy_onprem.py | tee evidence/onprem_run.txt
```

## Provenance

`src/riskservice` ports the risk scoring agent, its models, and the LLM client
layer from `kenmann01/insurance-orchestrator` at commit `c0fd857` (Week 8
submission). The frozen test input comes from that repo's committed trace
`4b9f20251da84cb5ac6e9d78f9f8b0f5`. Everything else (simaws, deploy scripts,
docs) is new for this lab.

The `simaws` control plane is a teaching simulation, not an AWS emulator:
resource state lives in a local JSON file, ARNs use the `arn:simaws:` prefix,
and the only "API" it calls is the local machine.
