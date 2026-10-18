# Comparison: simulated AWS deployment vs simulated on-prem deployment

The brief asks for three axes (cost, complexity, output quality) and one
specific recommendation: which deployment for a client with strict data
residency requirements, and which for one without. Both deployments ran the
same frozen test input (the Week 8 CASE-001 states scored by
`riskservice`); the run transcripts embedded as exhibits 3 and 6 carry the
measured outputs and the shared input hash.

## What was actually compared

- Cloud-style: the task runs under the least-privilege role in the simulated
  VPC's private application subnet; its model call goes to the
  managed-endpoint stand-in (qwen3:8b, the model id a real deployment would
  pin as its Bedrock model).
- On-prem-style: the same service on the same machine calls the boundary's
  local Ollama server hosting a deliberately smaller open-weight model
  (qwen3:4b).

Using two genuinely different model sizes is deliberate: the brief expects the
on-prem side to acknowledge that a smaller open-weight model may reason
differently, and a same-model comparison would be identical by construction.

## Cost

Cloud-style (real-deployment shape, illustrative): an always-on Fargate task,
an ECR repository, a NAT path for the private subnet, plus per-token managed
model charges. The task itself is small, but the always-on footprint and the
managed model bill scale with traffic; at low, bursty volume you pay for idle
capacity. On-prem-style: hardware the client already owns inside the boundary,
zero per-token charges, and the marginal cost of a scoring call is
electricity. The trade is money for control: article 3's "real tradeoff"
framing, convenience versus control and compliance. The honest cost caveat on
the on-prem side is capacity engineering: serving many simultaneous
production users needs properly sized infrastructure (vLLM on server hardware,
article 3, Use Case 2), which is a capital line, not a subscription line.

## Complexity

Cloud-style carries the platform's complexity surface: IAM roles and policy
linting, registry and digest discipline, task definitions, subnets and
security groups. That complexity is exactly what this lab built, and it buys
auditability: every permission is written down, enforced, and evidenced
(exhibit 1). Operations are simpler though: the platform runs the task, keeps
the model warm and current, and scales the replica count.

On-prem-style is operationally simpler to reason about (one server, one model
file, no credentials anywhere) but pushes every platform concern onto the
owner: model hosting and upgrades, capacity, and the change-control process
from article 3 (Use Case 1), where even a dependency update moves at the
client's audit pace. The code side is a wash by design: the same service, one
endpoint flag different.

## Output quality

Both deployments scored the same frozen input at temperature 0, and both
transcripts print the same input hash:
`b8963dc4177b0055e8bf085c1b64e99022e90eaa02cc18a19cd8fe5545e7a2ce`
(exhibits 3 and 6).

The Week 8 recorded qwen3:8b reference, embedded in the input file, scored
the case 15 with three 5-point factors and used 218 input and 152 output
tokens.

The simulated AWS task, also qwen3:8b, reproduced that reference. Score 15.
Factors: Credit Band 5, No Prior Claims 5, Vehicle Age 5. The rationale calls
the case low underwriting risk. Usage was `model=qwen3:8b input_tokens=218
output_tokens=152 duration_ms=10028.1`. The factor points sum to the score,
so validation accepted the result (exhibit 3).

The on-prem deployment itself ran and validated on this input with the
resident qwen3:8b: score 15, the same three factors, 218/152 tokens,
9538.4 ms (exhibit 6, first capture). The on-prem side therefore runs
successfully and produces reasonable output; the smaller-model observation
below is what the brief asks to note on top of that.

The on-prem qwen3:4b run produced no score. After the one allowed repair
call, the reply was still not JSON (`invalid JSON from model after repair:
Expecting value: line 1 column 1 (char 0)`). The transcript records that
error and then the shared input hash. It has no factor breakdown and no
usage line, because usage is printed only after a validated result
(exhibit 6, second capture).

That is the measured quality difference on this input. The 8B model matched
the reference on both targets. The 4B model failed schema discipline, and the
service refused the reply instead of recording a score, which is the
factor-sum guardrail doing its job: a score that cannot explain itself never
reaches the transcript.

## Recommendation

- **Client with strict data residency requirements: the on-prem deployment.**
  Not primarily for security hygiene, but because for such a client the cloud
  option is often not merely worse but non-compliant: an inference call is a
  data transfer (article 4, Use Case 2), each external service triggers a
  vendor-risk review that may end in "not approved" (Use Case 3), and model
  risk management wants a version-pinned model the client can freeze and
  validate (Use Case 4). The on-prem variant satisfies all three by
  construction: no external call exists, the model id is pinned, and the
  factor-sum gate provides the output auditability such clients need. At
  production scale, serve it with vLLM on sized hardware (article 3) rather
  than the development-grade Ollama used here.
- **Client without residency or sovereignty constraints: the cloud-style
  deployment.** It inherits the platform's access control, logging, and
  elasticity story, keeps the model operations with the provider, and its
  costs track usage instead of capital. The least-privilege role and the
  one-egress-rule placement travel with it, so the security posture does not
  depend on where the workload runs.

## Simulation caveat, restated

Neither side touched a real cloud or a real client data center: the "AWS" side
is a local control-plane simulation, and the "on-prem" side is a laptop-class
model server. What transfers to a real engagement is the architecture and its
enforcement: a scoped role with per-permission justifications, a
deny-by-default placement, a digest-pinned artifact, one frozen input
confirmed on both targets, and a deployment whose guarantees are checked by
code before anything executes.
